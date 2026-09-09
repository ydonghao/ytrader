"""验证 FredProvider 的 5 个 FRED 序列号是否有效，并打印最新数据日期。

用法：
  export FRED_API_KEY=你的key
  python scripts/verify_fred_series.py
"""
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from src.domain.market.sync.providers.fred_provider import FredProvider


def main():
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        print("⚠️  未设置 FRED_API_KEY 环境变量")
        print("   export FRED_API_KEY=你的key 后重试")
        sys.exit(1)

    print(f"FRED_API_KEY: {key[:4]}...{key[-4:]}（长度 {len(key)}）\n")
    p = FredProvider()
    all_ok = True
    for code, (sid, transform, freq, unit) in FredProvider._MACRO_SERIES.items():
        rows = p.fetch_macro_series(code)
        if not rows:
            all_ok = False
            print(f"❌ {code:14s} ({sid:9s}, transform={transform}) → 无数据")
        else:
            latest_date = rows[-1][0]
            latest_val = rows[-1][1]
            print(f"✅ {code:14s} ({sid:9s}, transform={str(transform):5s}) → "
                  f"{len(rows)} 行，最新 {latest_date} = {latest_val}{unit}")

    print()
    if all_ok:
        print("🎉 全部 5 个序列有效，数据正常")
    else:
        print("⚠️  有序列无效，请检查上面的 ❌ 项（最可能是 NPMI）")
        print("   若 NPMI 失败，可访问 https://fred.stlouisfed.org/searchresults/?st=ism%20pmi 查正确序列号")


if __name__ == "__main__":
    main()
