# -*- coding: utf-8 -*-
"""命令行入口：python -m engine <command>"""
import argparse
import json
import sys

from . import (audit, config, convert, ingest, ingest_special, major_dirs,
               recommend as rec_mod, store, subject_rules)


def _open(auto_init=True):
    conn = store.connect()
    if auto_init:
        store.init_db(conn)
    return conn


def _print_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- 命令

def cmd_init(args):
    conn = _open()
    counts, n = ingest.bootstrap(
        conn, with_live=not args.no_live, workers=args.workers, limit=args.limit)
    print('\n完成。表统计：', counts)
    return 0


def cmd_fetch_scores(args):
    conn = _open()
    years = tuple(int(y) for y in args.years.split(',')) if args.years else (
        config.REFERENCE_YEAR,)
    n = ingest.fetch_live_scores(conn, years=years, workers=args.workers, limit=args.limit)
    print(f'录入 {n} 条，重新换算位次…')
    ingest.build_school_rank(conn)
    return 0


def cmd_build_rank(args):
    conn = _open()
    ingest.build_school_rank(conn)
    return 0


def cmd_status(args):
    conn = _open()
    counts = store.counts(conn)
    tables = convert.available(conn)
    coverage = []
    for prov in config.PROVINCE_IDS:
        for track in ('physics', 'history'):
            rows = conn.execute(
                'SELECT year, COUNT(*) n FROM school_rank WHERE province=? AND track=? '
                'GROUP BY year ORDER BY year', (prov, track)).fetchall()
            coverage.append({
                'province': prov, 'track': config.TRACK_CN[track],
                'school_rank_by_year': {r['year']: r['n'] for r in rows},
            })
    out = {
        'db': config.db_path(),
        'counts': counts,
        'rank_tables': tables,
        'coverage': coverage,
        'meta': {r['key']: r['value'] for r in conn.execute('SELECT key,value FROM meta')},
    }
    if args.json:
        _print_json(out)
    else:
        print(f"数据库: {out['db']}")
        print(f"表统计: {counts}")
        print('\n一分一段表覆盖:')
        for t in tables:
            print(f"  {t['province']} {t['year']} {config.TRACK_CN[t['track']]:<4} "
                  f"{t['n']:>4} 行  ({t['lo']}~{t['hi']} 分)")
        print('\n各校最低位次覆盖（分年计数）:')
        for c in coverage:
            print(f"  {c['province']} {c['track']:<4} {c['school_rank_by_year']}")
        if out['meta']:
            print('\n元信息:')
            for k, v in out['meta'].items():
                print(f'  {k} = {v}')
    return 0


def cmd_rank(args):
    conn = _open()
    res = convert.score_to_rank_safe(conn, args.province, args.year, args.track, args.score)
    if not res:
        print(f'{args.province} {args.year} {config.TRACK_CN[args.track]} '
              f'一分一段表里没有 {args.score} 分', file=sys.stderr)
        return 2
    if args.json:
        _print_json(res)
    else:
        print(f"{res['province']} {res['year']} {config.TRACK_CN[args.track]}  "
              f"{res['score']} 分 → 位次 {res['rank']}"
              f"  {audit.tag(res['province'], res['year'], res['track'])}")
        if res.get('note'):
            print('  注:', res['note'])
    return 0


def cmd_score(args):
    conn = _open()
    res = convert.rank_to_score(conn, args.province, args.year, args.track, args.rank)
    if not res:
        print(f'位次 {args.rank} 超出 {args.province} {args.year} '
              f'{config.TRACK_CN[args.track]} 一分一段表范围', file=sys.stderr)
        return 2
    if args.json:
        _print_json(res)
    else:
        print(f"{res['province']} {res['year']} {config.TRACK_CN[args.track]}  "
              f"位次 {res['rank']} → 约 {res['score']} 分  "
              f"{audit.tag(res['province'], res['year'], res['track'])}")
    return 0


def cmd_ingest_special(args):
    conn = _open()
    try:
        if not args.all and not args.province:
            print('错误: 要么给 --province，要么给 --all', file=sys.stderr)
            return 2
        combos = ([(p, t) for p in config.PROVINCE_IDS for t in ('physics', 'history')]
                  if args.all else [(args.province, args.track or 'physics')])
        total = {'schools': 0, 'groups': 0, 'majors': 0, 'failed': 0, 'empty': 0}
        for p, t in combos:
            r = ingest_special.ingest(conn, p, t, year=args.year,
                                      workers=args.workers, limit=args.limit,
                                      reload=args.reload)
            for k in total:
                total[k] += r.get(k, 0)
        print('\n合计：', total)
        return 0
    finally:
        conn.close()


def cmd_special_status(args):
    conn = _open()
    try:
        rows = ingest_special.status(conn, args.province)
        if args.json:
            _print_json(rows)
        else:
            print('%-6s %-8s %-6s %6s %8s %10s %10s' %
                  ('省', '科类', '年份', '组数', '院校数', '有位次', '有学费'))
            for r in rows:
                print('%-6s %-8s %-6s %6d %8d %10d %10d' % (
                    r['province'], config.TRACK_CN.get(r['track'], r['track']),
                    r['year'], r['n'], r['schools'], r['with_rank'], r['with_tuition']))
            if not rows:
                print('(还没有分专业数据，先跑 ingest-special)')
        return 0
    finally:
        conn.close()


def cmd_recommend(args):
    conn = _open()
    result = rec_mod.recommend(
        conn, args.province, args.track, score=args.score, rank=args.rank,
        year=args.year, limit=args.limit, name_like=args.name,
        only_985=args.only_985, only_211=args.only_211,
        city=args.city, level=args.level, with_history=not args.no_history,
        score_lo=args.score_lo, score_hi=args.score_hi,
        rank_lo=args.rank_lo, rank_hi=args.rank_hi,
        subject_primary=args.first, subject_resel=args.resel,
        city_list=[c for c in (args.cities or '').split(',') if c])
    if args.json:
        _print_json(result)
        return 0

    if result['range_mode']:
        basis = (f"考生区间 {result['score_lo']}~{result['score_hi']} 分"
                 f"（位次 {result['rank_lo']}~{result['rank_hi']}，中位 {result['rank']}）"
                 f"  ·  {result['province']} {result['track_cn']}  ·  参考 {result['year']} 年")
    else:
        basis = (f"考生位次 {result['rank']}"
                 + (f"（{result['score']} 分）" if result['score'] else '')
                 + f"  ·  {result['province']} {result['track_cn']}  ·  参考 {result['year']} 年")
    print(basis)
    if result.get('subject'):
        s = result['subject']
        print(f"选科: {s['full']}（{s['label']}）  可报专业面 {s['coverage']}  {s['level_cn']}")
        if s.get('warning'):
            print(f"  ⚠ {s['warning']}")
    print(f"判定规则: {result['meta']['band_rule']}")
    print(f"数据基础: {result['meta']['rank_basis']} + {result['meta']['score_basis']}\n")

    for key in ('chong', 'wen', 'bao'):
        items = result[key]
        print(f"── {config.BAND_CN[key]}（{result['counts'][key]} 所）", end='')
        if not items:
            print('  无匹配')
            continue
        print()
        for i, it in enumerate(items, 1):
            print(f"  {i:>2}. {audit.format_item(it)}")
            if it.get('history'):
                hist = ' / '.join(f"{h['year']}:{h['rank']}" for h in it['history'])
                print(f"      {it.get('trend','')}  位次轨迹 {hist}")
        print()
    return 0


def cmd_selftest(args):
    conn = _open()
    fails = []
    ok = []

    def check(name, cond, detail=''):
        (ok if cond else fails).append(f'{name} {detail}'.strip())

    # 1) 分数 -> 位次
    r = convert.score_to_rank(conn, '湖南', 2026, 'physics', 600)
    check('湖南2026物理600分', bool(r) and r['rank'] == 18876, f"得到 {r and r['rank']}")
    r2 = convert.score_to_rank(conn, '广东', 2026, 'physics', 600)
    check('广东2026物理600分', bool(r2) and r2['rank'] == 30891, f"得到 {r2 and r2['rank']}")

    # 2) 位次 -> 分数
    s = convert.rank_to_score(conn, '湖南', 2026, 'physics', 18876)
    check('湖南2026位次18876->分数', bool(s) and s['score'] == 600, f"得到 {s and s['score']}")

    # 3) 跨年不能混用：2025 同一分数位次应不同
    r3 = convert.score_to_rank(conn, '湖南', 2025, 'physics', 600)
    check('湖南2025物理600分', bool(r3) and r3['rank'] != r['rank'] if r else False,
          f"2026={r and r['rank']} 2025={r3 and r3['rank']}")

    # 4) 推荐能出结果，且分档不重叠
    res = rec_mod.recommend(conn, '湖南', 'physics', score=600, limit=5)
    check('湖南推荐出结果', bool(res['chong'] or res['wen'] or res['bao']),
          f"冲{len(res['chong'])} 稳{len(res['wen'])} 保{len(res['bao'])}")
    ids = [it['school_id'] for k in ('chong', 'wen', 'bao') for it in res[k]]
    check('分档不重叠', len(ids) == len(set(ids)), f'{len(ids)} 条')

    # 5) 每条推荐都有来源与位次
    all_items = [it for k in ('chong', 'wen', 'bao') for it in res[k]]
    check('每条都带来源年份位次',
          all(it.get('rank') and it.get('year') and it.get('source') for it in all_items))

    # 6) audit 能抓到编造的数字、放过真实的数字
    ev = rec_mod.evidence_from(res)
    fake = '湖南大学 2026 年最低 687 分，位次 9921'
    sus = audit.scan(fake, ev)
    check('audit 抓到编造数字', len(sus) >= 1, f'抓到 {[s["value"] for s in sus]}')
    real_item = (res['chong'] or res['wen'] or res['bao'])[0]
    real = f"{real_item['school']} 最低 {real_item['score']} 分，位次 {real_item['rank']}"
    sus2 = audit.scan(real, ev)
    check('audit 放过真实数字', len(sus2) == 0, f'误报 {[s["value"] for s in sus2]}')

    # 7) 整百位次（编造常见写法）也要点名
    sus3 = audit.scan('位次大概 15000 左右', ev)
    check('audit 抓到整百位次', any(s['value'] == 15000 for s in sus3),
          f'抓到 {[s["value"] for s in sus3]}')

    # 8) 直接给位次也能推荐
    res2 = rec_mod.recommend(conn, '湖南', 'physics', rank=18876, limit=3)
    check('按位次直接推荐', bool(res2['rank'] == 18876 and
                                 (res2['chong'] or res2['wen'] or res2['bao'])))

    # 9) 未收录省份必须报错，不能静默返回空
    try:
        rec_mod.recommend(conn, '河南', 'physics', score=600)
        check('未收录省份报错', False, '没有报错')
    except ValueError:
        check('未收录省份报错', True)

    # 10) 分数区间 -> 同年位次区间
    conv = convert.score_range_to_rank(conn, '湖南', 2026, 'physics', 585, 605)
    check('湖南2026 585~605 位次区间',
          bool(conv) and conv['rank_lo'] == 16521 and conv['rank_hi'] == 26952,
          f'得到 {conv and (conv["rank_lo"], conv["rank_hi"])}')

    # 11) 区间推荐：三档都有、互不重叠、冲档需考分高于区间上端
    rng = rec_mod.recommend(conn, '湖南', 'physics', score_lo=585, score_hi=605,
                            limit=40, subject_primary='physics',
                            subject_resel=['chem', 'bio'])
    check('区间推荐三档都有',
          bool(rng['chong'] and rng['wen'] and rng['bao']),
          f"冲{len(rng['chong'])} 稳{len(rng['wen'])} 保{len(rng['bao'])}")
    ids2 = [it['school_id'] for k in ('chong', 'wen', 'bao') for it in rng[k]]
    check('区间分档不重叠', len(ids2) == len(set(ids2)), f'{len(ids2)} 条')
    check('冲档需考分高于区间上端',
          all(it['need_score'] >= 605 for it in rng['chong']),
          f"最低 {min((it['need_score'] for it in rng['chong']), default=None)}")
    check('保档需考分低于区间下端',
          all(it['need_score'] <= 585 for it in rng['bao']),
          f"最高 {max((it['need_score'] for it in rng['bao']), default=None)}")
    check('区间模式带位次区间',
          rng['rank_lo'] == 16521 and rng['rank_hi'] == 26952 and rng['range_mode'])
    check('稳档带需考分说明',
          all(it['gap_text'] for it in rng['wen']),
          f"示例 {(rng['wen'][0]['need_score'], rng['wen'][0]['gap_text']) if rng['wen'] else None}")

    # 12) 位次区间入参也能算
    rng2 = rec_mod.recommend(conn, '湖南', 'physics', rank_lo=16521, rank_hi=26952, limit=5)
    check('位次区间入参', rng2['rank_lo'] == 16521 and rng2['rank_hi'] == 26952)

    # 13) 选科规则
    sr = subject_rules.analyze('physics', ['chem', 'bio'])
    check('物化生=专业面最宽', sr['level'] == 'wide' and sr['label'] == '物化生',
          f"{sr['label']} {sr['level_cn']}")
    sr2 = subject_rules.analyze('physics', ['bio', 'pol'])
    check('物生政=收窄且提示缺化学',
          sr2['level'] == 'narrow' and '化学' in sr2['warning'] and sr2['label'] == '物生政',
          f"{sr2['label']}")
    sr3 = subject_rules.analyze('history', ['pol', 'geo'])
    check('史政地=理工农医关闭',
          sr3['level'] == 'half' and len(sr3['closed']) >= 3 and sr3['label'] == '史政地',
          f"{sr3['label']} 关闭 {len(sr3['closed'])} 类")
    sr4 = subject_rules.analyze('physics', ['chem'])
    check('再选没选满 -> 还没定',
          sr4['undecided'] is True and bool(sr4['warning']),
          f"{sr4['label']} undecided={sr4['undecided']}")
    check('选科解析兼容中英文',
          subject_rules.parse_primary('物理类') == 'physics'
          and subject_rules.parse_resel('化学,生物') == ['chem', 'bio']
          and subject_rules.parse_resel('物化生') == ['chem', 'bio'])

    # 14) 提前批（军/警）必须打标，普通院校不能误标
    big = rec_mod.recommend(conn, '湖南', 'physics', score_lo=585, score_hi=605, limit=300)
    big_all = [it for k in ('chong', 'wen', 'bao') for it in big[k]]
    pk = [(it['school'], it['prelim_kind']) for it in big_all if it['prelim']]
    check('军警院校打标', len(pk) >= 3 and all(x[1] in ('军', '警') for x in pk),
          f'{len(pk)} 所，样例 {pk[:3]}')
    check('普通院校不误标',
          not any(it['prelim'] for it in big_all
                  if it['school'] in ('吉林大学', '中国政法大学', '重庆大学', '深圳大学')))
    check('军校判军、公安判警',
          all(k == '军' for n, k in pk if '解放军' in n or n.startswith('武警'))
          and all(k == '警' for n, k in pk if ('警察' in n or '公安大学' in n)),
          f'军 {sum(1 for _, k in pk if k == "军")} / 警 {sum(1 for _, k in pk if k == "警")}')

    # 15) 方向候选库
    d1 = major_dirs.pick('physics', ['chem', 'bio'], ['job', 'city'], [], limit=6)
    check('方向候选有结果', len(d1) >= 3, f'{len(d1)} 个: {[d["key"] for d in d1]}')
    check('care 影响排序', bool(d1) and d1[0]['score'] >= d1[-1]['score'],
          f"首位 {d1[0]['name']} score={d1[0]['score']}" if d1 else '空')
    d2 = major_dirs.pick('physics', ['bio', 'pol'], ['job'], [], limit=8)
    check('无化学剔除要求化学的方向', all(not d['need_chem'] for d in d2), f'{len(d2)} 个')
    d3 = major_dirs.pick('history', ['pol', 'geo'], ['gov'], [], limit=8)
    check('历史类只给文管法方向',
          all(d['primary'] in ('any', 'history') for d in d3) and len(d3) >= 3,
          f'{len(d3)} 个: {[d["key"] for d in d3]}')
    d4 = major_dirs.pick('physics', ['chem', 'bio'], ['job'], ['土木', '化工'], limit=8)
    check('排除项生效',
          not any(('土木' in d['name']) or ('化工' in d['name']) for d in d4),
          f'{len(d4)} 个')
    d5 = major_dirs.pick('physics', [], ['job'], [], limit=8)
    check('再选没选满时保留要求化学的方向并标记',
          any(d['need_chem_if_undecided'] for d in d5),
          f'{sum(1 for d in d5 if d["need_chem_if_undecided"])} 个被标记')
    check('方向库文本可渲染', '代表专业' in major_dirs.brief(d1))

    # 16) 近三年分档（P7）与办学性质（P8）
    zoned = [it for it in big_all if it.get('zone_years')]
    check('每条带近三年分档', bool(zoned) and len(zoned) == len(big_all),
          f'{len(zoned)}/{len(big_all)}')
    check('近三年次数之和 = 有数据年数',
          all(sum(it['zone_counts'].values()) == it['zone_years'] for it in zoned))
    check('当年档位 = 近三年最后一年的档位',
          all(it['hist_zones'][-1]['zone'] == it['zone'] for it in zoned),
          f"示例 {zoned[0]['school']} {zoned[0]['zone_text']}" if zoned else '')
    bs = [it for it in zoned if it['big_small']]
    check('大小年判定 = 三年内既进冲又进保',
          all(it['zone_counts'].get('chong') and it['zone_counts'].get('bao') for it in bs),
          f'{len(bs)} 所')
    ratio_vol = len([it for it in zoned if it['volatile']]) / max(1, len(zoned))
    check('近三年跨档比例落在合理区间(10%~70%)', 0.10 <= ratio_vol <= 0.70,
          f'{100.0 * ratio_vol:.0f}%')
    coop = [it for it in big_all if '合作' in (it.get('nature_group') or '')]
    check('合作办学 = 高学费，且能识别',
          bool(coop) and all(it['expensive'] for it in coop),
          f'{len(coop)} 所: {[it["school"] for it in coop][:3]}')
    pub = [it for it in big_all if it.get('nature_group') == '公办']
    check('公办校不误标高学费',
          bool(pub) and not any(it['expensive'] for it in pub),
          f'公办 {len(pub)} 所')
    one = rec_mod.recommend(conn, '湖南', 'physics', score=600, limit=5)
    one_all = [it for k in ('chong', 'wen', 'bao') for it in one[k]]
    check('单点（非区间）模式也有近三年分档',
          bool(one_all) and all(it.get('zone_years', 0) >= 1 for it in one_all),
          f'{len(one_all)} 条')

    # 17) 专业组（P6）。数据是分批灌的，所以这里只验证「有数据时的行为」，不要求全量。
    from . import special as special_mod
    req1 = special_mod.parse_require('首选物理，再选化学、生物(2科必选)')
    req2 = special_mod.parse_require('首选物理，再选不限')
    check('选科要求解析：物+化+生',
          req1['primary'] == 'physics' and req1['groups'] == [['chem', 'bio']]
          and special_mod.require_text('', req1) == '物+化+生',
          special_mod.require_text('', req1))
    check('选科要求解析：不限', req2['unlimited'] is True)
    check('可报性：物化生能报 / 物生政不能报 / 史政地不能报',
          special_mod.reportable(req1, 'physics', ['chem', 'bio'])
          and not special_mod.reportable(req1, 'physics', ['bio', 'pol'])
          and not special_mod.reportable(req1, 'history', ['pol', 'geo']))
    check('再选没选满按最宽口径放行',
          special_mod.reportable(req1, 'physics', []) is True)
    g_row = conn.execute(
        'SELECT school_id FROM special_group WHERE province=? AND track=? LIMIT 1',
        ('湖南', 'physics')).fetchone()
    if g_row:
        gs = special_mod.school_groups(
            conn, g_row['school_id'], '湖南', 'physics', 'physics', ['chem', 'bio'],
            range_mode=True, r_lo=16521, r_hi=26952, r_mid=21736,
            score_lo=585, score_hi=605, max_majors=3)
        check('专业组能查出来', bool(gs), f'{len(gs)} 组')
        check('专业组带学费或计划',
              any(g['tuition'] for g in gs) or any(g['planNum'] for g in gs))
        check('可报的排在前面',
              all(gs[i]['ok'] or not gs[i - 1]['ok'] for i in range(1, len(gs))))
        check('组线位次换算到参考年',
              all((g['refRank'] is None) or g['refRank'] > 0 for g in gs)
              and any(g['refRank'] for g in gs))
        summ = special_mod.summarize(
            conn, [g_row['school_id']], '湖南', 'physics', 'physics', ['bio', 'pol'])
        s = summ.get(g_row['school_id']) or {}
        check('摘要 ok + blocked = total',
              s.get('total', 0) >= 1 and s['ok'] + s['blocked'] == s['total'],
              f"可报 {s.get('ok')} / 共 {s.get('total')}")
        # 推荐结果里要带上专业组摘要
        withg = [it for it in big_all if it.get('groups')]
        check('推荐结果带专业组摘要', bool(withg),
              f'{len(withg)}/{len(big_all)} 所有数据')
        check('专业组摘要字段自洽',
              all(it['groups']['ok'] + it['groups']['blocked'] == it['groups']['total']
                  for it in withg))
    else:
        print('  (跳过专业组查询检查：库里还没有分专业数据)')

    print(f'\n自检: {len(ok)} 通过, {len(fails)} 失败')
    for x in ok:
        print('  ✅', x)
    for x in fails:
        print('  ❌', x)
    return 0 if not fails else 1


# ---------------------------------------------------------------- 参数

def build_parser():
    p = argparse.ArgumentParser(prog='python -m engine', description='雪峰 Agent 位次引擎')
    sub = p.add_subparsers(dest='cmd', required=True)

    def add_db_common(sp):
        pass

    sp = sub.add_parser('init', help='初始化数据库（一分一段 + 校线 + 换算）')
    sp.add_argument('--no-live', action='store_true', help='跳过实时校线（只用离线索引）')
    sp.add_argument('--workers', type=int, default=8)
    sp.add_argument('--limit', type=int, default=None, help='仅处理前 N 所学校（调试用）')
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser('fetch-scores', help='拉取实时校线')
    sp.add_argument('--years', default=str(config.REFERENCE_YEAR))
    sp.add_argument('--workers', type=int, default=8)
    sp.add_argument('--limit', type=int, default=None)
    sp.set_defaults(func=cmd_fetch_scores)

    sp = sub.add_parser('build-rank', help='重新换算各校最低位次')
    sp.set_defaults(func=cmd_build_rank)

    sp = sub.add_parser('status', help='查看数据覆盖情况')
    sp.add_argument('--json', action='store_true')
    sp.set_defaults(func=cmd_status)

    def add_prov_track(sp):
        sp.add_argument('--province', required=True, choices=list(config.PROVINCE_IDS))
        sp.add_argument('--track', default='physics', choices=list(config.TRACK_CN)[:2])

    sp = sub.add_parser('rank', help='分数 -> 位次')
    add_prov_track(sp)
    sp.add_argument('--year', type=int, required=True)
    sp.add_argument('--score', type=int, required=True)
    sp.add_argument('--json', action='store_true')
    sp.set_defaults(func=cmd_rank)

    sp = sub.add_parser('score', help='位次 -> 分数')
    add_prov_track(sp)
    sp.add_argument('--year', type=int, required=True)
    sp.add_argument('--rank', type=int, required=True)
    sp.add_argument('--json', action='store_true')
    sp.set_defaults(func=cmd_score)

    sp = sub.add_parser('recommend', help='冲稳保推荐（按位次）')
    add_prov_track(sp)
    sp.add_argument('--score', type=int, default=None)
    sp.add_argument('--rank', type=int, default=None)
    sp.add_argument('--score-lo', type=int, default=None, help='分数区间下端')
    sp.add_argument('--score-hi', type=int, default=None, help='分数区间上端')
    sp.add_argument('--rank-lo', type=int, default=None, help='位次区间上端（数字更小）')
    sp.add_argument('--rank-hi', type=int, default=None, help='位次区间下端（数字更大）')
    sp.add_argument('--first', default=None, choices=['physics', 'history'],
                    help='首选科目')
    sp.add_argument('--resel', default=None, help='再选科目，如 chem,bio')
    sp.add_argument('--cities', default=None, help='城市多选，逗号分隔')
    sp.add_argument('--year', type=int, default=None)
    sp.add_argument('--limit', type=int, default=config.DEFAULT_LIMIT)
    sp.add_argument('--name', default=None, help='按校名过滤')
    sp.add_argument('--city', default=None)
    sp.add_argument('--level', default=None)
    sp.add_argument('--only-985', action='store_true')
    sp.add_argument('--only-211', action='store_true')
    sp.add_argument('--no-history', action='store_true')
    sp.add_argument('--json', action='store_true')
    sp.set_defaults(func=cmd_recommend)

    sp = sub.add_parser('selftest', help='运行内置自检')
    sp.set_defaults(func=cmd_selftest)

    sp = sub.add_parser('ingest-special',
                        help='抓分专业录取线 + 招生计划/学费（专业组级）')
    sp.add_argument('--province', choices=list(config.PROVINCE_IDS), default=None)
    sp.add_argument('--track', choices=['physics', 'history'], default=None)
    sp.add_argument('--year', type=int, default=None,
                    help=f'默认 {config.SPECIAL_YEAR}（分专业数据完整的年份）')
    sp.add_argument('--workers', type=int, default=10)
    sp.add_argument('--limit', type=int, default=None, help='只抓前 N 所（调试）')
    sp.add_argument('--reload', action='store_true', help='已入库的也重抓')
    sp.add_argument('--all', action='store_true', help='湖南+广东 × 物理+历史 全抓')
    sp.set_defaults(func=cmd_ingest_special)

    sp = sub.add_parser('special-status', help='分专业数据入库情况')
    sp.add_argument('--province', default=None)
    sp.add_argument('--json', action='store_true')
    sp.set_defaults(func=cmd_special_status)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError, convert.NoRankTable) as e:
        print(f'错误: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
