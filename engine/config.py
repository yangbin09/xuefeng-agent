# -*- coding: utf-8 -*-
"""引擎配置：路径、省份、科类、分档参数、数据源署名。"""
import os

# ---------- 路径 ----------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
RAW_DIR = os.path.join(DATA_DIR, 'raw')
RANK_RAW_DIR = os.path.join(RAW_DIR, 'yifenyiduan')
SCHOOL_INDEX_GZ = os.path.join(RAW_DIR, 'school-index.json.gz')
DB_PATH = os.path.join(DATA_DIR, 'engine.db')

# ---------- 数据源 ----------
API_BASE = 'https://static-data.gaokao.cn/www/2.0'
API_UA = 'xuefeng-engine/0.1 (local personal use)'
SOURCE_LIVE = '掌上高考/static-data.gaokao.cn'
SOURCE_INDEX = '掌上高考静态索引'
SOURCE_RANK_TABLE = '省考试院一分一段表'

# 招生省份 -> 掌上高考 province id
PROVINCE_IDS = {'湖南': 43, '广东': 44}

# 一分一段 track -> 中文名
TRACK_CN = {
    'physics': '物理类',
    'history': '历史类',
    'combined': '综合',
    'science': '理工',
    'liberal': '文史',
}
# 掌上高考 type 码 -> 一分一段 track
TRACK_FROM_CODE = {
    '2073': 'physics',
    '2074': 'history',
    '3': 'combined',
    '1': 'science',
    '2': 'liberal',
}

# ---------- 参考年 ----------
# 2027 届填报时，2027 投档线尚未产生，主要参考 2026；同时保留 2024/2025 看趋势。
REFERENCE_YEAR = 2026
HISTORY_YEARS = (2024, 2025, 2026)

# ---------- 冲 / 稳 / 保 ----------
# 判定口径：该校「最低录取位次」(mr) 与「考生位次」(r) 的比值
#   mr / r < 1  →  学校更难（要求更靠前的位次）
#   mr / r > 1  →  学校更容易
BANDS = (
    ('chong', 0.80, 0.95),   # 冲：比考生好 5%~20%
    ('wen',   0.95, 1.10),   # 稳：±10% 内
    ('bao',   1.10, 1.45),   # 保：比考生低 10%~45%
)
BAND_CN = {'chong': '冲', 'wen': '稳', 'bao': '保'}

DEFAULT_LIMIT = 15

# ---------- 区间填报（预演模式）----------
# 考生给的是「预估分数区间」，换算成位次区间 [rank_lo, rank_hi]（lo 更靠前 = 更好）
#   校线位次 mr < rank_lo            → 冲：比你的最好情况还好
#   rank_lo <= mr <= rank_hi         → 稳：落在估分区间内，看发挥
#   rank_hi < mr                     → 保：比你的最差情况还容易
RANGE_CHONG_RATIO = 0.65   # 冲档下探到 rank_lo 的 0.65 倍
RANGE_BAO_RATIO = 1.50     # 保档上探到 rank_hi 的 1.50 倍
RANGE_MAX_WIDTH = 25       # 分数区间最大宽度（分），超过会说人话劝缩
RANGE_MIN_WIDTH = 3        # 太窄就退化成单点，没意义


# ---------- 分专业 / 招生计划（掌上高考 zjzw 接口）----------
# 注意：两个接口的版本前缀不同，用错会返回 code=1064（接口请求版本不存在）
#   分专业录取线   apidata/api/gk/score/special     （gk 前缀）
#   招生计划+学费  apidata/api/gkv3/plan/school     （gkv3 前缀）
API_ZJZW = 'https://api.zjzw.cn/web/api/'
ZJZW_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'),
    'Referer': 'https://www.zjzw.cn/',
    'Origin': 'https://www.zjzw.cn',
}
ZJZW_URI_SCORE = 'apidata/api/gk/score/special'
ZJZW_URI_PLAN = 'apidata/api/gkv3/plan/school'
ZJZW_PAGE_SIZE = 20          # 实测上限 20；size=50 会静默返回空
SPECIAL_YEAR = 2025          # 分专业数据实际完整的年份（2026 尚稀）
SOURCE_SPECIAL = '掌上高考/zjzw（分专业录取线）'
SOURCE_PLAN = '掌上高考/zjzw（招生计划）'


def db_path():
    return os.environ.get('XUEFENG_ENGINE_DB', DB_PATH)
