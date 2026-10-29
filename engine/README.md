# 位次引擎（engine/）

给雪峰 Agent 换掉数据层用的独立模块。**不改界面**，只把「按分数猜」换成「按位次算」。

## 为什么要有它

原来那个 `admission_clean.db` 的问题不是「旧」，是**结构上没法用**：

- 湖南 1717 行 / 广东 202 行，**位次字段全部为空**
- 只能拿今年分数比去年分数 —— 而 600 分在湖南 2025 是 15860 位、2026 是 18876 位，一年挪 3000 名
- 没有一分一段表，也没有可追溯的来源

这个引擎只做三件事：**一分一段换算、位次分档、来源留痕**。

## 数据来源

| 数据 | 来源 | 覆盖 |
|---|---|---|
| 一分一段表 | 省考试院（经 eol.cn 整理） | 湖南 / 广东 × 2024 / 2025 / 2026 × 物理 / 历史 |
| 校线 2023–2025 | 掌上高考静态索引（单文件 3145 校） | 全部院校 |
| 校线 2026 | `static-data.gaokao.cn` 实时接口 | 全部院校 |

原始文件固化在 `data/raw/`，不依赖任何外部安装。

## 快速开始

```bash
# 1. 初始化（离线部分，约 10 秒）
python -m engine init --no-live

# 2. 拉取 2026 实时校线（约 12~15 分钟，可断点续跑）
python -m engine fetch-scores --years 2026 --workers 12

# 3. 看覆盖
python -m engine status

# 4. 自检
python -m engine selftest
```

## 常用命令

```bash
# 分数 -> 位次
python -m engine rank --province 湖南 --year 2026 --score 600
#   湖南 2026 物理类  600 分 → 位次 18876  [2026·湖南·物理类·掌上高考]

# 位次 -> 分数
python -m engine score --province 广东 --year 2026 --rank 30891

# 冲稳保（按位次）
python -m engine recommend --province 湖南 --track physics --score 600 --limit 15
python -m engine recommend --province 广东 --track physics --rank 30891 --only-211
python -m engine recommend --province 湖南 --track physics --score 600 --json

# 区间填报（预演）：给分数区间 + 选科组合
python -m engine recommend --province 湖南 --track physics \
    --score-lo 585 --score-hi 605 --first physics --resel chem,bio --limit 10

# 位次区间也可以
python -m engine recommend --province 湖南 --track physics --rank-lo 16521 --rank-hi 26952
```

## 区间口径（预演填报，2027 届最常用）

考生还没出分，给的是**预估分数区间**。引擎把它换算成**位次区间** `[rank_lo, rank_hi]`
（`rank_lo` 更靠前 = 考得更好），然后：

```
校线位次 mr <  rank_lo          冲：比你的最好情况还要好
rank_lo <= mr <= rank_hi        稳：落在估分区间内，看发挥
mr > rank_hi                    保：比你的最差情况还容易

窗口：冲下探到 rank_lo × 0.65，保上探到 rank_hi × 1.50
```

参数在 `config.py` 的 `RANGE_CHONG_RATIO` / `RANGE_BAO_RATIO` / `RANGE_MAX_WIDTH`。

**关键口径：分数 → 位次必须用同一年的一分一段表。**
`school_rank.min_rank` 是参考年的录取位次，混年换算就是跨年混算，会人为把区间放大 40%。

每条结果额外带：

| 字段 | 含义 |
|---|---|
| `need_score` | 该校门槛分（= 参考年最低录取分，和区间同年口径） |
| `gap_text` | `差 14 分` / `区间内` / `贴底线` / `富余 12 分` |
| `prelim` / `prelim_kind` | 提前批标记（`军` / `警`），这类学校要政审体检面试，不能和本科批混比 |
| `hist_zones` | 近三年（2024/2025/2026）每年的录取位次按**考生同一区间**归到的档位 |
| `zone_text` | 次数汇总，如 `稳2 冲1` / `保3` |
| `volatile` / `big_small` | 三年跨过档位 / 三年内既进过冲又进过保（大小年） |
| `nature` / `nature_group` / `expensive` | 办学性质：公办 / 民办 / 合作办学；后两者 `expensive=True` |

实测（湖南 物理 585~605 → 位次 16521~26952）：冲 37 / 稳 57 / 保 67，
可选空间合适；区间宽度建议 ≤ 25 分（`RANGE_MAX_WIDTH`），再宽冲稳保就失去意义。

## 近三年分档（为什么不给概率）

单年的「稳」是快照。把 2024–2026 三年位次各自按同一区间归一次档，再数次数：

```
考生区间 [16521, 26952] 的 161 所有数据候选校：
  三年同档     110 所（68%）
  三年跨档      51 所（32%）   ← 现在的「稳」字有三分之一会失效
  三年没进过稳  78 所（48%）
```

所以只输出 `稳2 冲1` 这种**次数**，不输出百分比：

- 三年样本撑不出「录取概率 87%」，那是伪精确
- 同一套口径也能用于单值模式（用 `BANDS` 倍率归一次档），不会出现「区间才有、单点没有」的割裂

`big_small = 三年里既出现过冲又出现过保`——这类学校忽高忽低，不能当保底。
实现见 `recommend._zone_of()`。

## 办学性质 / 高学费

`school.nature` 直接透出，并归成三类：公办 / 民办（含独立学院）/ 合作办学（中外合作、内地与港澳台合作、境外独立办学）。

为什么必须标：实测「湖南物理 585–605」这一档里混着 4 所中外合作（北京交通大学威海校区、西交利物浦、深圳北理莫斯科、安徽大学纽约石溪），
学费 4~9 万/年，而普通公办约 5 千/年。**不标就是让家长报完才知道。**

目前只做「高/不高」二分（基于办学性质），**没有具体学费数字**；
`gkv3/plan/school` 接口带 `tuition` 字段（已验证可用），后续入库后可精确到专业组。

## 选科组合（`subject_rules.py`）

3+1+2：首选 物理/历史 + 再选 化学/生物/政治/地理 中选 2 门 = 12 种组合。

```python
from engine import subject_rules
subject_rules.analyze('physics', ['chem', 'bio'])
# {'label': '物化生', 'level': 'wide', 'coverage': '约 96%',
#  'closed': [...], 'warning': '', 'note': '...政策规则，非录取数据'}
```

| 组合 | 可报专业面 | 关闭方向 |
|---|---|---|
| 物化生 / 物化地 / 物化政 | 约 96% | 基本无 |
| 物生政 / 物生地 / 物政地（无化学） | 约 55% | 临床/口腔/药学/材料/化工/生物工程 |
| 历史类任意 | 约 50% | 理工农医全部 |

**边界**：首选科目（物理/历史）能**真筛**（`school_rank.track`）；
再选科目**没有**专业组选科要求数据，只能做「专业面提示」，不作筛选。展示时必须标注这是政策规则。

## 专业组（P6 + P9，录取的最小单位）

湖南 / 广东的志愿填报单位不是「学校」，是**院校专业组**：本科批 45 个院校专业组，
每组内 6 个专业志愿 + 1 个是否服从调剂，且**同组内各专业选考科目必须相同**。

所以「全校最低分」只能告诉你能不能进档，不能告诉你**能不能读那个专业**。
这一层用两个接口补齐（前缀不同，用错就是 `1064`）：

| 数据 | 接口 | 关键字段 |
|---|---|---|
| 分专业录取线 | `apidata/api/gk/score/special`（gk 前缀） | `spname` `sg_name` `sg_info` `min` `min_section` `special_group` |
| 招生计划 + 学费 | `apidata/api/gkv3/plan/school`（**gkv3** 前缀） | `num` `tuition` `length` `sg_name` `sg_info` `special_group` `local_batch_name` |

`special_group` 是两者的关联键，一 join 就是完整画像：**计划数 + 学费 + 学制 + 选科要求 + 最低分 + 最低位次**。

### 什么时候抓

```bash
python -m engine ingest-special --all                 # 湖南+广东 × 物理+历史
python -m engine ingest-special --province 湖南 --track physics
python -m engine special-status                      # 看入库情况
```

- `size` 上限 20，`size=50` 会**静默返回空列表**（code 仍是 0000）
- 必须逐校抓（全省翻页会封顶约 3600 条），可断点续跑：已入库的学校自动跳过
- 服务端会 **HTTP 429 限流**，代码里做了全局自适应节流（`_PACE`）：遇到 429 自动放慢、连续成功再放开
- 实测单批 500 校 ≈ 1800 个组，之后需要放慢速度

### 两个口径细节

1. **分专业数据目前只到 2025**（2026 尚稀）。入库时把组线位次换算成 **2026 等效位次**
   （2025 位次 → 2025 分数 → 2026 位次），`special_group.ref_rank` 存这个值。
   界面上的「需考到」也换成 2026 口径分数，和「你的区间 585–605 分」同年可比。
   换算不了的行 `ref_rank` 留空，只展示不参与分档，绝不硬凑。
2. **再选科目从「提示」变成「真筛选」**：`special.parse_require()` 解析 `sg_info`
   （支持 `化学、生物(2科必选)` / `化学` / `不限` / `化学或生物` 等写法），
   再按考生选科判断可报性。**只有再选 2 门都确定了才剔除学校**；没选满按最宽口径只提示。

### 关键函数

```python
from engine import special
special.parse_require('首选物理，再选化学、生物(2科必选)')
# {'primary': 'physics', 'groups': [['chem', 'bio']], 'unlimited': False}
special.reportable(req, 'physics', ['chem', 'bio'])      # True
special.reportable(req, 'physics', ['bio', 'pol'])       # False（缺化学）
special.school_groups(conn, school_id, '湖南', 'physics', 'physics', ['chem','bio'],
                      range_mode=True, r_lo=16521, r_hi=26952, score_lo=585, score_hi=605)
special.summarize(conn, [school_id], '湖南', 'physics', 'physics', ['bio','pol'])
```

### 实测样例（中南大学 2025 湖南物理，2026 等效口径）

| 组 | 选科 | 需考到 | 差几分 | 学费 | 计划 | 组内专业 |
|---|---|---|---|---|---|---|
| （119） | 物+化+生 | 655 | 差 50 分 | 7800 | 25 | 临床医学（八年制） |
| （116） | 物+化 | 629 | 差 24 分 | 6500 | 501 | 计算机、生物科学（拔尖）… |
| （118） | 物+化+生 | 625 | 差 20 分 | 7800 | 94 | 口腔医学（5+3）、临床医学类 |

同一所中南大学：**物化生 16 个组全可报；物生政 只有 2 个组可报**（其余要求化学）。
这就是「再选科目」的真实影响，以前只能靠一句提示。

## 分档口径

全部基于位次，**不用分数**：

```
倍率 = 该校最低录取位次 ÷ 考生位次
  倍率 < 1  →  学校要求更靠前的位次（更难）
  倍率 > 1  →  学校更容易

冲：0.80 ~ 0.95
稳：0.95 ~ 1.10
保：1.10 ~ 1.45
```

参数在 `engine/config.py` 的 `BANDS`，可直接调。

## 可审计

1. 每条结果都带 `year` / `min_score` / `min_rank` / `source`。
2. `audit.tag()` 生成来源标签，如 `[2026·湖南·物理类·掌上高考]`。
3. `audit.scan(reply, evidence)` 扫描 LLM 输出里**不在证据包中的分数/位次**并点名：

```python
from engine import audit, recommend
ev = recommend.evidence_from(result)
ok, warn, suspects = audit.verify(llm_reply, ev)
```

前端也有一份等价实现（`index.html` 的 `auditScan`），直接在回复末尾插入 ⚠️【数据校验】。

## 代码结构

```
engine/
├── config.py       配置：省份、科类、分档参数、区间参数、分专业接口、路径
├── store.py        SQLite 表结构（rank_table / school / school_score / school_rank / special_*）
├── ingest.py       数据录入 + 位次换算
├── ingest_special.py 分专业录取线 + 招生计划/学费抓取（逐校、限速、可续跑）
├── convert.py      分数 <-> 位次（含分数区间 -> 位次区间，严格同年）
├── recommend.py    冲稳保算法（单值 + 区间）+ 提前批标记 + 近三年分档 + 办学性质 + 证据包
├── special.py      专业组：选科要求解析、可报性、组级冲稳保、学费/计划
├── subject_rules.py 选科组合 -> 可报专业面（政策规则，非录取数据）
├── audit.py        来源标签 + 编造检测
├── web_adapter.py  给 server.py 的适配层（前端契约）
├── export_xlsx.py  Excel 导出
└── cli.py          命令行
```

## 数据表

| 表 | 含义 |
|---|---|
| `rank_table` | 一分一段：(省, 年, 科类, 分数) → 累计人数（= 该分数位次） |
| `school` | 3145 所学校元信息（985/211/双一流/城市/类型） |
| `school_score` | 校线原始值：某校在某招生省某年的最低分 + 来源 |
| `school_rank` | 校线换算结果：最低分 + **最低位次**（严格同年对齐） |
| `special_group` | 院校专业组：组号/选科要求/批次/计划数/学费/组最低分/组最低位次/`ref_rank`（换算到参考年） |
| `special_major` | 组内专业行（`src`=`score` 是分专业录取线，`src`=`plan` 是招生计划里的专业/大类） |

## 已知边界

- 只收录 **湖南、广东**。加省份：改 `config.PROVINCE_IDS`，把对应 `{pinyin}-{year}-{track}.json` 放进 `data/raw/yifenyiduan/`，重跑 `init`。
- 校线是**全校口径**（该省该科类最低分），不是分专业/分专业组。分专业数据实测可通过
  `uri=apidata/api/gk/score/special`（`local_province_id` / `local_type_id` / `school_id`）取得，
  含 `special_group` / `sg_info`（选科要求）/ `min` / `min_section`，**但尚未入库**；
  招生计划与学费在 `uri=apidata/api/gkv3/plan/school`（注意前缀是 gkv3）。详见仓库根目录 `优化空间评估.md`。
- 所以「想学什么专业」不能用来筛学校，产品上改成让用户选「更在乎什么」，专业方向由 LLM + 经验判断给，并标注非录取数据。
- 再选科目（化学/生物/政治/地理）没有专业组选科要求数据，只能提示不能筛。
- 提前批（军校/公安院校）已经打标 `prelim`，但**没有排除**：它们走提前批、要政审体检面试，用「不含军警」筛选器可一键隐藏。
- 2023 年没有一分一段表，只保留分数、不参与位次匹配。
- 掌上高考是第三方聚合，最终以省考试院公布为准；`source_url` 字段保留了原始出处。
