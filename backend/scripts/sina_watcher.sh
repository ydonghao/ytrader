#!/bin/bash
# Sina 分钟线回补自动恢复脚本
# 由 cron 调用，每5分钟检测 Sina 是否恢复
# 恢复后自动启动回补进程（单 worker + 3s delay 避免再次触发限流）

set -e

BACKEND="/home/yuandonghao/sidejob/sources/trader/ytrader/backend"
cd "$BACKEND"
export PYTHONPATH="$BACKEND/src"

LOG="logs/sina_watcher.log"
LOCK="logs/sina_watcher.lock"
PROGRESS_FILE="logs/.backfill_progress.lock"

# 防止并发：锁文件 5 分钟过期
if [ -f "$LOCK" ]; then
    LOCK_AGE=$(($(date +%s) - $(stat -c %Y "$LOCK" 2>/dev/null || echo 0)))
    if [ "$LOCK_AGE" -lt 300 ]; then
        echo "[$(date '+%H:%M')] 锁未过期，退出" >> "$LOG"
        exit 0
    fi
fi
touch "$LOCK"

echo "[$(date '+%Y-%m-%d %H:%M')] 检测 Sina API..." >> "$LOG"

# 测试 Sina 60m API
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time 8 \
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh600000&scale=60&ma=no&datalen=1")

if [ "$HTTP_STATUS" = "200" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M')] ✅ Sina 恢复 (status=200)！" >> "$LOG"

    # 60m
    if ! pgrep -f "backfill_all.*a_60m" > /dev/null 2>&1; then
        echo "[$(date '+%H:%M')] 启动 60m 回补..." >> "$LOG"
        PYTHONPATH="$BACKEND/src" \
            .venv/bin/python scripts/backfill_all.py \
            --targets a_60m --providers sina --workers 1 --delay 3.0 \
            >> logs/backfill_a60m_sina.log 2>&1 &
        echo "[$(date '+%H:%M')] 60m PID=$!" >> "$LOG"
    fi

    # 30m（60m 开始 5 分钟后再启动）
    if ! pgrep -f "backfill_all.*a_30m" > /dev/null 2>&1; then
        echo "[$(date '+%H:%M')] 启动 30m 回补..." >> "$LOG"
        PYTHONPATH="$BACKEND/src" \
            .venv/bin/python scripts/backfill_all.py \
            --targets a_30m --providers sina --workers 1 --delay 3.0 \
            >> logs/backfill_a30m_sina.log 2>&1 &
        echo "[$(date '+%H:%M')] 30m PID=$!" >> "$LOG"
    fi

    # 5m（30m 开始 5 分钟后再启动）
    if ! pgrep -f "backfill_all.*a_5m" > /dev/null 2>&1; then
        echo "[$(date '+%H:%M')] 启动 5m 回补..." >> "$LOG"
        PYTHONPATH="$BACKEND/src" \
            .venv/bin/python scripts/backfill_all.py \
            --targets a_5m --providers sina --workers 1 --delay 3.0 \
            >> logs/backfill_a5m_sina.log 2>&1 &
        echo "[$(date '+%H:%M')] 5m PID=$!" >> "$LOG"
    fi
else
    echo "[$(date '+%Y-%m-%d %H:%M')] ❌ Sina 仍被限流 (status=$HTTP_STATUS)" >> "$LOG"
fi

rm -f "$LOCK"
