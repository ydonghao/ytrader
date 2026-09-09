"""
Feishu Notification Service
===========================
Sends alert notifications via Feishu Open Platform HTTP API.
No external SDK dependency — uses stdlib urllib + json.

Environment variables:
  FEISHU_APP_ID       — Bot App ID (e.g. cli_a418eb6a34a9900b)
  FEISHU_APP_SECRET   — Bot App Secret
"""

import json
import logging
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# ── Token cache ────────────────────────────────────────────────────────────────

_token_cache: dict = {}  # {"access_token": "...", "expires_at": float}


def _get_tenant_token() -> str | None:
    """Get a fresh tenant access token, cached for ~110 minutes."""
    now = time.time()
    cached = _token_cache.get("access_token")
    expires_at = _token_cache.get("expires_at", 0)

    if cached and now < expires_at - 60:
        return cached

    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        log.warning("[Feishu] FEISHU_APP_ID / FEISHU_APP_SECRET not set")
        return None

    payload = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("code") != 0:
            log.error("[Feishu] token request failed: %s", data.get("msg"))
            return None
        token = data["tenant_access_token"]
        # Feishu tokens expire in 2 hours; cache for 110 minutes
        _token_cache["access_token"] = token
        _token_cache["expires_at"] = now + 110 * 60
        return token
    except Exception as e:
        log.error("[Feishu] failed to get tenant token: %s", e)
        return None


def _send_message(open_id: str, card_content: dict) -> bool:
    """Send an interactive card message to a user by open_id."""
    token = _get_tenant_token()
    if not token:
        return False

    payload = json.dumps({
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card_content),
    }).encode()

    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("code") == 0:
            log.info("[Feishu] message sent to %s", open_id)
            return True
        log.error("[Feishu] send failed: code=%s msg=%s", result.get("code"), result.get("msg"))
        return False
    except Exception as e:
        log.error("[Feishu] send error: %s", e)
        return False


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_user_open_id() -> str | None:
    """Read feishu_user_open_id from app_settings table."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from src.infra.database.sql_engine.dsn import get_dsn
    try:
        conn = psycopg2.connect(get_dsn())
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT value FROM app_settings WHERE name = 'feishu_user_open_id' LIMIT 1"
            )
            row = cur.fetchone()
        conn.close()
        return row["value"] if row else None
    except Exception as e:
        log.error("[Feishu] failed to read feishu_user_open_id: %s", e)
        return None


def _ensure_settings_table():
    """Create app_settings table if not exists."""
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn
    try:
        conn = psycopg2.connect(get_dsn())
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    name TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        conn.commit()
        conn.close()
    except Exception as e:
        log.error("[Feishu] failed to create app_settings: %s", e)


def set_user_open_id(open_id: str) -> bool:
    """Save feishu_user_open_id to app_settings."""
    _ensure_settings_table()
    import psycopg2
    from src.infra.database.sql_engine.dsn import get_dsn
    try:
        conn = psycopg2.connect(get_dsn())
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO app_settings (name, value, updated_at)
                VALUES ('feishu_user_open_id', %s, NOW())
                ON CONFLICT (name) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """, (open_id,))
        conn.commit()
        conn.close()
        log.info("[Feishu] saved feishu_user_open_id = %s", open_id)
        return True
    except Exception as e:
        log.error("[Feishu] failed to save feishu_user_open_id: %s", e)
        return False


# ── Card builder ───────────────────────────────────────────────────────────────

def _build_alert_card(
    symbol: str,
    direction: str,
    target_price: float,
    current_price: float,
    message: str | None,
    triggered_at: str,
) -> dict:
    """Build a Feishu interactive card for a triggered price alert."""
    direction_emoji = "🔴" if direction == "above" else "🔵"
    direction_text = "突破上限" if direction == "above" else "跌破下限"
    color = "red" if direction == "above" else "blue"

    header_title = f"{direction_emoji} 价格告警 — {symbol.upper()}"

    fields = [
        {
            "is_short": True,
            "text": {
                "tag": "lark_md",
                "content": f"**方向**\n{direction_text}",
            },
        },
        {
            "is_short": True,
            "text": {
                "tag": "lark_md",
                "content": f"**目标价格**\n¥{target_price:.2f}",
            },
        },
        {
            "is_short": True,
            "text": {
                "tag": "lark_md",
                "content": f"**当前价格**\n¥{current_price:.2f}",
            },
        },
        {
            "is_short": True,
            "text": {
                "tag": "lark_md",
                "content": f"**触发时间**\n{triggered_at}",
            },
        },
    ]

    elements = [{"tag": "div", "fields": fields}]

    if message:
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**备注**: {message}",
            },
        })

    elements.extend([
        {"tag": "hr"},
        {"tag": "note", "elements": [{"tag": "plain_text", "content": "YTrader 量化交易平台"}]},
    ])

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": header_title},
            "template": color,
        },
        "elements": elements,
    }


# ── Generic Card Builder ──────────────────────────────────────────────────────

def _build_notification_card(title: str, content: str, color: str = "blue") -> dict:
    """Build a simple Feishu card with title + markdown content."""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color,
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": content,
                },
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": "YTrader 量化交易平台"},
                ],
            },
        ],
    }


# ── Public API ────────────────────────────────────────────────────────────────

def send_notification(title: str, content: str, color: str = "blue") -> bool:
    """
    Send a generic Feishu card notification.
    Reuses tenant token + user open_id infrastructure.
    """
    open_id = _get_user_open_id()
    if not open_id:
        log.warning("[Feishu] feishu_user_open_id not configured — skipping")
        return False

    card = _build_notification_card(title, content, color=color)
    return _send_message(open_id, card)


def send_alert_notification(
    symbol: str,
    direction: str,
    target_price: float,
    current_price: float,
    message: str | None = None,
) -> bool:
    """
    Send a Feishu card notification for a triggered price alert.
    Reads recipient from app_settings (feishu_user_open_id).
    """
    open_id = _get_user_open_id()
    if not open_id:
        log.warning("[Feishu] feishu_user_open_id not configured — skipping")
        return False

    triggered_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    card = _build_alert_card(
        symbol=symbol,
        direction=direction,
        target_price=target_price,
        current_price=current_price,
        message=message,
        triggered_at=triggered_at,
    )
    return _send_message(open_id, card)
