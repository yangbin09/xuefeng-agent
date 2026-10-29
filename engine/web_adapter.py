# -*- coding: utf-8 -*-
"""服务端适配层：把位次引擎的输出转成 index.html 已认识的旧结构。

原则：
- 只做「翻译」，不改前端契约，index.html 一行不用动就能用上新引擎。
- 任何异常都返回 None，让 server.py 回落到原有逻辑，绝不把网页打挂。
"""
import os
import sqlite3

from . import audit, config, major_dirs, recommend as rec_mod, special, store, subject_rules

TRACK_ALIASES = {
    'physics': 'physics', '物理': 'physics', '物': 'physics',
    'history': 'history', '历史': 'history', '史': 'history',
}


def guess_track(subject_text):
    """从用户原话里猜科类。返回 physics / history / None(无法判断)。"""
    if not subject_text:
        return None
    s = str(subject_text)
    has_phy = ('物理' in s) or ('物化' in s) or ('物' in s and '历史' not in s)
    has_his = ('历史' in s) or ('史政' in s)
    if has_phy and not has_his:
        return 'physics'
    if has_his and not has_phy:
        return 'history'
    return None


def _adapt_items(items, province, track, range_mode=False):
    out = []
    for it in items:
        out.append({
            'schoolId': it.get('school_id'),
            'school': it['school'],
            'major': it.get('major') or '全校最低分',
            'score': it['score'],
            'needScore': it.get('need_score') or it['score'],
            'rank': it['rank'],
            'year': it['year'],
            'source': 'DB',
            'tag': audit.tag(province, it['year'], track, it.get('source')),
            'trend': it.get('trend', ''),
            'histZones': it.get('hist_zones', []),
            'zoneText': it.get('zone_text', ''),
            'zoneYears': it.get('zone_years', 0),
            'volatile': bool(it.get('volatile')),
            'bigSmall': bool(it.get('big_small')),
            'nature': it.get('nature', ''),
            'natureGroup': it.get('nature_group', ''),
            'expensive': bool(it.get('expensive')),
            'grpTotal': (it.get('groups') or {}).get('total', 0),
            'grpOk': (it.get('groups') or {}).get('ok', 0),
            'grpBlocked': (it.get('groups') or {}).get('blocked', 0),
            'minTuition': (it.get('groups') or {}).get('minTuition'),
            'maxTuition': (it.get('groups') or {}).get('maxTuition'),
            'planTotal': (it.get('groups') or {}).get('planTotal', 0),
            'grpYear': (it.get('groups') or {}).get('year'),
            'gapText': it.get('gap_text', '') if range_mode else '',
            'prelim': bool(it.get('prelim')),
            'prelimKind': it.get('prelim_kind', ''),
            'f985': it.get('f985'),
            'f211': it.get('f211'),
            'city': it.get('city', ''),
            'schoolProvince': it.get('school_province', ''),
            'history': it.get('history', []),
        })
    return out


def recommend_for_web(province, keyword=None, rank=0, score=0,
                      subject=None, track=None, limit=40,
                      rank_lo=0, rank_hi=0, score_lo=0, score_hi=0,
                      first=None, resel=None, cities=None,
                      care=None, avoid=None):
    """给 server.py 的 /recommend 用。返回前端结构 dict，或 None 表示请走旧逻辑。

    支持单值（rank/score）与区间（rank_lo+rank_hi / score_lo+score_hi）两种入参。
    """
    if province not in config.PROVINCE_IDS:
        return None

    # 首选科目：first > subject > 原话猜测
    primary = subject_rules.parse_primary(first) or subject_rules.parse_primary(subject)
    track = (TRACK_ALIASES.get((track or '').strip())
             or primary
             or guess_track(subject)
             or 'physics')
    resel_codes = subject_rules.parse_resel(resel)

    rank, score = _num(rank), _num(score)
    rank_lo, rank_hi = _num(rank_lo), _num(rank_hi)
    score_lo, score_hi = _num(score_lo), _num(score_hi)

    if not any((rank, score, rank_lo, rank_hi, score_lo, score_hi)):
        return None

    db = config.db_path()
    if not os.path.exists(db):
        return None

    conn = store.connect(db)
    try:
        store.init_db(conn)
        if not conn.execute('SELECT 1 FROM school_rank LIMIT 1').fetchone():
            return None
        res = rec_mod.recommend(
            conn, province, track,
            score=score or None, rank=rank or None,
            score_lo=score_lo or None, score_hi=score_hi or None,
            rank_lo=rank_lo or None, rank_hi=rank_hi or None,
            limit=limit,
            city_list=cities or None,
            subject_primary=primary,
            subject_resel=resel_codes)
    except (ValueError, sqlite3.Error):
        return None
    finally:
        conn.close()

    rm = bool(res['range_mode'])
    dirs = []
    dir_note = ''
    try:
        dirs = major_dirs.pick(primary, resel_codes, care, avoid, limit=6)
        dir_note = major_dirs.NOTE
    except Exception as _e:  # 方向库异常绝不能拖垮推荐
        print('[ADAPTER] 方向库失败: %s' % _e)
    payload = {
        'province': res['province'],
        'rank': res['rank'],
        'rankLo': res['rank_lo'],
        'rankHi': res['rank_hi'],
        'score': res['score'] or 0,
        'scoreLo': res['score_lo'] or 0,
        'scoreHi': res['score_hi'] or 0,
        'rangeMode': rm,
        'rangeWidth': res['range_width'],
        'chong': _adapt_items(res['chong'], province, track, rm),
        'wen': _adapt_items(res['wen'], province, track, rm),
        'bao': _adapt_items(res['bao'], province, track, rm),
        'user_data': [],
        'source': 'engine',
        'track': res['track_cn'],
        'year': res['year'],
        'subject': res.get('subject'),
        'special': res.get('special'),
        'directions': dirs,
        'directionNote': dir_note,
        'engine_meta': res['meta'],
        'counts': res['counts'],
    }
    return payload


def _num(v):
    try:
        n = int(v or 0)
    except (TypeError, ValueError):
        return 0
    return n


def rank_range(province, track, score_lo=0, score_hi=0, year=None):
    """给前端表单做「分数区间 -> 位次区间」实时换算。"""
    if province not in config.PROVINCE_IDS:
        return {'ok': False, 'error': f'未收录的省份: {province}'}
    track = TRACK_ALIASES.get((track or '').strip()) or 'physics'
    lo, hi = _num(score_lo), _num(score_hi)
    if lo > hi:
        lo, hi = hi, lo
    if lo <= 0 or hi <= 0:
        return {'ok': False, 'error': '需要两个分数'}
    db = config.db_path()
    if not os.path.exists(db):
        return {'ok': False, 'error': '数据库不存在'}
    conn = store.connect(db)
    try:
        store.init_db(conn)
        y = rec_mod.resolve_year(conn, province, track, year)
        conv = convert_range(conn, province, y, track, lo, hi)
        if not conv:
            return {'ok': False, 'error': '一分一段表里没有这个分数区间', 'year': y}
        width = hi - lo
        conv.update({
            'ok': True,
            'track_cn': config.TRACK_CN.get(track, track),
            'width': width,
            'too_wide': width > config.RANGE_MAX_WIDTH,
            'too_narrow': width < config.RANGE_MIN_WIDTH,
            'max_width': config.RANGE_MAX_WIDTH,
            'min_width': config.RANGE_MIN_WIDTH,
        })
        return conv
    except sqlite3.Error as e:
        return {'ok': False, 'error': str(e)}
    finally:
        conn.close()


def convert_range(conn, province, year, track, lo, hi):
    from . import convert
    try:
        return convert.score_range_to_rank(conn, province, year, track, lo, hi)
    except convert.NoRankTable:
        return None


def groups_for_web(province, school_id, track='physics', first=None, resel=None,
                   score_lo=0, score_hi=0, rank_lo=0, rank_hi=0):
    """给前端「展开行」用：一所学校的专业组列表（含可报性 / 冲稳保 / 学费 / 组内专业）。"""
    if province not in config.PROVINCE_IDS:
        return {'ok': False, 'error': '未收录的省份: %s' % province}
    try:
        sid = int(school_id)
    except (TypeError, ValueError):
        return {'ok': False, 'error': 'school_id 不合法'}
    db = config.db_path()
    if not os.path.exists(db):
        return {'ok': False, 'error': '数据库不存在'}
    primary = subject_rules.parse_primary(first)
    resel_codes = subject_rules.parse_resel(resel)
    tk = TRACK_ALIASES.get((track or '').strip()) or primary or 'physics'
    conn = store.connect(db)
    try:
        store.init_db(conn)
        if not conn.execute('SELECT 1 FROM special_group LIMIT 1').fetchone():
            return {'ok': True, 'groups': [], 'empty': True,
                    'error': '还没有分专业数据，先跑 python -m engine ingest-special --all'}
        year = rec_mod.resolve_year(conn, province, tk)
        rng = rec_mod.resolve_input_range(
            conn, province, tk, year,
            score_lo=_num(score_lo) or None, score_hi=_num(score_hi) or None,
            rank_lo=_num(rank_lo) or None, rank_hi=_num(rank_hi) or None)
        range_mode = rng['mode'] in ('rank_range', 'score_range')
        r_mid = (rng['rank_lo'] + rng['rank_hi']) // 2
        groups = special.school_groups(
            conn, sid, province, tk,
            student_primary=primary, student_resel=resel_codes,
            range_mode=range_mode, r_lo=rng['rank_lo'], r_hi=rng['rank_hi'],
            bands=config.BANDS, r_mid=r_mid,
            score_lo=rng['score_lo'], score_hi=rng['score_hi'])
        return {
            'ok': True,
            'province': province,
            'schoolId': sid,
            'track': config.TRACK_CN.get(tk, tk),
            'year': year,
            'groups': groups,
            'student': {
                'scoreLo': rng['score_lo'], 'scoreHi': rng['score_hi'],
                'rankLo': rng['rank_lo'], 'rankHi': rng['rank_hi'],
                'rangeMode': range_mode,
            },
            'subject': subject_rules.analyze(primary, resel_codes),
        }
    except ValueError as e:
        return {'ok': False, 'error': str(e)}
    except sqlite3.Error as e:
        return {'ok': False, 'error': 'DB: %s' % e}
    finally:
        conn.close()


def health():
    """返回引擎可用性摘要，供 /ping 或排障使用。"""
    db = config.db_path()
    info = {'db': db, 'exists': os.path.exists(db)}
    if not info['exists']:
        return info
    try:
        conn = store.connect(db)
        store.init_db(conn)
        info['counts'] = store.counts(conn)
        rows = conn.execute(
            'SELECT province, track, MAX(year) y, COUNT(*) n FROM school_rank '
            'GROUP BY province, track').fetchall()
        info['coverage'] = [dict(r) for r in rows]
        conn.close()
    except sqlite3.Error as e:
        info['error'] = str(e)
    return info
