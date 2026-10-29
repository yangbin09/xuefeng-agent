# -*- coding: utf-8 -*-
"""位次匹配引擎：冲 / 稳 / 保（支持单值与区间两种口径）。

判定口径全部基于「位次」，不基于分数：
    倍率 = 该校最低录取位次 / 考生位次
    倍率 < 1  →  学校录取线更靠前（更难）  → 冲
    倍率 ≈ 1  →  位次相当                  → 稳
    倍率 > 1  →  学校录取线更靠后（更容易） → 保

区间口径（预演填报，考生还没有确定分数）：
    考生位次是一个区间 [r_lo, r_hi]，r_lo 更靠前（考得更好）
    校线位次 mr <  r_lo        → 冲：比你的最好情况还要好
    r_lo <= mr <= r_hi         → 稳：落在估分区间内，看发挥
    r_hi <  mr                 → 保：比你的最差情况还容易

【关键口径】分数 -> 位次 必须用**同一年**的一分一段表。
因为要比较的 `school_rank.min_rank` 是参考年的录取位次，混年换算 = 跨年混算。
"""
from . import config, convert, subject_rules


def _to_int(v):
    try:
        n = int(v or 0)
    except (TypeError, ValueError):
        return 0
    return n


def resolve_year(conn, province, track, year=None):
    """确定参考年份：显式指定 > 库内最新 > 配置默认。"""
    if year:
        return int(year)
    latest = conn.execute(
        'SELECT MAX(year) y FROM school_rank WHERE province=? AND track=?',
        (province, track),
    ).fetchone()
    if latest and latest['y']:
        return int(latest['y'])
    return config.REFERENCE_YEAR


def _load_history(conn, province, track):
    """school_id -> {year: (min_score, min_rank)}"""
    hist = {}
    for r in conn.execute(
            'SELECT school_id, year, min_score, min_rank FROM school_rank '
            'WHERE province=? AND track=?', (province, track)):
        hist.setdefault(r['school_id'], {})[r['year']] = (r['min_score'], r['min_rank'])
    return hist


def _trend(hist_years, years):
    """根据多年位次判断趋势。位次数字变大 = 录取线后移 = 更好考。"""
    pts = [(y, hist_years[y][1]) for y in sorted(years) if y in hist_years]
    if len(pts) < 2:
        return {'label': '无历史对比', 'pts': pts}
    seq = [p[1] for p in pts]
    ups = all(seq[i] < seq[i + 1] for i in range(len(seq) - 1))
    downs = all(seq[i] > seq[i + 1] for i in range(len(seq) - 1))
    if ups:
        label = '位次逐年后移（更好考）'
    elif downs:
        label = '位次逐年前移（更难考）'
    else:
        label = '位次波动'
    return {'label': label, 'pts': pts}


def _score_of_rank(conn, province, year, track, r):
    if not r:
        return None
    res = convert.rank_to_score(conn, province, year, track, int(r))
    return res['score'] if res else None


def resolve_input_range(conn, province, track, year,
                        score=None, rank=None, score_lo=None, score_hi=None,
                        rank_lo=None, rank_hi=None):
    """把各种入参统一成区间。返回 dict。

    mode: 'rank' / 'score' / 'rank_range' / 'score_range'
    """
    score_lo, score_hi = _to_int(score_lo), _to_int(score_hi)
    rank_lo, rank_hi = _to_int(rank_lo), _to_int(rank_hi)
    score, rank = _to_int(score), _to_int(rank)

    if score_lo and score_hi and score_lo > score_hi:
        score_lo, score_hi = score_hi, score_lo
    if rank_lo and rank_hi and rank_lo > rank_hi:
        rank_lo, rank_hi = rank_hi, rank_lo

    # 1) 位次区间（最可靠，直接用）
    if rank_lo > 0 and rank_hi > 0:
        if not score_lo or not score_hi:
            score_hi = _score_of_rank(conn, province, year, track, rank_lo) or score_hi
            score_lo = _score_of_rank(conn, province, year, track, rank_hi) or score_lo
        return {'mode': 'rank_range', 'rank_lo': rank_lo, 'rank_hi': rank_hi,
                'score_lo': score_lo or None, 'score_hi': score_hi or None}

    # 2) 分数区间 -> 同年换算成位次区间
    if score_lo > 0 and score_hi > 0:
        conv = convert.score_range_to_rank(conn, province, year, track, score_lo, score_hi)
        if not conv:
            raise ValueError(
                f'{province} {year} 年 {config.TRACK_CN[track]} 的一分一段表里没有 '
                f'{score_lo}~{score_hi} 分')
        return {'mode': 'score_range', 'rank_lo': conv['rank_lo'], 'rank_hi': conv['rank_hi'],
                'score_lo': score_lo, 'score_hi': score_hi}

    # 3) 单个位次
    if rank > 0:
        lo = _score_of_rank(conn, province, year, track, rank)
        return {'mode': 'rank', 'rank_lo': rank, 'rank_hi': rank,
                'score_lo': lo, 'score_hi': lo}

    # 4) 单个分数
    if score > 0:
        info = convert.score_to_rank_safe(conn, province, year, track, score)
        if not info:
            raise ValueError(
                f'{province} {year} 年 {config.TRACK_CN[track]} 的一分一段表里没有 {score} 分')
        return {'mode': 'score', 'rank_lo': info['rank'], 'rank_hi': info['rank'],
                'score_lo': score, 'score_hi': score}

    raise ValueError('必须提供 score / rank / score_lo+score_hi / rank_lo+rank_hi 之一')


_POLICE_BELONG = ('公安部', '司法部', '国家安全部')

_ZONE_CN = {'chong': '冲', 'wen': '稳', 'bao': '保'}


def _zone_of(mr, range_mode, r_lo, r_hi, bands, r):
    """把任意一年的录取位次翻译成冲/稳/保档位。

    用途：同一个考生区间，把该校 2024/2025/2026 三年的录取位次各归一次档，
    就能看出「这所学校近几年到底稳不稳」——这是单年快照看不出来的。
    """
    if not mr or mr <= 0:
        return None
    mr = int(mr)
    if range_mode:
        if mr < r_lo:
            return 'chong'
        if mr <= r_hi:
            return 'wen'
        return 'bao'
    if not r:
        return None
    ratio = mr / float(r)
    for key, b_lo, b_hi in bands:
        if b_lo <= ratio < b_hi:
            return key
    return None


def _nature_group(nature):
    """把 school.nature 归成三类：公办 / 民办 / 合作办学。

    为什么要归一：光看校名看不出学费。中外合作办学普遍 4~9 万/年，
    民办 1.5~3 万/年，公办 4 千~7 千/年，对普通家庭这是决策级信息。
    """
    n = nature or ''
    if '合作' in n or '中外' in n:
        return '合作办学'
    if n in ('民办', '独立学院'):
        return '民办'
    if n == '公办':
        return '公办'
    return ''


def _prelim_kind(row):
    """提前批院校判定：军校 / 公安院校。

    这类学校走提前批，要政审 + 体检 + 面试，录取线不能和本科批直接比，
    所以必须在界面上打标，不能混在普通院校里让家长误读。
    返回 '' / '军' / '警'。
    """
    try:
        t = row['type'] or ''
        name = row['name'] or ''
        belong = row['school_belong'] or ''
    except (KeyError, IndexError):
        return ''
    if t == '军事类' or ('解放军' in name) or name.startswith('武警'):
        return '军'
    for b in _POLICE_BELONG:
        if b in belong:
            return '警'
    if ('警察学院' in name) or ('警官学院' in name) or ('公安大学' in name):
        return '警'
    return ''


def recommend(conn, province, track, score=None, rank=None, year=None,
              limit=None, name_like=None, only_985=False, only_211=False,
              dual_class=None, city=None, level=None, bands=None,
              with_history=True, score_lo=None, score_hi=None,
              rank_lo=None, rank_hi=None, city_list=None,
              subject_primary=None, subject_resel=None):
    """按位次给出冲稳保（支持区间）。返回 dict，所有数字都能追溯到库里的行。"""
    limit = limit or config.DEFAULT_LIMIT
    bands = bands or config.BANDS

    if province not in config.PROVINCE_IDS:
        raise ValueError(f'未收录的招生省份: {province}（当前支持 {list(config.PROVINCE_IDS)}）')
    track = track or 'physics'
    year = resolve_year(conn, province, track, year)

    rng = resolve_input_range(conn, province, track, year,
                              score=score, rank=rank,
                              score_lo=score_lo, score_hi=score_hi,
                              rank_lo=rank_lo, rank_hi=rank_hi)
    r_lo, r_hi = rng['rank_lo'], rng['rank_hi']
    if r_lo <= 0 or r_hi <= 0:
        raise ValueError('位次必须大于 0')
    if r_lo > r_hi:
        r_lo, r_hi = r_hi, r_lo
    r = (r_lo + r_hi) // 2
    range_mode = rng['mode'] in ('rank_range', 'score_range')

    # ---- 候选集合 ----
    sql = ('SELECT sr.school_id, sr.min_score, sr.min_rank, sr.year, '
           '       s.name, s.city, s.f985, s.f211, s.dual_class, s.level, s.type, '
           '       s.belong AS school_belong, '
           '       s.province AS school_province, '
           '       s.nature AS school_nature '
           'FROM school_rank sr JOIN school s ON s.id = sr.school_id '
           'WHERE sr.province=? AND sr.year=? AND sr.track=?')
    params = [province, year, track]
    if only_985:
        sql += ' AND s.f985=1'
    if only_211:
        sql += ' AND s.f211=1'
    if dual_class:
        sql += ' AND s.dual_class LIKE ?'
        params.append(f'%{dual_class}%')
    if city:
        sql += ' AND s.city LIKE ?'
        params.append(f'%{city}%')
    if level:
        sql += ' AND s.level=?'
        params.append(level)
    if name_like:
        sql += ' AND s.name LIKE ?'
        params.append(f'%{name_like}%')

    rows = conn.execute(sql, params).fetchall()
    hist = _load_history(conn, province, track) if with_history else {}

    cities = [c for c in (city_list or []) if c]
    if cities:
        rows = [x for x in rows if any(c in (x['city'] or '') for c in cities)]

    # ---- 窗口 ----
    if range_mode:
        lo = r_lo * config.RANGE_CHONG_RATIO
        hi = r_hi * config.RANGE_BAO_RATIO
    else:
        lo = min(b[1] for b in bands) * r
        hi = max(b[2] for b in bands) * r

    score_lo, score_hi = rng['score_lo'], rng['score_hi']
    score_mid = None
    if score_lo and score_hi:
        score_mid = int((score_lo + score_hi) / 2)

    buckets = {'chong': [], 'wen': [], 'bao': []}
    for row in rows:
        mr = row['min_rank']
        if not mr or mr < lo or mr > hi:
            continue
        ratio = mr / r
        if range_mode:
            if mr < r_lo:
                which = 'chong'
            elif mr <= r_hi:
                which = 'wen'
            else:
                which = 'bao'
        else:
            which = None
            for key, b_lo, b_hi in bands:
                if b_lo <= ratio < b_hi:
                    which = key
                    break
            if which is None:
                continue  # 落在分档空隙
        item = {
            'school_id': row['school_id'],
            'school': row['name'],
            'major': '',
            'score': row['min_score'],
            'need_score': row['min_score'],
            'rank': mr,
            'year': row['year'],
            'track': track,
            'track_cn': config.TRACK_CN[track],
            'province': province,
            'ratio': round(ratio, 4),
            'gap': mr - r,
            'zone': which,
            'f985': bool(row['f985']),
            'f211': bool(row['f211']),
            'dual_class': row['dual_class'] or '',
            'city': row['city'] or '',
            'school_province': row['school_province'] or '',
            'level': row['level'] or '',
            'type': row['type'] or '',
            'source': config.SOURCE_LIVE,
            'gap_text': '',
            'nature': row['school_nature'] or '',
            'nature_group': _nature_group(row['school_nature']),
            'expensive': _nature_group(row['school_nature']) in ('合作办学', '民办'),
        }
        # 提前批（军校/公安院校）：录取线不能和本科批直接比，必须打标
        pk = _prelim_kind(row)
        item['prelim'] = bool(pk)
        item['prelim_kind'] = pk
        # 区间模式：把「校线位次」翻译成人话——需考到多少分、差几分
        need = row['min_score']
        if range_mode and need and score_lo and score_hi:
            if which == 'chong':
                d = need - score_hi
                item['gap_text'] = f'差 {d} 分' if d > 0 else '临界'
            elif which == 'wen':
                item['gap_text'] = '贴底线' if need <= score_lo else '区间内'
            else:
                item['gap_text'] = f'富余 {score_lo - need} 分'
        if with_history:
            hy = hist.get(row['school_id'], {})
            t = _trend(hy, config.HISTORY_YEARS)
            item['trend'] = t['label']
            item['history'] = [{'year': y, 'score': hy[y][0], 'rank': hy[y][1]}
                               for y in sorted(config.HISTORY_YEARS) if y in hy]
            # 近三年分档：把往年的录取位次也按「考生同一区间」归一次档
            zones = []
            for y in sorted(config.HISTORY_YEARS):
                if y not in hy:
                    continue
                z = _zone_of(hy[y][1], range_mode, r_lo, r_hi, bands, r)
                if z:
                    zones.append({'year': y, 'zone': z})
            cnt = {}
            for z in zones:
                cnt[z['zone']] = cnt.get(z['zone'], 0) + 1
            item['hist_zones'] = zones
            item['zone_counts'] = cnt
            item['zone_years'] = len(zones)
            item['zone_text'] = ' '.join(
                '%s%d' % (_ZONE_CN[k], cnt[k])
                for k in ('chong', 'wen', 'bao') if cnt.get(k))
            item['volatile'] = len(cnt) >= 2
            # 同时出现过「冲」和「保」= 典型的忽高忽低（大小年）
            item['big_small'] = bool(cnt.get('chong') and cnt.get('bao'))
        buckets[which].append(item)

    # ---- 专业组：选科真筛选 + 组数摘要（P6）----
    # 只有「再选 2 门都确定了」才做真筛选；没选满就只展示、不剔除（最宽口径）。
    special_meta = None
    resel_codes = list(subject_resel or [])
    strict_subject = len(resel_codes) == 2
    try:
        from . import special as special_mod
        all_ids = [it['school_id'] for k in ('chong', 'wen', 'bao') for it in buckets[k]]
        summ = special_mod.summarize(conn, all_ids, province, track,
                                     subject_primary, resel_codes)
        if summ:
            dropped = 0
            for k in ('chong', 'wen', 'bao'):
                kept = []
                for it in buckets[k]:
                    s = summ.get(it['school_id'])
                    if s:
                        it['groups'] = s
                        if strict_subject and s['total'] and s['ok'] == 0:
                            dropped += 1
                            continue
                    kept.append(it)
                buckets[k] = kept
            any_year = next(iter(summ.values()))['year']
            special_meta = {
                'year': any_year,
                'schools': len(summ),
                'dropped': dropped,
                'strict': strict_subject,
                'note': (
                    '专业组数据来自掌上高考 %d 年招生计划与分专业录取线；'
                    '已把组线位次换算成 %d 年等效位次再比较。'
                    % (any_year, year)),
            }
    except Exception as _e:  # 专业组失败绝不能拖垮推荐
        print('[RECOMMEND] 专业组失败: %s' % _e)
        special_meta = None

    # ---- 排序 ----
    buckets['chong'].sort(key=lambda x: x['rank'])           # 冲：由难到易
    if score_mid:
        buckets['wen'].sort(key=lambda x: abs((x['need_score'] or 0) - score_mid))
    else:
        buckets['wen'].sort(key=lambda x: abs(x['rank'] - r))
    buckets['bao'].sort(key=lambda x: x['rank'])             # 保：由近到远

    subject_info = None
    if subject_primary or subject_resel:
        try:
            subject_info = subject_rules.analyze(subject_primary, subject_resel)
        except Exception:  # 选科分析失败绝不能拖垮推荐
            subject_info = None

    out = {
        'province': province,
        'track': track,
        'track_cn': config.TRACK_CN[track],
        'year': year,
        'score': score_mid,
        'rank': r,
        'rank_lo': r_lo,
        'rank_hi': r_hi,
        'score_lo': score_lo,
        'score_hi': score_hi,
        'score_mid': score_mid,
        'range_mode': range_mode,
        'range_width': (score_hi - score_lo) if (score_lo and score_hi) else 0,
        'input_mode': rng['mode'],
        'subject': subject_info,
        'special': special_meta,
        'counts': {k: len(v) for k, v in buckets.items()},
        'meta': {
            'rank_basis': f'{year} 年 {province} {config.TRACK_CN[track]} 一分一段表（按位次分档）',
            'score_basis': f'{year} 年 {province} 各校最低录取分',
            'band_rule': (
                f'冲：校线位次 < {r_lo}；稳：{r_lo} ~ {r_hi}；'
                f'保：> {r_hi}（考生位次区间 {r_lo}~{r_hi}，中位 {r}）'
                if range_mode else
                '冲 0.80~0.95 / 稳 0.95~1.10 / 保 1.10~1.45（倍率 = 校线位次 ÷ 考生位次）'
            ),
            'zone_basis': (
                '「近三年」= 把该校 2024/2025/2026 三年的录取位次，分别按你同一个区间'
                '归到冲/稳/保再数次数。不给百分比（三年样本撑不住），只给「几年落在哪档」；'
                '三年里既出现过冲又出现过保 = 大小年，慎当保底。'
            ),
        },
    }
    for key in ('chong', 'wen', 'bao'):
        out[key] = buckets[key][:limit]
    return out


def evidence_from(result):
    """把结果里所有可信数字收集成证据包，供 audit 校验 LLM 输出。"""
    ev = {'scores': set(), 'ranks': set(), 'schools': set(), 'years': set()}
    if result.get('rank'):
        ev['ranks'].add(int(result['rank']))
        ev['candidate_rank'] = int(result['rank'])
    for key in ('rank_lo', 'rank_hi'):
        if result.get(key):
            ev['ranks'].add(int(result[key]))
    if result.get('score'):
        ev['scores'].add(int(result['score']))
    for key in ('score_lo', 'score_hi'):
        if result.get(key):
            ev['scores'].add(int(result[key]))
    if result.get('year'):
        ev['years'].add(int(result['year']))
    for key in ('chong', 'wen', 'bao'):
        for it in result.get(key) or []:
            if it.get('score'):
                ev['scores'].add(int(it['score']))
            if it.get('need_score'):
                ev['scores'].add(int(it['need_score']))
            ev['ranks'].add(int(it['rank']))
            ev['years'].add(int(it['year']))
            ev['schools'].add(it['school'])
    return ev
