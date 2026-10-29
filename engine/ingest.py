# -*- coding: utf-8 -*-
"""数据录入：一分一段表、校线（离线索引 + 在线接口）、位次换算。

设计要点：
- 一分一段表来自省考试院整理好的 JSON（随仓库固化在 data/raw/yifenyiduan）。
- 校线：2023/2024/2025 走离线索引（1 个文件覆盖 3145 校），2026 走实时接口。
- 换算严格同年对齐；没有对应年份的表就跳过并计数，绝不跨年硬凑。
"""
import glob
import gzip
import json
import os
import time
import urllib.request
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor

from . import config, store


# ---------------------------------------------------------------- 一分一段表

def ingest_rank_tables(conn, raw_dir=None, verbose=True):
    """把 data/raw/yifenyiduan/*.json 全部灌入 rank_table。"""
    raw_dir = raw_dir or config.RANK_RAW_DIR
    files = sorted(glob.glob(os.path.join(raw_dir, '*.json')))
    if not files:
        raise FileNotFoundError(f'没有找到一分一段表文件: {raw_dir}')

    total = 0
    for fp in files:
        with open(fp, encoding='utf-8') as f:
            data = json.load(f)
        # province 字段是拼音，province_name 是中文
        province = data.get('province_name')
        if not province:
            raise ValueError(f'{fp} 缺少 province_name')
        year = int(data['year'])
        track = data['track']
        if track not in config.TRACK_CN:
            raise ValueError(f'{fp} 未知科类: {track}')
        source = data.get('source')
        url = data.get('source_url')

        rows = []
        for r in data.get('rows') or []:
            try:
                score = int(r['score'])
                cum = int(r['cumulative'])
            except (KeyError, TypeError, ValueError):
                continue
            cnt = r.get('count')
            rows.append((province, year, track, score,
                         int(cnt) if cnt is not None else None,
                         cum, source, url))
        conn.executemany(
            'INSERT INTO rank_table(province,year,track,score,cnt,cumulative,source,source_url) '
            'VALUES(?,?,?,?,?,?,?,?) '
            'ON CONFLICT(province,year,track,score) DO UPDATE SET '
            '  cnt=excluded.cnt, cumulative=excluded.cumulative, '
            '  source=excluded.source, source_url=excluded.source_url',
            rows)
        total += len(rows)
        if verbose:
            print(f'  {os.path.basename(fp):<32} {year} {config.TRACK_CN[track]:<4} {len(rows):>4} 行')
    conn.commit()
    store.set_meta(conn, 'rank_tables_ingested_at', time.strftime('%Y-%m-%d %H:%M:%S'))
    return total


# ---------------------------------------------------------------- 离线校线索引

def ingest_school_index(conn, gz_path=None, verbose=True):
    """导入 3145 校的学校元信息 + 2023~2025 校线（离线索引）。"""
    gz_path = gz_path or config.SCHOOL_INDEX_GZ
    if not os.path.exists(gz_path):
        raise FileNotFoundError(f'没有找到学校索引: {gz_path}')

    with gzip.open(gz_path, 'rt', encoding='utf-8') as f:
        data = json.load(f)
    rows = data.get('rows') or []

    schools, scores = [], []
    for r in rows:
        try:
            sid = int(r['gaokao_cn_id'])
        except (KeyError, TypeError, ValueError):
            continue
        schools.append((
            sid, r.get('name') or '', r.get('province'), r.get('city'),
            r.get('level'), r.get('type'), r.get('nature'), r.get('belong'),
            1 if r.get('f985') else 0, 1 if r.get('f211') else 0, r.get('dual_class'),
        ))
        ptm = r.get('pro_type_min') or {}
        for prov_name, pid in config.PROVINCE_IDS.items():
            for entry in ptm.get(str(pid)) or []:
                try:
                    year = int(entry.get('year'))
                except (TypeError, ValueError):
                    continue
                for code, sc in (entry.get('type') or {}).items():
                    track = config.TRACK_FROM_CODE.get(str(code))
                    if not track:
                        continue
                    try:
                        val = int(float(sc))
                    except (TypeError, ValueError):
                        continue
                    if val <= 0:
                        continue
                    scores.append((sid, prov_name, year, track, val,
                                   config.SOURCE_INDEX, None))

    conn.executemany(
        'INSERT INTO school(id,name,province,city,level,type,nature,belong,f985,f211,dual_class) '
        'VALUES(?,?,?,?,?,?,?,?,?,?,?) '
        'ON CONFLICT(id) DO UPDATE SET name=excluded.name, province=excluded.province, '
        '  city=excluded.city, level=excluded.level, type=excluded.type, '
        '  nature=excluded.nature, belong=excluded.belong, f985=excluded.f985, '
        '  f211=excluded.f211, dual_class=excluded.dual_class',
        schools)
    _upsert_scores(conn, scores)
    conn.commit()
    store.set_meta(conn, 'school_index_generated_at', data.get('generated_at') or '')
    if verbose:
        print(f'  学校 {len(schools)} 所，离线校线 {len(scores)} 条 '
              f'(索引生成于 {data.get("generated_at", "?")[:10]})')
    return len(scores)


# ---------------------------------------------------------------- 实时校线

def _fetch_school_info(sid, timeout=20, retries=2):
    url = f'{config.API_BASE}/school/{sid}/info.json'
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': config.API_UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode('utf-8'))
            if body.get('code') != '0000':
                return None
            return body.get('data') or {}
        except Exception:
            if attempt >= retries:
                return None
            time.sleep(0.4 * (attempt + 1))
    return None


def _extract_scores(sid, data, provinces, years):
    """从 info.json 的 pro_type_min 里抽出目标省份/年份的校线。"""
    filled_parts = []
    ptm = (data or {}).get('pro_type_min') or {}
    url = f'{config.API_BASE}/school/{sid}/info.json'
    for prov_name, pid in provinces.items():
        for entry in ptm.get(str(pid)) or []:
            try:
                year = int(entry.get('year'))
            except (TypeError, ValueError):
                continue
            if years and year not in years:
                continue
            for code, sc in (entry.get('type') or {}).items():
                track = config.TRACK_FROM_CODE.get(str(code))
                if not track:
                    continue
                try:
                    val = int(float(sc))
                except (TypeError, ValueError):
                    continue
                if val <= 0:
                    continue
                filled_parts.append((sid, prov_name, year, track, val,
                                     config.SOURCE_LIVE, url))
    return filled_parts


def fetch_live_scores(conn, provinces=None, years=(config.REFERENCE_YEAR,),
                      workers=8, limit=None, verbose=True):
    """逐校拉 info.json，补录实时校线（默认只补 2026）。"""
    provinces = provinces or config.PROVINCE_IDS
    years = tuple(years) if years else None

    school_ids = [r['id'] for r in conn.execute(
        'SELECT id FROM school ORDER BY f985 DESC, f211 DESC, id')]
    if limit:
        school_ids = school_ids[:limit]
    if not school_ids:
        raise RuntimeError('学校表为空，请先运行 ingest_school_index')

    buf, total, done, failed = [], 0, 0, 0

    def work(sid):
        data = _fetch_school_info(sid)
        if not data:
            return sid, None
        return sid, _extract_scores(sid, data, provinces, years)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for sid, out in ex.map(work, school_ids):
            done += 1
            if out is None:
                failed += 1
            else:
                buf.extend(out)
                total += len(out)
            if len(buf) >= 400:
                _upsert_scores(conn, buf)
                conn.commit()
                buf = []
            if verbose and done % 500 == 0:
                rate = done / max(time.time() - t0, 1e-6)
                print(f'  ... {done}/{len(school_ids)}  已录入 {total} 条  '
                      f'{rate:.1f} 校/秒  失败 {failed}')

    _upsert_scores(conn, buf)
    conn.commit()
    if verbose:
        print(f'  实时校线完成：{len(school_ids)} 校，录入 {total} 条，失败 {failed}，'
              f'耗时 {time.time() - t0:.0f}s')
    store.set_meta(conn, 'live_scores_fetched_at', time.strftime('%Y-%m-%d %H:%M:%S'))
    return total


def _upsert_scores(conn, rows):
    if not rows:
        return
    conn.executemany(
        'INSERT INTO school_score(school_id,province,year,track,min_score,source,source_url) '
        'VALUES(?,?,?,?,?,?,?) '
        'ON CONFLICT(school_id,province,year,track) DO UPDATE SET '
        '  min_score=excluded.min_score, source=excluded.source, '
        '  source_url=excluded.source_url',
        rows)


# ---------------------------------------------------------------- 位次换算落库

def build_school_rank(conn, verbose=True):
    """把 school_score 里每条校线换算成最低位次，写入 school_rank。

    严格同年对齐：用 (省, 年, 科类) 的一分一段表换算。
    若该分数不在表内（表有空档），取「分数更高」的临近档 —— 位次更靠前，
    对考生偏保守，避免把学校算得比实际更容易。
    """
    series = {}
    for r in conn.execute(
            'SELECT province, year, track, score, cumulative FROM rank_table '
            'ORDER BY province, year, track, score ASC'):
        key = (r['province'], r['year'], r['track'])
        scores, cums = series.setdefault(key, ([], []))
        scores.append(r['score'])
        cums.append(r['cumulative'])

    rows, exact, approx, missing = [], 0, 0, 0
    for r in conn.execute(
            'SELECT school_id, province, year, track, min_score FROM school_score'):
        key = (r['province'], r['year'], r['track'])
        if key not in series:
            missing += 1
            continue
        scores, cums = series[key]
        pos = bisect_left(scores, r['min_score'])
        if pos < len(scores) and scores[pos] == r['min_score']:
            exact += 1
        elif pos < len(scores):
            approx += 1
        else:
            pos = len(scores) - 1
            approx += 1
        rows.append((r['school_id'], r['province'], r['year'], r['track'],
                     r['min_score'], cums[pos]))

    conn.execute('DELETE FROM school_rank')
    conn.executemany(
        'INSERT INTO school_rank(school_id,province,year,track,min_score,min_rank) '
        'VALUES(?,?,?,?,?,?)', rows)
    conn.commit()
    if verbose:
        print(f'  位次换算：{len(rows)} 条（精确 {exact}，近似 {approx}，'
              f'缺当年一分一段表而跳过 {missing}）')
    store.set_meta(conn, 'school_rank_built_at', time.strftime('%Y-%m-%d %H:%M:%S'))
    return len(rows)


# ---------------------------------------------------------------- 一站式初始化

def bootstrap(conn, with_live=True, workers=8, limit=None, verbose=True):
    store.init_db(conn)
    if verbose:
        print('[1/4] 一分一段表')
    ingest_rank_tables(conn, verbose=verbose)
    if verbose:
        print('[2/4] 学校索引 + 2023~2025 校线')
    ingest_school_index(conn, verbose=verbose)
    if with_live:
        if verbose:
            print('[3/4] 实时校线（2026）')
        fetch_live_scores(conn, workers=workers, limit=limit, verbose=verbose)
    else:
        if verbose:
            print('[3/4] 跳过实时校线')
    if verbose:
        print('[4/4] 换算最低位次')
    n = build_school_rank(conn, verbose=verbose)
    return store.counts(conn), n
