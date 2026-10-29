# -*- coding: utf-8 -*-
"""专业方向候选库（离线、可维护）。

【为什么要有它】
用户的诉求是「帮我看看学什么专业好」，但我们**没有分专业录取数据**
（掌上高考 `schoolspecialscore` 2024–2026 全 404）。

所以这里做的不是「按分数筛专业」，而是：
  1. 按**选科**判断哪些方向的门关了（政策规则，硬约束）
  2. 按用户勾的**「更在乎什么」**给方向排序
  3. 按**排除项**剔掉用户明确不要的
  4. 输出 3~6 个候选交给模型，让它挑 3 个讲理由

【边界】
`fit` / `job` / `pit` 是行业常识判断，**不是录取数据**。
任何展示都必须带上 `NOTE`，不能包装成「数据支撑」。
"""

NOTE = '方向判断基于公开的选科政策与行业常识，属经验判断，不是录取数据；录取数据只覆盖「全校最低分」'
SOURCE = '内部方向库（经验判断）'

# care 代码与前端一致：job 就业薪资 / gov 考公稳定 / grad 读研深造 /
#                     near 离家近 / brand 学校牌子 / city 城市发展
DIRECTIONS = [
    {
        'key': 'cs', 'name': '计算机 / 软件 / 人工智能',
        'majors': '计算机科学与技术、软件工程、人工智能、数据科学与大数据技术',
        'primary': 'physics', 'need_chem': False,
        'fit': '本科就业面最宽，但校际差距极大，双非要看城市和实习',
        'job': '互联网、软件、国企信息岗，起薪高但吃项目和城市',
        'grad': '考研卷，名校溢价明显',
        'gov': '岗位不少（网信、统计、税务信息化）',
        'care': ['job', 'city', 'brand'],
        'pit': '双非计算机两极分化严重，普通家庭优先看城市和实习机会，别只看专业名',
        'tags': [],
    },
    {
        'key': 'ee', 'name': '电子 / 通信 / 微电子',
        'majors': '电子信息工程、通信工程、微电子科学与工程、集成电路设计',
        'primary': 'physics', 'need_chem': False,
        'fit': '硬科技主线，比纯软件抗周期，但学起来更苦',
        'job': '芯片、通信设备、消费电子，国企和制造业都需要',
        'grad': '读研比例高，硕士才吃到核心岗',
        'gov': '岗位一般',
        'care': ['job', 'grad', 'brand'],
        'pit': '微电子门槛高，本科就业一般，最好做好读研准备',
        'tags': [],
    },
    {
        'key': 'elec', 'name': '电气 / 自动化',
        'majors': '电气工程及其自动化、自动化、机器人工程',
        'primary': 'physics', 'need_chem': False,
        'fit': '就业稳、对口国企多，是「求稳型」技术专业首选',
        'job': '电网、发电、轨道交通、装备制造',
        'grad': '读研为进电网优质岗加分',
        'gov': '电网系统算半个体制内',
        'care': ['gov', 'job', 'near'],
        'pit': '进电网看学校和地域，非电力行业院校优势明显弱一档',
        'tags': [],
    },
    {
        'key': 'mech', 'name': '机械 / 车辆 / 智能制造',
        'majors': '机械设计制造及其自动化、车辆工程、智能制造工程',
        'primary': 'physics', 'need_chem': False,
        'fit': '就业面广、下限稳，上限靠考研或转研发',
        'job': '车企、工程机械、装备制造',
        'grad': '读研可转机器人/新能源方向',
        'gov': '岗位少',
        'care': ['job', 'near'],
        'pit': '本科多在车间/工艺岗，想坐办公室得读研或转方向',
        'tags': [],
    },
    {
        'key': 'energy', 'name': '能源 / 新能源 / 储能',
        'majors': '能源与动力工程、新能源科学与工程、储能科学与工程',
        'primary': 'physics', 'need_chem': True,
        'fit': '政策风口，但强绑定化学，无化学报不了核心方向',
        'job': '电池、光伏、风电、电力集团',
        'grad': '读研友好',
        'gov': '一般',
        'care': ['job', 'grad'],
        'pit': '行业波动大，跟着补贴走，选校要看产业所在地',
        'tags': [],
    },
    {
        'key': 'civil', 'name': '土木 / 建筑 / 交通工程',
        'majors': '土木工程、建筑学、交通工程、水利水电工程',
        'primary': 'physics', 'need_chem': False,
        'fit': '过去十年最热，现在明显降温，靠基建和国企托底',
        'job': '施工单位、设计院、交通系统',
        'grad': '读研可转市政/规划',
        'gov': '交通系统有岗',
        'care': ['gov', 'near'],
        'pit': '施工岗常年驻项目，强度大；设计院在缩编，谨慎',
        'tags': ['土木'],
    },
    {
        'key': 'chem', 'name': '化工 / 材料 / 生物工程',
        'majors': '化学工程与工艺、材料科学与工程、生物工程',
        'primary': 'physics', 'need_chem': True,
        'fit': '基础工业底盘，就业不难但薪资一般，俗称「天坑」',
        'job': '化工、材料、制药、电池材料',
        'grad': '读研后待遇改善明显',
        'gov': '岗位较少',
        'care': ['grad', 'near'],
        'pit': '本科端薪资偏低，工厂环境一般；不读研不建议首选',
        'tags': ['化工', '材料'],
    },
    {
        'key': 'med', 'name': '临床医学 / 口腔医学',
        'majors': '临床医学、口腔医学、麻醉学、医学影像学',
        'primary': 'physics', 'need_chem': True,
        'fit': '最稳的职业之一，但周期极长（本科 5 年 + 规培）',
        'job': '医院、基层医疗、口腔诊所',
        'grad': '几乎必须读研，三甲基本要博士',
        'gov': '事业编，稳定性强',
        'care': ['gov', 'near', 'brand'],
        'pit': '学制长、前十年收入低、夜班多；家里等不起的要慎重',
        'tags': ['医学'],
    },
    {
        'key': 'pharm', 'name': '药学 / 制药工程',
        'majors': '药学、药物制剂、制药工程、临床药学',
        'primary': 'physics', 'need_chem': True,
        'fit': '医药产业链中段，比临床轻松但收入天花板低',
        'job': '药企、CRO、医院药剂科',
        'grad': '读研进研发',
        'gov': '药监系统有岗',
        'care': ['near', 'grad'],
        'pit': '本科多做生产/质检，研发岗要硕博',
        'tags': ['医学', '化工'],
    },
    {
        'key': 'nurse', 'name': '护理 / 康复 / 医学技术',
        'majors': '护理学、康复治疗学、医学检验技术、口腔医学技术',
        'primary': 'any', 'need_chem': False,
        'fit': '分数不高也能进医院，稳定但辛苦',
        'job': '医院护理、康复机构、体检中心',
        'grad': '可选，主要是晋升用',
        'gov': '事业编',
        'care': ['gov', 'near'],
        'pit': '夜班轮转、体力活多；男护士反而稀缺好就业',
        'tags': ['护理', '医学'],
    },
    {
        'key': 'math', 'name': '数学 / 统计 / 数据科学',
        'majors': '数学与应用数学、统计学、应用统计学',
        'primary': 'physics', 'need_chem': False,
        'fit': '最百搭的基础学科，考研转金融/算法/教师都行',
        'job': '数据分析、算法、教师、银行',
        'grad': '数学底子读研选择最宽',
        'gov': '统计系统、教师编',
        'care': ['grad', 'gov'],
        'pit': '本科直接就业一般，必须读研或考编才发挥价值',
        'tags': [],
    },
    {
        'key': 'econ', 'name': '金融 / 经济 / 会计',
        'majors': '金融学、经济学、会计学、财务管理、审计学',
        'primary': 'any', 'need_chem': False,
        'fit': '看学校牌子和城市，双非很难进头部机构',
        'job': '银行、券商、会计师事务所、企业财务',
        'grad': '金融硕士常见路径',
        'gov': '财政、税务、审计岗位多',
        'care': ['gov', 'brand', 'city'],
        'pit': '头部岗位极度看学校出身；普通家庭别指望「金融=高薪」',
        'tags': [],
    },
    {
        'key': 'law', 'name': '法学 / 知识产权',
        'majors': '法学、知识产权、国际经贸规则',
        'primary': 'any', 'need_chem': False,
        'fit': '考公考编岗位多，但司考难度大、无家庭资源慎选',
        'job': '律所、法务、公检法',
        'grad': '法硕常见',
        'gov': '公检法、法务岗需求大',
        'care': ['gov', 'brand'],
        'pit': '没有公检法家庭资源、又不打算考编的，慎选；过了司考才有议价权',
        'tags': ['法学'],
    },
    {
        'key': 'cn', 'name': '汉语言文学 / 新闻传播',
        'majors': '汉语言文学、新闻学、网络与新媒体、广告学',
        'primary': 'any', 'need_chem': False,
        'fit': '考编神器，文字功底型选手的主战场',
        'job': '教师、公务员、企业文案/运营',
        'grad': '学科教学、新闻传播',
        'gov': '公务员岗位最多的专业之一',
        'care': ['gov', 'near'],
        'pit': '纯文学就业面窄，务必走「考编/考公」路线才稳',
        'tags': [],
    },
    {
        'key': 'edu', 'name': '师范 / 教育学',
        'majors': '小学教育、学前教育、学科教学（各科）、特殊教育',
        'primary': 'any', 'need_chem': False,
        'fit': '编制稳定，但近年教师招聘竞争加剧',
        'job': '中小学教师、培训机构',
        'grad': '教育硕士',
        'gov': '事业编',
        'care': ['gov', 'near'],
        'pit': '看地区和学校层次；学龄人口下降，未来编制竞争更激烈',
        'tags': ['师范'],
    },
    {
        'key': 'lang', 'name': '外语 / 翻译 / 国际商务',
        'majors': '英语、日语、商务英语、翻译',
        'primary': 'any', 'need_chem': False,
        'fit': '单一语言已不够，建议「语言 + 一个硬技能」',
        'job': '外贸、跨境电商、翻译、教师',
        'grad': '翻译硕士',
        'gov': '外事、海关有少量岗位',
        'care': ['city', 'job'],
        'pit': '纯语言就业面收窄，AI 冲击明显，别只学语言',
        'tags': [],
    },
    {
        'key': 'mgmt', 'name': '管理 / 工商管理 / 人力资源',
        'majors': '工商管理、人力资源管理、市场营销、物流管理',
        'primary': 'any', 'need_chem': False,
        'fit': '万金油，什么都能干但什么都不精，看实习',
        'job': '企业职能岗、运营、销售管理',
        'grad': 'MBA 或转专业',
        'gov': '综合管理岗',
        'care': ['city', 'brand'],
        'pit': '本科无硬技能，容易变成「销售预备班」，慎选纯管理',
        'tags': [],
    },
    {
        'key': 'police', 'name': '公安 / 军警院校',
        'majors': '公安学类、刑事科学技术、军校指挥类 / 技术类',
        'primary': 'any', 'need_chem': False,
        'fit': '提前批，入警/入伍率高，但要政审、体检、面试',
        'job': '公安系统、部队',
        'grad': '一般不读研',
        'gov': '毕业即入警/入伍',
        'care': ['gov', 'near'],
        'pit': '体检政审卡人，且岗位分配看生源地，不能跨省挑',
        'tags': ['军警'],
    },
    {
        'key': 'agri', 'name': '农林 / 园艺 / 动物医学',
        'majors': '农学、园艺、植物保护、动物医学、食品科学与工程',
        'primary': 'physics', 'need_chem': True,
        'fit': '分数低、录取友好，考编和农业系统有对口岗',
        'job': '农业系统、食品企业、养殖疫苗、宠物医疗',
        'grad': '读研转生物或食品',
        'gov': '农业农村系统岗位',
        'care': ['near', 'gov'],
        'pit': '传统农学就业环境偏基层；动物医学（宠物方向）反而在涨',
        'tags': ['农学'],
    },
    {
        'key': 'geol', 'name': '地质 / 矿业 / 测绘',
        'majors': '地质工程、资源勘查工程、测绘工程、采矿工程',
        'primary': 'physics', 'need_chem': False,
        'fit': '行业院校就业对口，但工作地点偏野外',
        'job': '地质队、矿业、测绘院、自然资源系统',
        'grad': '读研转资源环境',
        'gov': '自然资源系统有岗',
        'care': ['near', 'gov'],
        'pit': '野外作业多、常年出差；女生慎选',
        'tags': ['地质'],
    },
]

_CARE_ORDER = ('job', 'gov', 'grad', 'near', 'brand', 'city')


def pick(primary=None, resel=None, care=None, avoid=None, limit=6):
    """按选科 + 偏好 + 排除项挑方向候选。

    primary: 'physics' / 'history' / None
    resel:   ['chem','bio'] 或 'chem,bio'
    care:    ['job','gov',...]
    avoid:   ['土木','化工',...]  （前端 AVOID_LIST 的标签）
    """
    from . import subject_rules

    resel = subject_rules.parse_resel(resel)
    primary = subject_rules.parse_primary(primary) or 'physics'
    has_chem = 'chem' in resel
    undecided = len(resel) < 2
    care = [c for c in (care or []) if c in _CARE_ORDER]
    avoid = [a for a in (avoid or []) if a]

    scored = []
    for i, d in enumerate(DIRECTIONS):
        if d['primary'] not in ('any', primary):
            continue
        if d.get('need_chem') and not has_chem and not undecided:
            continue  # 无化学 -> 该方向的门真的关了
        tags = d.get('tags') or []
        if any(a in tags or a in d['name'] for a in avoid):
            continue
        score = sum(2 for c in care if c in d.get('care', []))
        scored.append((score, i, d))

    scored.sort(key=lambda x: (-x[0], x[1]))
    out = []
    for score, _, d in scored[:limit]:
        item = dict(d)
        item['need_chem_if_undecided'] = bool(d.get('need_chem') and not has_chem)
        item['score'] = score
        out.append(item)
    return out


def brief(dirs):
    """给模型看的一行行文本（用于拼进死命令数据块）。"""
    lines = []
    for i, d in enumerate(dirs, 1):
        extra = '（要求化学，你没选化学的话这个方向报不了）' if d.get('need_chem_if_undecided') else ''
        lines.append(
            f"{i}. {d['name']}{extra}\n"
            f"   代表专业：{d['majors']}\n"
            f"   定位：{d['fit']}\n"
            f"   就业：{d['job']}\n"
            f"   考研：{d['grad']}；考公：{d['gov']}\n"
            f"   坑：{d['pit']}"
        )
    return '\n'.join(lines)
