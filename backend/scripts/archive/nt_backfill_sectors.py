"""一次性脚本:回填 national_team_symbol_sector(申万一级行业)。

数据源:akshare sw_index_first_info(31 个申万一级行业) + index_component_sw(成分股)。
带重试 + 进度日志。网络不稳可多次运行(幂等覆盖)。

运行:.venv/bin/python scripts/nt_backfill_sectors.py
"""
import sys, time
sys.path.insert(0, '.')
import akshare as ak
from src.infra.database.market.national_team_holding import (
    create_national_team_repository,
)


def _retry(fn, attempts=3, delay=2):
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            if i == attempts - 1:
                raise
            print(f'  重试 {i+1}/{attempts}: {repr(e)[:80]}')
            time.sleep(delay)
    return None


def main():
    repo = create_national_team_repository()
    # 1. 申万一级行业列表
    print('拉取申万一级行业列表...')
    df = _retry(lambda: ak.sw_index_first_info())
    if df is None or len(df) == 0:
        print('无法获取行业列表,退出')
        return
    # 行业代码去 .SI 后缀(成分接口要纯数字),名称
    boards = [(str(c).replace('.SI', ''), str(n)) for c, n in zip(df['行业代码'], df['行业名称'])]
    print(f'共 {len(boards)} 个申万一级行业')

    ok = fail = total_written = 0
    for i, (code, name) in enumerate(boards):
        try:
            cdf = _retry(lambda c=code: ak.index_component_sw(symbol=c))
            if cdf is None or len(cdf) == 0:
                fail += 1
                continue
            # 列:证券代码 / 证券名称
            code_col = '证券代码' if '证券代码' in cdf.columns else '代码'
            for _, r in cdf.iterrows():
                sym = str(r.get(code_col) or '').strip()
                if sym:
                    repo.upsert_sector(sym, name)
                    total_written += 1
            ok += 1
            if (i + 1) % 5 == 0:
                print(f'进度: {i+1}/{len(boards)} 行业, 成功 {ok} 失败 {fail}, 累计入库 {total_written}')
        except Exception as e:
            fail += 1
            print(f'  行业 {name}({code}) 失败: {repr(e)[:80]}')
    print(f'=== 完成: {ok} 行业成功, {fail} 失败, 共 {total_written} 条 symbol→sector ===')

    # 报告国家队持仓的行业覆盖率
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn
    conn = psycopg2.connect(get_dsn())
    with conn.cursor() as cur:
        cur.execute('SELECT count(*) FROM national_team_symbol_sector')
        n_sec = cur.fetchone()[0]
        cur.execute('''SELECT count(DISTINCT h.symbol)
            FROM national_team_holding h LEFT JOIN national_team_symbol_sector s ON h.symbol=s.symbol
            WHERE s.symbol IS NULL''')
        missing = cur.fetchone()[0]
    conn.close()
    print(f'national_team_symbol_sector 现有 {n_sec} 只; 国家队持仓中缺行业的: {missing} 只')


if __name__ == '__main__':
    main()
