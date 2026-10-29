# -*- coding: utf-8 -*-
"""专业组查询层：选科要求解析、可报性判断、组级冲稳保、学费/计划。

数据来自 `special_group` / `special_major`（由 `ingest_special.py` 抓取合并）。

【口径】
- 组线分数/位次是 `special_group.year`（目前 2025）的真实数据；
- 与考生（2026 口径）比较时用 `ref_rank`——入库时已换算成 2026 等效位次；
- 「需考到」展示为 **2026 等效分数**（ref_rank -> 2026 一分一段），而不是 2025 原始分。
  这样和界面上的「你的区间 585–605 分」是同一年口径，不会出现「2025 的 600 分 ≠ 2026 的 600 分」的错觉。
- 换算不了 ref_rank 的组，只展示分数/学费，不参与冲稳保分档。
"""
from . import config, convert

SUBJ_CN = {'chem': '化学', 'bio': '生物', 'pol': '政治', 'geo': '地理'}
SUBJ_ALIAS = {
    '化学': 'chem', '生物': 'bio', '生物学': 'bio',
    '思想政治': 'pol', '政治': 'pol', '地理': 'geo',
}
ZONE_CN = config.BAND_CN


def _int(v):
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def parse_require(sg_info):
    """解析选科要求原文。

    返回 {'primary': 'physics'|'history'|None,
          'groups': [[code,...], ...]   # 每个子列表内「必须全选」，子列表之间「满足其一即可」
          'unlimited': bool}
    """
    s = (sg_info or '').replace(' ', '').replace('　', '')
    primary = None
    if '首选物理' in s:
        primary = 'physics'
    elif '首选历史' in s:
        primary = 'history'
    if not s:
        return {'primary': primary, 'groups': [], 'unlimited': True}

    tail = s.split('再选', 1)[1] if '再选' in s else ''
    if not tail:
        return {'primary': primary, 'groups': [], 'unlimited': True}
    if '不限' in tail or '不提' in tail or tail.startswith('无'):
        return {'primary': primary, 'groups': [], 'unlimited': True}

    # 去掉括号里的说明（如 (2科必选)），避免把「2科」当科目
    import re
    tail = re.sub(r'[（(][^）)]*[）)]', '', tail)
    groups = []
    for alt in tail.split('或'):
        codes = []
        for part in re.split(r'[、,，和及]', alt):
            for cn, code in SUBJ_ALIAS.items():
                if cn in part and code not in codes:
                    codes.append(code)
        if codes:
            groups.append(codes)
    return {'primary': primary, 'groups': groups, 'unlimited': not groups}


def reportable(req, student_primary, student_resel):
    """这个组能不能报。

    student_resel 为空（还没定）时按「最宽口径」：只要首选对得上就算可报，并标记 undecided。
    """
    if req['primary'] and student_primary and req['primary'] != student_primary:
        return False
    if req['unlimited'] or not req['groups']:
        return True
    have = set(student_resel or [])
    if not have:
        return True  # 还没定，最宽口径
    return any(set(g) <= have for g in req['groups'])


def require_text(sg_info, req):
    """把要求转成人话：物+化+生 / 物+化 / 物+不限 / 史+政。"""
    p = '物' if req['primary'] == 'physics' else ('史' if req['primary'] == 'history' else '')
    if req['unlimited'] or not req['groups']:
        resel = '不限'
    else:
        parts = []
        for g in req['groups']:
            parts.append('+'.join(SUBJ_CN.get(c, c)[0] if SUBJ_CN.get(c) else c for c in g))
        resel = '或'.join(parts)
    return (p + '+' + resel) if p else resel


def _zone(ref_rank, range_mode, r_lo, r_hi, bands, r_mid):
    if not ref_rank:
        return None
    if range_mode:
        if ref_rank < r_lo:
            return 'chong'
        if ref_rank <= r_hi:
            return 'wen'
        return 'bao'
    if not r_mid:
        return None
    ratio = ref_rank / float(r_mid)
    for key, lo, hi in bands:
        if lo <= ratio < hi:
            return key
    return None


def _need_score(conn, province, track, ref_rank):
    if not ref_rank:
        return None
    s = convert.rank_to_score(conn, province, config.REFERENCE_YEAR, track, int(ref_rank))
    return s['score'] if s else None


def _gap_text(zone, need, score_lo, score_hi):
    if zone == 'chong':
        if need and score_hi:
            d = need - score_hi
            return '差 %d 分' % d if d > 0 else '临界'
        return '高于区间'
    if zone == 'wen':
        if need and score_lo and need <= score_lo:
            return '贴底线'
        return '区间内'
    if zone == 'bao':
        if need and score_lo:
            return '富余 %d 分' % (score_lo - need)
        return '低于区间'
    return '—'


def school_groups(conn, school_id, province, track, student_primary=None,
                  student_resel=None, range_mode=True, r_lo=0, r_hi=0,
                  bands=None, r_mid=0, score_lo=None, score_hi=None,
                  year=None, with_majors=True, max_majors=8):
    """某校的专业组列表（含可报性、冲稳保、学费、计划、组内专业）。"""
    y = int(year or 0)
    if not y:
        row = conn.execute(
            'SELECT MAX(year) y FROM special_group WHERE province=? AND track=?',
            (province, track)).fetchone()
        y = int(row['y']) if row and row['y'] else config.SPECIAL_YEAR
    bands = bands or config.BANDS
    rows = conn.execute(
        'SELECT * FROM special_group WHERE school_id=? AND province=? AND track=? AND year=? '
        'ORDER BY ref_rank IS NULL, ref_rank', (school_id, province, track, y)).fetchall()
    if not rows:
        return []
    out = []
    for r in rows:
        req = parse_require(r['sg_info'])
        ok = reportable(req, student_primary, student_resel)
        need = _need_score(conn, province, track, r['ref_rank'])
        zone = _zone(r['ref_rank'], range_mode, r_lo, r_hi, bands, r_mid)
        item = {
            'grp': r['grp'],
            'name': r['sg_name'] or '',
            'info': r['sg_info'] or '',
            'reqText': require_text(r['sg_info'], req),
            'reqPrimary': req['primary'] or '',
            'reqResel': [c for g in req['groups'] for c in g],
            'requireAll': [g for g in req['groups']],
            'unlimited': req['unlimited'],
            'ok': bool(ok),
            'batch': r['batch'] or '',
            'planNum': r['plan_num'],
            'tuition': r['tuition'],
            'minScore': r['min_score'],
            'minRank': r['min_rank'],
            'refRank': r['ref_rank'],
            'needScore': need,
            'zone': zone or '',
            'zoneCn': ZONE_CN.get(zone, ''),
            'gapText': _gap_text(zone, need, score_lo, score_hi) if zone else '',
            'nMajor': r['n_major'],
            'year': y,
        }
        if with_majors:
            ms = conn.execute(
                'SELECT spname, src, min_score, plan_num, tuition, length '
                'FROM special_major '
                'WHERE school_id=? AND province=? AND track=? AND year=? AND grp=? '
                'ORDER BY (min_score IS NULL), min_score DESC',
                (school_id, province, track, y, r['grp'])).fetchall()
            seen, majors = set(), []
            for m in ms:
                if m['spname'] in seen:
                    continue
                seen.add(m['spname'])
                majors.append({
                    'spname': m['spname'], 'src': m['src'],
                    'minScore': m['min_score'],
                    'planNum': m['plan_num'],
                    'tuition': m['tuition'],
                    'length': m['length'] or '',
                })
            item['majors'] = majors[:max_majors]
            item['majorMore'] = max(0, len(majors) - max_majors)
        out.append(item)
    # 可报的排前面，再按组线位次从难到易
    out.sort(key=lambda x: (0 if x['ok'] else 1,
                            x['refRank'] if x['refRank'] else 10 ** 9))
    return out


def summarize(conn, school_ids, province, track, student_primary=None,
              student_resel=None):
    """批量给推荐结果补「组数」信息：{school_id: {...}}。

    只查一次，避免逐校 N+1。
    """
    out = {}
    ids = [int(x) for x in school_ids if x]
    if not ids:
        return out
    row = conn.execute(
        'SELECT MAX(year) y FROM special_group WHERE province=? AND track=?',
        (province, track)).fetchone()
    if not row or not row['y']:
        return out
    year = int(row['y'])
    # SQLite 默认最多 999 个参数，分块查，别让宽区间的大候选集把查询撑爆
    rows = []
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        ph = ','.join('?' * len(chunk))
        rows.extend(conn.execute(
            'SELECT school_id, sg_info, plan_num, tuition FROM special_group '
            'WHERE province=? AND track=? AND year=? AND school_id IN (%s)' % ph,
            [province, track, year] + chunk).fetchall())
    for r in rows:
        d = out.setdefault(r['school_id'], {
            'total': 0, 'ok': 0, 'blocked': 0, 'minTuition': None,
            'maxTuition': None, 'planTotal': 0, 'year': year})
        d['total'] += 1
        req = parse_require(r['sg_info'])
        if reportable(req, student_primary, student_resel):
            d['ok'] += 1
        else:
            d['blocked'] += 1
        t = _int(r['tuition'])
        if t:
            d['minTuition'] = t if d['minTuition'] is None else min(d['minTuition'], t)
            d['maxTuition'] = t if d['maxTuition'] is None else max(d['maxTuition'], t)
        d['planTotal'] += (r['plan_num'] or 0)
    return out


def coverage(conn, province=None):
    """整库专业组覆盖概览。"""
    sql = ('SELECT province, track, year, COUNT(*) n, COUNT(DISTINCT school_id) schools, '
           'SUM(CASE WHEN sg_info IS NOT NULL AND sg_info<>"" THEN 1 ELSE 0 END) with_info, '
           'SUM(CASE WHEN tuition IS NOT NULL THEN 1 ELSE 0 END) with_tuition '
           'FROM special_group')
    args = []
    if province:
        sql += ' WHERE province=?'
        args.append(province)
    sql += ' GROUP BY province, track, year ORDER BY province, track, year'
    return [dict(r) for r in conn.execute(sql, args)]
