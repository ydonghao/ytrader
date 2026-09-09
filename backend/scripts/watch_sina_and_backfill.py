#!/usr/bin/env python3
"""
监控 Sina K线 API 是否恢复，恢复后自动启动回补。
每个周期单独一个进程，避免全部同时跑耗尽配额。
"""
import os, sys, time, signal
from pathlib import Path

BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND / "src"))

import requests

INTERVALS = ["60m", "30m", "5m"]
TEST_SYMBOL = "sh600000"
LOG_DIR = BACKEND / "logs"

def test_sina(scale="60"):
    """测试 Sina API 是否可用（status 200 且有数据）"""
    try:
        r = requests.get(
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
            params={"symbol": TEST_SYMBOL, "scale": scale, "ma": "no", "datalen": "3"},
            timeout=10
        )
        if r.status_code == 200 and len(r.text) > 20 and "[" in r.text:
            return True, r.text[:100]
        return False, f"status={r.status_code} len={len(r.text)}"
    except Exception as e:
        return False, str(e)[:60]

def is_process_running(name):
    """检查同名进程是否在跑"""
    import subprocess
    r = subprocess.run(["pgrep", "-f", name], capture_output=True)
    return r.returncode == 0

def start_backfill(interval, workers=1, delay=3.0):
    log_file = LOG_DIR / f"backfill_a{interval}_auto.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND / "src")
    import subprocess
    proc = subprocess.Popen(
        [str(BACKEND / ".venv/bin/python"),
         str(BACKEND / "scripts/backfill_all.py"),
         "--targets", f"a_{interval}",
         "--providers", "sina",
         "--workers", str(workers),
         "--delay", str(delay)],
        stdout=open(log_file, "w"),
        stderr=subprocess.STDOUT,
        env=env
    )
    return proc.pid

def get_scale(interval):
    return {"60m": "60", "30m": "30", "15m": "15", "5m": "5", "1m": "1"}.get(interval, "60")

print(f"[{time.strftime('%Y-%m-%d %H:%M')}] Sina Watcher 启动")
print(f"监控周期: {INTERVALS}")

while True:
    for interval in INTERVALS:
        scale = get_scale(interval)
        ok, info = test_sina(scale)
        status = "✅ 可用" if ok else f"❌ {info}"
        print(f"[{time.strftime('%H:%M')}] {interval} (scale={scale}): {status}")
        
        if ok and not is_process_running(f"a_{interval}"):
            print(f">>> {interval} 恢复！启动回补...")
            pid = start_backfill(interval)
            print(f">>> PID={pid}")
            # 只跑一个周期，然后休息，避免多周期同时跑
            print(f">>> 等待 {interval} 运行中，休息 60秒...")
            time.sleep(60)
    
    print(f"[{time.strftime('%H:%M')}] 全部周期检查完毕，5分钟后再测...")
    time.sleep(300)
