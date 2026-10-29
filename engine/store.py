# -*- coding: utf-8 -*-
"""SQLite 存储层：建表、连接、元信息。"""
import os
import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- 一分一段表：某省某年某科类，每个分数对应的人数与累计人数（= 该分数的全省位次）
CREATE TABLE IF NOT EXISTS rank_table (
    province   TEXT    NOT NULL,
    year       INTEGER NOT NULL,
    track      TEXT    NOT NULL,
    score      INTEGER NOT NULL,
    cnt        INTEGER,
    cumulative INTEGER NOT NULL,
    source     TEXT,
    source_url TEXT,
    PRIMARY KEY (province, year, track, score)
);
CREATE INDEX IF NOT EXISTS ix_rank_cum ON rank_table(province, year, track, cumulative);

CREATE TABLE IF NOT EXISTS school (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    province   TEXT,
    city       TEXT,
    level      TEXT,
    type       TEXT,
    nature     TEXT,
    belong     TEXT,
    f985       INTEGER DEFAULT 0,
    f211       INTEGER DEFAULT 0,
    dual_class TEXT
);
CREATE INDEX IF NOT EXISTS ix_school_name ON school(name);

-- 校线原始数据：某校在某招生省份某年的最低分（全校口径）
CREATE TABLE IF NOT EXISTS school_score (
    school_id  INTEGER NOT NULL,
    province   TEXT    NOT NULL,
    year       INTEGER NOT NULL,
    track      TEXT    NOT NULL,
    min_score  INTEGER NOT NULL,
    source     TEXT    NOT NULL,
    source_url TEXT,
    PRIMARY KEY (school_id, province, year, track)
);
CREATE INDEX IF NOT EXISTS ix_ss ON school_score(province, year, track);

-- 校线换算结果：同一行里必须保留用于换算的分数与年份，保证可审计
CREATE TABLE IF NOT EXISTS school_rank (
    school_id  INTEGER NOT NULL,
    province   TEXT    NOT NULL,
    year       INTEGER NOT NULL,
    track      TEXT    NOT NULL,
    min_score  INTEGER NOT NULL,
    min_rank   INTEGER NOT NULL,
    PRIMARY KEY (school_id, province, year, track)
);
CREATE INDEX IF NOT EXISTS ix_sr ON school_rank(province, year, track, min_rank);

-- 专业组级（院校专业组）：分专业录取线 + 招生计划/学费 合并后的结果
-- 一个 special_group id 唯一标识一个「院校专业组」（同一个组内各专业选科要求必须相同）
CREATE TABLE IF NOT EXISTS special_group (
    school_id  INTEGER NOT NULL,
    province   TEXT    NOT NULL,
    year       INTEGER NOT NULL,
    track      TEXT    NOT NULL,
    grp        INTEGER NOT NULL,      -- special_group
    sg_name    TEXT,                  -- 组号，如 （119）
    sg_info    TEXT,                  -- 选科要求原文，如「首选物理，再选化学、生物(2科必选)」
    batch      TEXT,                  -- 本科批 / 本科提前批 / 本科批（特殊类型）
    plan_num   INTEGER,               -- 组计划总数
    tuition    INTEGER,               -- 学费（元/年）
    min_score  INTEGER,               -- 组内最低分
    min_rank   INTEGER,               -- 组内最低位次（当年口径）
    ref_rank   INTEGER,               -- 换算到参考年（2026）的等效位次
    n_major    INTEGER,
    PRIMARY KEY (school_id, province, year, track, grp)
);
CREATE INDEX IF NOT EXISTS ix_sg ON special_group(province, year, track, ref_rank);

-- 专业级（组内每个专业一行）
-- src: score = 来自分专业录取线（有分数/位次）；plan = 来自招生计划（有计划数/学费/学制）
-- 两个接口的专业名口径不同（分数线按具体专业、计划按招生大类），所以各存各的，不强行合并
CREATE TABLE IF NOT EXISTS special_major (
    school_id  INTEGER NOT NULL,
    province   TEXT    NOT NULL,
    year       INTEGER NOT NULL,
    track      TEXT    NOT NULL,
    grp        INTEGER NOT NULL,
    spname     TEXT    NOT NULL,
    src        TEXT    NOT NULL DEFAULT 'score',
    min_score  INTEGER,
    min_rank   INTEGER,
    avg_score  INTEGER,
    max_score  INTEGER,
    plan_num   INTEGER,
    tuition    INTEGER,
    length     TEXT,
    PRIMARY KEY (school_id, province, year, track, grp, spname, src)
);
CREATE INDEX IF NOT EXISTS ix_sm ON special_major(school_id, province, year, track, grp);
"""


def connect(path=None):
    """打开数据库（自动建目录、开启 WAL）。"""
    path = path or config.db_path()
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def set_meta(conn, key, value):
    conn.execute(
        'INSERT INTO meta(key, value) VALUES(?, ?) '
        'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
        (key, str(value)),
    )


def get_meta(conn, key, default=None):
    row = conn.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
    return row['value'] if row else default


def counts(conn):
    out = {}
    for t in ('rank_table', 'school', 'school_score', 'school_rank',
              'special_group', 'special_major'):
        try:
            out[t] = conn.execute(f'SELECT COUNT(*) c FROM {t}').fetchone()['c']
        except sqlite3.Error:
            out[t] = 0
    return out
