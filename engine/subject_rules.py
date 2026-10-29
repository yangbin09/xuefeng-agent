# -*- coding: utf-8 -*-
"""选科组合 -> 可报专业面（政策级规则）。

依据：教育部《普通高等学校本科招生专业选考科目要求指引》，
2024 年起理工农医类普遍要求「物理 + 化学」绑定。

【边界，必须说清】
这里回答的是「哪些方向的门关了」，依据是**政策规则**；
它不回答「多少分能上」，那需要分专业录取数据（本库没有）。
所以任何展示都要标注：政策规则，非录取数据。

组合命名（3+1+2，湖南/广东）：
    首选：物理 / 历史
    再选：化学 / 生物 / 政治 / 地理 中选 2 门 -> 12 种组合
"""

PRIMARY = {'physics': '物理', 'history': '历史'}
RESEL = {'chem': '化学', 'bio': '生物', 'pol': '政治', 'geo': '地理'}
RESEL_ORDER = ('chem', 'bio', 'pol', 'geo')

_PRIMARY_ALIASES = {
    'physics': 'physics', '物理': 'physics', '物理类': 'physics', '物': 'physics',
    'history': 'history', '历史': 'history', '历史类': 'history', '史': 'history',
}
_RESEL_ALIASES = {
    'chem': 'chem', '化学': 'chem', '化': 'chem',
    'bio': 'bio', '生物': 'bio', '生': 'bio',
    'pol': 'pol', '政治': 'pol', '思想政治': 'pol', '政': 'pol',
    'geo': 'geo', '地理': 'geo', '地': 'geo',
}

# 无化学时关闭的方向（首选物理）
NO_CHEM_CLOSED = [
    ('临床医学 / 口腔医学', '要求「物理 + 化学」'),
    ('药学 / 药物制剂', '要求「物理 + 化学」'),
    ('材料类', '要求「物理 + 化学」'),
    ('化学工程与工艺', '要求「物理 + 化学」'),
    ('生物工程 / 生物技术', '多数院校要求「物理 + 化学」'),
    ('中医学（多数院校）', '多数院校要求「物理 + 化学」'),
    ('部分院校的计算机 / 电子信息', '顶校普遍要求「物理 + 化学」'),
]

# 首选历史时关闭的方向
HISTORY_CLOSED = [
    ('工科全部（机械 / 电子 / 计算机 / 电气 / 自动化 / 土木）', '要求首选物理'),
    ('医学类（临床 / 口腔 / 药学）', '要求「物理 + 化学」'),
    ('理学（数学 / 物理 / 化学 / 生物）', '要求首选物理'),
    ('农学类', '要求「物理 + 化学」'),
]

HISTORY_OPEN = ['文学 / 新闻传播', '法学', '经济学 / 管理学', '外语',
                '哲学 / 历史学', '教育学（部分方向）']

NOTE = '依据教育部选考科目要求指引（2024 年起理工农医「物化绑定」），属政策规则，非录取数据'
SOURCE = '教育部《普通高校本科招生专业选考科目要求指引》'


def parse_primary(v):
    """把 '物理类' / 'physics' / '物化生' 归一成 physics / history / None。"""
    if not v:
        return None
    s = str(v).strip()
    if s in _PRIMARY_ALIASES:
        return _PRIMARY_ALIASES[s]
    if '历史' in s or s.startswith('史'):
        return 'history'
    if '物理' in s or s.startswith('物'):
        return 'physics'
    return None


def parse_resel(v):
    """把 ['化学','生物'] / 'chem,bio' / '物化生' 归一成 ['chem','bio']。"""
    if not v:
        return []
    if isinstance(v, (list, tuple, set)):
        parts = [str(x) for x in v]
    else:
        s = str(v)
        for sep in ('，', ',', '/', '+', '、', ' '):
            s = s.replace(sep, '|')
        parts = [x for x in s.split('|') if x]
        # 支持连写「物化生」「史政地」「化生」
        if len(parts) == 1 and parts[0]:
            t = parts[0]
            if len(t) > 2 and t[0] in ('物', '史'):
                t = t[1:]
            if t and all(ch in _RESEL_ALIASES for ch in t):
                parts = list(t)
    out = []
    for p in parts:
        k = _RESEL_ALIASES.get(p.strip())
        if k and k not in out:
            out.append(k)
    return out[:2]


def combo_label(primary, resel):
    """组合短名：物化生 / 史政地。"""
    if not primary:
        return '未选'
    s = '物' if primary == 'physics' else '史'
    for k in RESEL_ORDER:
        if k in (resel or []):
            s += RESEL[k][0]
    return s


def combo_full(primary, resel):
    if not primary:
        return ''
    parts = [PRIMARY[primary]] + [RESEL[k] for k in RESEL_ORDER if k in (resel or [])]
    return '+'.join(parts)


def analyze(primary=None, resel=None):
    """返回可报专业面分析 dict（始终能返回，不抛异常）。"""
    primary = parse_primary(primary)
    resel = parse_resel(resel)
    undecided = len(resel) < 2
    has_chem = 'chem' in resel

    out = {
        'primary': primary,
        'primary_cn': PRIMARY.get(primary, ''),
        'resel': resel,
        'resel_cn': [RESEL[k] for k in RESEL_ORDER if k in resel],
        'undecided': undecided,
        'label': combo_label(primary, resel),
        'full': combo_full(primary, resel),
        'closed': [],
        'open': [],
        'warning': '',
        'coverage': '',
        'level': '',
        'level_cn': '',
        'note': NOTE,
        'source': SOURCE,
    }

    if primary == 'history':
        out.update(level='half', level_cn='专业面约一半', coverage='约 50%',
                   closed=[{'name': n, 'why': w} for n, w in HISTORY_CLOSED],
                   open=HISTORY_OPEN)
        out['warning'] = '首选历史的话，理工农医基本进不去，主要在人文社科和管理类里选。'
        return out

    if primary == 'physics' and not has_chem and not undecided:
        out.update(level='narrow', level_cn='专业面明显收窄', coverage='约 55%',
                   closed=[{'name': n, 'why': w} for n, w in NO_CHEM_CLOSED],
                   open=['计算机（多数院校）', '电气 / 自动化 / 机械', '数学 / 统计',
                         '经济 / 金融 / 管理', '法学 / 外语 / 新闻'])
        out['warning'] = ('物理但没有化学：临床医学、口腔、药学、材料、化工、生物工程这些'
                          '主流方向会被「物化绑定」挡在门外，可报专业面明显收窄。')
        return out

    # 物理 + 化学（或再选还没定，按最宽口径算）
    out.update(level='wide', level_cn='专业面最宽', coverage='约 96%',
               open=['理工农医几乎全部', '计算机 / 电子 / 电气 / 自动化',
                     '临床 / 口腔 / 药学', '经济 / 金融 / 管理 / 法学'])
    if undecided:
        out['warning'] = ('再选科目还没选满，本次按最宽口径（含化学）计算。'
                          '若最终没有化学，临床医学、口腔医学、药学、材料、化工、'
                          '生物工程等方向会关闭。')
        out['if_no_chem_closed'] = [{'name': n, 'why': w} for n, w in NO_CHEM_CLOSED]
    else:
        out['coverage'] = '约 96%'
    return out
