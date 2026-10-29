# -*- coding: utf-8 -*-
"""分数 <-> 位次 换算。

核心约定：位次（rank）= 一分一段表里「分数 >= S」的累计人数。
        即 rank(S) = cumulative(S)。位次越小越靠前。
"""
from . import config


class NoRankTable(Exception):
    """该省/年/科类没有一分一段表。"""


def available(conn, province=None):
    """列出已收录的 (省, 年, 科类, 行数)。"""
    sql = ('SELECT province, year, track, COUNT(*) n, MIN(score) lo, MAX(score) hi '
           'FROM rank_table')
    params = []
    if province:
        sql += ' WHERE province=?'
        params.append(province)
    sql += ' GROUP BY province, year, track ORDER BY province, year, track'
    return [dict(r) for r in conn.execute(sql, params)]


def latest_year(conn, province, track):
    row = conn.execute(
        'SELECT MAX(year) y FROM rank_table WHERE province=? AND track=?',
        (province, track),
    ).fetchone()
    return row['y'] if row and row['y'] else None


def score_to_rank(conn, province, year, track, score):
    """分数 -> 位次。返回 dict 或 None（该分数不在表内）。"""
    row = conn.execute(
        'SELECT score, cumulative, cnt, source, source_url FROM rank_table '
        'WHERE province=? AND year=? AND track=? AND score=?',
        (province, year, track, int(score)),
    ).fetchone()
    if row:
        return {
            'province': province,
            'year': year,
            'track': track,
            'score': row['score'],
            'rank': row['cumulative'],
            'count': row['cnt'],
            'source': row['source'],
            'source_url': row['source_url'],
        }
    # 分数高于表中最高分（表只从一本线附近开始）→ 用最高分那一档
    top = conn.execute(
        'SELECT score, cumulative, cnt, source, source_url FROM rank_table '
        'WHERE province=? AND year=? AND track=? ORDER BY score DESC LIMIT 1',
        (province, year, track),
    ).fetchone()
    if top and int(score) > top['score']:
        return {
            'province': province, 'year': year, 'track': track,
            'score': int(score), 'rank': top['cumulative'], 'count': None,
            'source': top['source'], 'source_url': top['source_url'],
            'approximate': True, 'note': f'高于表内最高分 {top["score"]}，按最高档位次估算',
        }
    return None


def rank_to_score(conn, province, year, track, rank):
    """位次 -> 分数（该位次对应的最低分）。"""
    row = conn.execute(
        'SELECT score, cumulative, cnt, source, source_url FROM rank_table '
        'WHERE province=? AND year=? AND track=? AND cumulative>=? '
        'ORDER BY cumulative ASC LIMIT 1',
        (province, year, track, int(rank)),
    ).fetchone()
    if not row:
        return None
    return {
        'province': province,
        'year': year,
        'track': track,
        'rank': int(rank),
        'score': row['score'],
        'band': [row['score'], row['score']],
        'cumulative': row['cumulative'],
        'source': row['source'],
        'source_url': row['source_url'],
    }


def score_to_rank_safe(conn, province, year, track, score):
    """严格版：没有表就抛异常，绝不静默降级。"""
    if not conn.execute(
        'SELECT 1 FROM rank_table WHERE province=? AND year=? AND track=? LIMIT 1',
        (province, year, track),
    ).fetchone():
        raise NoRankTable(
            f'{province} {year} 年 {config.TRACK_CN.get(track, track)} 没有一分一段表')
    return score_to_rank(conn, province, year, track, score)


def score_range_to_rank(conn, province, year, track, score_lo, score_hi):
    """分数区间 -> 位次区间（必须同一年换算）。

    score_hi 是区间上端（考得更好）-> 位次数字更小 -> rank_lo
    score_lo 是区间下端（考得更差）-> 位次数字更大 -> rank_hi

    返回 {'rank_lo','rank_hi','score_lo','score_hi','year','basis'} 或 None。
    """
    lo = int(score_lo)
    hi = int(score_hi)
    if lo > hi:
        lo, hi = hi, lo
    a = score_to_rank_safe(conn, province, year, track, hi)   # 上端 -> 位次小
    b = score_to_rank_safe(conn, province, year, track, lo)   # 下端 -> 位次大
    if not a or not b:
        return None
    return {
        'province': province,
        'year': year,
        'track': track,
        'score_lo': lo,
        'score_hi': hi,
        'rank_lo': a['rank'],
        'rank_hi': b['rank'],
        'basis': f'{year} 年 {province} {config.TRACK_CN.get(track, track)} 一分一段表',
    }
