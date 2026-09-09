"""一次性脚本:只扫 2024Q4(最新已披露季度),全部成分股。
目的:快速让国家队的最新持仓 Top 榜丰富起来。
运行:.venv/bin/python scripts/nt_backfill_2024q4.py
"""
import sys, datetime as dt
sys.path.insert(0, '.')
import akshare as ak
from src.domain.market.sync.providers.akshare_provider import AkshareProvider
from src.domain.market.sync.providers.national_team_config import (
    match_holder_category, get_backfill_scope,
)
from src.infra.database.market.national_team_holding import (
    create_national_team_repository,
)

Q = '20241231'
RD = dt.date(2024, 12, 31)

# 1. 取成分股
scope = get_backfill_scope()
syms = {}  # symbol -> (name, sector)
for item in scope:
    try:
        if 'index_code' in item:
            df = ak.index_stock_cons_csindex(symbol=item['index_code'])
            for _, r in df.iterrows():
                c = str(r.get('成分券代码') or '').strip()
                n = str(r.get('成分券名称') or '').strip()
                if c:
                    syms.setdefault(c, (n, ''))
        elif 'sw_sector_code' in item:
            sn = item.get('sw_sector_name', '')
            got = False
            for fn in (lambda: ak.index_component_sw(symbol=item['sw_sector_code']),
                       lambda: ak.stock_board_industry_cons_em(symbol=sn)):
                try:
                    df = fn()
                    if df is None or len(df) == 0:
                        continue
                    cc = '代码' if '代码' in df.columns else '证券代码'
                    nn = '名称' if '名称' in df.columns else '证券名称'
                    for _, r in df.iterrows():
                        c = str(r.get(cc) or '').strip()
                        n = str(r.get(nn) or '').strip()
                        if c:
                            syms.setdefault(c, (n, sn))
                    got = True
                    break
                except Exception:
                    continue
            if not got:
                print(f'[warn] 无法获取行业成分 {item}')
    except Exception as e:
        print(f'[warn] scope err {item}: {e}')

print(f'[info] 待扫 {len(syms)} 股 @ {Q}')

provider = AkshareProvider()
repo = create_national_team_repository()
calls = matched = written = 0
for i, (sym, (name, sector)) in enumerate(syms.items()):
    try:
        repo.upsert_sector(sym, sector)
        holders = provider.fetch_top10_float_holders(sym, Q)
        rows = []
        for h in holders:
            cat = match_holder_category(h['holder_name'])
            if not cat:
                continue
            rows.append({
                'report_date': RD,
                'holder_name': h['holder_name'],
                'holder_category': cat,
                'symbol': sym,
                'company_name': name,
                'hold_shares': int(h.get('hold_shares') or 0),
                'hold_value': float(h.get('hold_value') or 0),
                'pct_of_float': float(h.get('pct_of_float') or 0),
                'ranking': int(h.get('ranking') or 0),
            })
        if rows:
            repo.bulk_upsert(rows)
            written += len(rows)
            matched += 1
        calls += 1
        if calls % 30 == 0:
            print(f'[info] 进度:{calls}/{len(syms)} 调用, {matched} 股命中, {written} 条入库')
    except Exception as e:
        print(f'[warn] 失败 {sym}@{Q}: {e}')

print(f'[done] 完成:{calls} 调用, {matched} 股命中, {written} 条入库 @ {Q}')
