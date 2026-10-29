# -*- coding: utf-8 -*-
"""分专业 / 招生计划入库（P6 + P9）。

两个接口，前缀不同，用错会返回 1064「接口请求版本不存在」：

    分专业录取线    apidata/api/gk/score/special   ?school_id&local_province_id&local_type_id&year
    招生计划+学费   apidata/api/gkv3/plan/school   ?school_id&local_province_id&local_type_id&year

两者都带 `special_group`（专业组 id），是天然的关联键。
一个 `special_group` 就是一个「院校专业组」——湖南/广东的志愿填报单位，
组内各专业选科要求必须相同（见《湖南省2026年普通高等学校招生工作实施办法》）。

【关键口径】分专业数据目前只到 2025（2026 尚稀）。而推荐用的是 2026 校线。
所以入库时把组线的 2025 位次换算成 **2026 等效位次**（2025 位次 -> 2025 分数 -> 2026 位次），
否则就是跨年混算。换算不了的行 `ref_rank` 留空，不硬凑。

【坑】
- `size` 上限 20，`size=50` 会静默返回空列表（code 仍是 0000）。
- 服务端偶发 SSL EOF，必须重试。
- 逐校抓：全省一次翻页会封顶约 3600 条。
"""
import http.client
import json
import random
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, convert, store

REF_YEAR = config.REFERENCE_YEAR
_TLS = threading.local()

# 全局限速（自适应）：实测这个接口会在持续高频后返回 HTTP 429。
# 用一个全局最小间隔把并发压到一个安全速率，遇到 429 就自动放慢，连续成功再慢慢放开。
_PACE_LOCK = threading.Lock()
_PACE = {'last': 0.0, 'min': 0.40}


def _pace():
    with _PACE_LOCK:
        now = time.time()
        wait = _PACE['last'] + _PACE['min'] - now
        if wait > 0:
            time.sleep(wait)
            now = time.time()
        _PACE['last'] = now


def _slow_down():
    with _PACE_LOCK:
        _PACE['min'] = min(3.0, _PACE['min'] * 1.5)


def _speed_up():
    with _PACE_LOCK:
        _PACE['min'] = max(0.60, _PACE['min'] * 0.998)


def _int(v):
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _conn():
    """每线程复用一条 HTTPS 长连接：实测比每次新建快 3 倍（3.4s -> 1.1s/请求）。"""
    c = getattr(_TLS, 'conn', None)
    if c is None:
        c = http.client.HTTPSConnection('api.zjzw.cn', timeout=25)
        _TLS.conn = c
    return c


def _drop_conn():
    c = getattr(_TLS, 'conn', None)
    if c is not None:
        try:
            c.close()
        except Exception:
            pass
    _TLS.conn = None


def _get(params, retries=7):
    """请求一个 api.zjzw.cn 接口，返回 data 字段。

    - 429 限流：全局放慢 + 指数退避重试（实测连续抓几千次后必然出现）
    - 1064/1070：端点或参数错，重试没有意义，直接抛
    """
    path = '/web/api/?' + urllib.parse.urlencode(params)
    last = ''
    for i in range(retries):
        try:
            _pace()
            c = _conn()
            c.request('GET', path, headers=config.ZJZW_HEADERS)
            resp = c.getresponse()
            raw = resp.read()
            if resp.status == 429:
                _drop_conn()
                _slow_down()
                last = 'HTTP 429 限流'
                time.sleep(1.5 + 1.2 * min(i, 5) + random.random())
                continue
            if resp.status != 200:
                raise IOError('HTTP %s' % resp.status)
            j = json.loads(raw.decode('utf-8', 'replace'))
            code = str(j.get('code'))
            if code == '0000':
                _speed_up()
                return j.get('data') or {}
            if code == '1069':          # 另一种限流写法
                _slow_down()
                last = 'code=1069 限流'
                time.sleep(1.5 + 1.2 * min(i, 5) + random.random())
                continue
            if code in ('1064', '1070'):
                raise ValueError('接口错误 code=%s %s' % (code, j.get('message')))
            last = 'code=%s %s' % (code, j.get('message'))
        except ValueError:
            raise
        except Exception as e:  # 网络/SSL/超时/连接被服务端关掉
            last = '%s: %s' % (type(e).__name__, str(e)[:100])
            _drop_conn()
        time.sleep(0.4 * (i + 1))
    raise IOError('请求失败: %s' % last)


def _paged(params, uri):
    """按页取全（size 上限 20）。"""
    out, page, total = [], 1, None
    while page <= 80:
        p = dict(params)
        p.update({'uri': uri, 'page': page, 'size': config.ZJZW_PAGE_SIZE})
        d = _get(p)
        total = int(d.get('numFound') or 0)
        items = d.get('item') or []
        if not items:
            break
        out.extend(items)
        if total and len(out) >= total:
            break
        page += 1
    return out


def fetch_school(school_id, province, track, year):
    """抓一所学校在某省某年某科类的专业组数据，返回 (groups, majors)。"""
    base = {
        'school_id': school_id,
        'local_province_id': config.PROVINCE_IDS[province],
        'local_type_id': 2073 if track == 'physics' else 2074,
        'year': year,
    }
    score_rows = _paged(base, config.ZJZW_URI_SCORE)
    plan_rows = _paged(base, config.ZJZW_URI_PLAN)
    return _merge(score_rows, plan_rows)


def _merge(score_rows, plan_rows):
    groups, majors = {}, []

    def g(gid):
        return groups.setdefault(gid, {
            'grp': gid, 'sg_name': '', 'sg_info': '', 'batch': '',
            'plan_num': 0, 'tuition': None,
            'min_score': None, 'min_rank': None, 'majors': set(),
        })

    for r in plan_rows:
        gid = _int(r.get('special_group'))
        if not gid:
            continue
        x = g(gid)
        x['sg_name'] = x['sg_name'] or (r.get('sg_name') or '').strip()
        x['sg_info'] = x['sg_info'] or (r.get('sg_info') or '').strip()
        x['batch'] = x['batch'] or (r.get('local_batch_name') or '').strip()
        num = _int(r.get('num')) or 0
        x['plan_num'] += num
        tui = _int(r.get('tuition'))
        if tui and not x['tuition']:
            x['tuition'] = tui
        sp = (r.get('spname') or r.get('sp_name') or '').strip()
        if not sp:
            continue
        x['majors'].add(sp)
        majors.append({
            'grp': gid, 'spname': sp, 'src': 'plan',
            'plan_num': _int(r.get('num')), 'tuition': tui,
            'length': (r.get('length') or '').strip(),
            'min_score': None, 'min_rank': None, 'avg_score': None, 'max_score': None,
        })

    for r in score_rows:
        gid = _int(r.get('special_group'))
        if not gid:
            continue
        x = g(gid)
        x['sg_name'] = x['sg_name'] or (r.get('sg_name') or '').strip()
        x['sg_info'] = x['sg_info'] or (r.get('sg_info') or '').strip()
        x['batch'] = x['batch'] or (r.get('local_batch_name') or '').strip()
        mn, sec = _int(r.get('min')), _int(r.get('min_section'))
        if mn and (x['min_score'] is None or mn < x['min_score']):
            x['min_score'] = mn
        if sec and (x['min_rank'] is None or sec > x['min_rank']):
            x['min_rank'] = sec
        sp = (r.get('spname') or r.get('sp_name') or '').strip()
        if not sp:
            continue
        x['majors'].add(sp)
        majors.append({
            'grp': gid, 'spname': sp, 'src': 'score',
            'min_score': mn, 'min_rank': sec,
            'avg_score': _int(r.get('average')), 'max_score': _int(r.get('max')),
            'plan_num': None, 'tuition': None, 'length': '',
        })

    out = []
    for gid, x in groups.items():
        if not (x['min_score'] or x['plan_num']):
            continue
        x['n_major'] = len(x['majors'])
        x.pop('majors', None)
        out.append(x)
    return out, majors


def _equiv_rank(conn, province, track, rank, year, ref_year=REF_YEAR):
    """把某年的位次换算成参考年（2026）的等效位次。换算不了就返回 None。"""
    if not rank:
        return None
    if year == ref_year:
        return rank
    s = convert.rank_to_score(conn, province, year, track, rank)
    if not s:
        return None
    r = convert.score_to_rank_safe(conn, province, ref_year, track, s['score'])
    return r['rank'] if r else None


def _write(conn, school_id, province, track, year, groups, majors):
    rows_g, rows_m = [], []
    for x in groups:
        rows_g.append((
            school_id, province, year, track, x['grp'], x['sg_name'], x['sg_info'],
            x['batch'], x['plan_num'] or None, x['tuition'],
            x['min_score'], x['min_rank'],
            _equiv_rank(conn, province, track, x['min_rank'], year),
            x['n_major'],
        ))
    for m in majors:
        rows_m.append((
            school_id, province, year, track, m['grp'], m['spname'], m['src'],
            m['min_score'], m['min_rank'], m['avg_score'], m['max_score'],
            m['plan_num'], m['tuition'], m['length'],
        ))
    conn.executemany(
        'INSERT OR REPLACE INTO special_group('
        ' school_id,province,year,track,grp,sg_name,sg_info,batch,plan_num,tuition,'
        ' min_score,min_rank,ref_rank,n_major) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        rows_g)
    conn.executemany(
        'INSERT OR REPLACE INTO special_major('
        ' school_id,province,year,track,grp,spname,src,min_score,min_rank,avg_score,'
        ' max_score,plan_num,tuition,length) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        rows_m)
    return len(rows_g), len(rows_m)


def ingest(conn, province, track, year=None, workers=10, limit=None,
           reload=False, verbose=True):
    """抓某省某科类全部分专业数据。可断点续跑（已入库的学校默认跳过）。"""
    year = int(year or config.SPECIAL_YEAR)
    ph = config.PROVINCE_IDS.get(province)
    if not ph:
        raise ValueError('未收录的省份: %s' % province)

    ids = set()
    for (sid,) in conn.execute(
            'SELECT DISTINCT school_id FROM school_rank WHERE province=? AND track=? '
            'AND year IN (?, ?)', (province, track, year, REF_YEAR)):
        ids.add(int(sid))
    if not reload:
        done = {int(r[0]) for r in conn.execute(
            'SELECT DISTINCT school_id FROM special_group '
            'WHERE province=? AND track=? AND year=?', (province, track, year))}
        ids -= done
    todo = sorted(ids)
    if limit:
        todo = todo[:int(limit)]
    if verbose:
        print('[special] %s %s %d 年：待抓 %d 所（%d 线程）'
              % (province, config.TRACK_CN.get(track, track), year, len(todo), workers),
              flush=True)
    if not todo:
        return {'schools': 0, 'groups': 0, 'majors': 0, 'failed': 0, 'empty': 0}

    ok = groups_n = majors_n = failed = empty = 0
    t0 = time.time()
    buf = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_school, sid, province, track, year): sid for sid in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            sid = futs[fut]
            try:
                groups, majors = fut.result()
            except Exception as e:
                failed += 1
                if verbose and failed <= 5:
                    print('   ! %s 失败: %s' % (sid, str(e)[:110]))
                continue
            if not groups:
                empty += 1
                continue
            buf.append((sid, groups, majors))
            if len(buf) >= 60:
                for sid2, g2, m2 in buf:
                    a, b = _write(conn, sid2, province, track, year, g2, m2)
                    groups_n += a
                    majors_n += b
                    ok += 1
                conn.commit()
                buf = []
            if verbose and i % 100 == 0:
                sp = time.time() - t0
                print('   %d/%d  组 %d 专业 %d 失败 %d 空 %d  %.0fs  限速 %.2fs'
                      % (i, len(todo), groups_n, majors_n, failed, empty, sp,
                         _PACE['min']), flush=True)
    for sid2, g2, m2 in buf:
        a, b = _write(conn, sid2, province, track, year, g2, m2)
        groups_n += a
        majors_n += b
        ok += 1
    conn.commit()
    store.set_meta(conn, 'special_ingested_%s_%s_%d' % (province, track, year),
                   time.strftime('%Y-%m-%d %H:%M:%S'))
    if verbose:
        print('[special] 完成：%d 校 / %d 组 / %d 专业行，失败 %d，无数据 %d，'
              '用时 %.0fs' % (ok, groups_n, majors_n, failed, empty, time.time() - t0),
              flush=True)
    return {'schools': ok, 'groups': groups_n, 'majors': majors_n,
            'failed': failed, 'empty': empty}


def status(conn, province=None):
    """入库进度概览。"""
    sql = ('SELECT province, track, year, COUNT(*) n, COUNT(DISTINCT school_id) schools, '
           'SUM(CASE WHEN min_rank IS NOT NULL THEN 1 ELSE 0 END) with_rank, '
           'SUM(CASE WHEN tuition IS NOT NULL THEN 1 ELSE 0 END) with_tuition '
           'FROM special_group')
    args = ()
    if province:
        sql += ' WHERE province=?'
        args = (province,)
    sql += ' GROUP BY province, track, year ORDER BY province, track, year'
    out = []
    for r in conn.execute(sql, args):
        out.append(dict(r))
    return out
