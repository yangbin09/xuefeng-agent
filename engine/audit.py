# -*- coding: utf-8 -*-
"""可审计输出层。

两件事：
1. 给每一行数据打来源标签（省 · 年 · 科类 · 数据源）。
2. 扫描 LLM 回复里的分数/位次数字，凡是证据包里没有的，全部点名。
   目标不是「让回复好看」，而是「不让编造的数字混过去」。
"""
import re

from . import config


def tag(province, year, track, source=None):
    """生成来源标签，例如 [2026·湖南·物理类·掌上高考]。"""
    src = source or config.SOURCE_LIVE
    short = '掌上高考' if 'gaokao' in src else src
    return f'[{year}·{province}·{config.TRACK_CN.get(track, track)}·{short}]'


def format_item(it):
    """把一条推荐格式化成带来源的一行文本。"""
    flags = []
    if it.get('f985'):
        flags.append('985')
    if it.get('f211'):
        flags.append('211')
    if it.get('dual_class') and it['dual_class'] not in ('双一流',):
        flags.append(it['dual_class'])
    flag = (' ' + '/'.join(flags)) if flags else ''
    city = f" {it['city']}" if it.get('city') else ''
    return (f"{it['school']}{flag}{city}  "
            f"{it['year']}年最低 {it['score']}分 / 位次 {it['rank']}  "
            f"{tag(it['province'], it['year'], it['track'], it.get('source'))}")


# ---------------------------------------------------------------- 编造检测

# 结构性数字：招生志愿数、985/211、年份等，不该被当成编造的分数
_STRUCTURAL = {
    2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20, 24, 30, 40, 45, 48, 50, 60, 70,
    80, 96, 100, 112, 150, 200, 211, 750, 985,
}
_YEAR_MIN, _YEAR_MAX = 2020, 2035

_NUM_RE = re.compile(r'(?<![\d.])(\d{2,6})(?![\d.])')


def _is_structural(n):
    if n in _STRUCTURAL:
        return True
    if _YEAR_MIN <= n <= _YEAR_MAX:
        return True
    return False


def scan(reply, evidence, context_chars=18):
    """扫描回复中的可疑数字。

    判定：
      - 分数型：200~750，且不是整十（整十多为「600分左右」这类泛指的合法表述）
      - 位次型：1000~600000，且不是整百
      - 特例：与考生位次同量级（0.5~2 倍）的整百位次也算可疑，
        因为编造位次最常见的写法就是 15000 / 20000 这种整数
      - 且不在证据包里
    返回 [{'value','kind','snippet'}]。
    """
    allowed_scores = {int(x) for x in evidence.get('scores', ())}
    allowed_ranks = {int(x) for x in evidence.get('ranks', ())}
    years = {int(x) for x in evidence.get('years', ())}
    cand = evidence.get('candidate_rank')
    try:
        cand = int(cand) if cand else 0
    except (TypeError, ValueError):
        cand = 0

    suspects, seen = [], set()
    for m in _NUM_RE.finditer(reply or ''):
        n = int(m.group(1))
        if n in seen or _is_structural(n):
            continue
        if n in allowed_scores or n in allowed_ranks or n in years:
            continue

        kind = None
        if 200 <= n <= 750 and n % 10 != 0:
            kind = 'score'
        elif 1000 <= n <= 600000 and n % 100 != 0:
            kind = 'rank'
        elif 1000 <= n <= 600000 and cand and cand * 0.5 <= n <= cand * 2:
            kind = 'rank'
        if not kind:
            continue

        seen.add(n)
        lo = max(0, m.start() - context_chars)
        hi = min(len(reply), m.end() + context_chars)
        suspects.append({
            'value': n,
            'kind': kind,
            'snippet': reply[lo:hi].replace('\n', ' ').strip(),
        })
    return suspects


def warning_block(suspects):
    """把可疑数字整理成一段可直接追加到回复末尾的提示。"""
    if not suspects:
        return ''
    lines = ['', '---', '⚠️【数据校验】以下数字未出现在本次数据库查询结果中，'
                     '可能是模型自行推断，请以官方投档线为准，勿直接采信：']
    for s in suspects[:12]:
        kind = '分数' if s['kind'] == 'score' else '位次'
        lines.append(f'- `{s["value"]}`（疑似{kind}）… {s["snippet"]}')
    if len(suspects) > 12:
        lines.append(f'- 另有 {len(suspects) - 12} 处未列出')
    return '\n'.join(lines)


def verify(reply, evidence):
    """返回 (是否可信, 追加提示文本, 可疑列表)。"""
    suspects = scan(reply, evidence)
    return (not suspects), warning_block(suspects), suspects
