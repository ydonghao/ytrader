"""将 config.yaml 中的 RSS 源迁移到 Miniflux。

创建 4 个 Miniflux 分类 (finance, future_tech, hotlist, cctv_news)，
订阅所有 RSS feed，并写回 category IDs 和 CCTV channel 映射到 config.yaml。

幂等设计：已存在的分类和 feed 会跳过。

Usage:
    cd backend
    python scripts/migrate_feeds_to_miniflux.py
"""

import sys
import os
import yaml
import requests
from pathlib import Path

# 确保可以 import 项目模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CONFIG_PATH = Path(__file__).resolve().parent.parent / "conf" / "config.yaml"

# Miniflux 配置（从当前 config 读取，失败则用默认值）
MINIFLUX_BASE = "http://localhost:8380"
MINIFLUX_USER = "admin"
MINIFLUX_PASS = "admin123"

# 要创建的分类名（对应系统 category）
CATEGORY_NAMES = ["finance", "future_tech", "hotlist", "cctv_news"]


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(conf: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(conf, f, default_flow_style=False,
                  allow_unicode=True, sort_keys=False)


def get_miniflux_auth(conf: dict) -> tuple[str, str, str]:
    """从 config 读取 Miniflux 连接信息。"""
    mf = (
        conf.get("intel", {})
        .get("api", {})
        .get("miniflux", {})
    )
    base = mf.get("base_url", MINIFLUX_BASE)
    user = mf.get("username", MINIFLUX_USER)
    pwd = mf.get("password", MINIFLUX_PASS)
    return base, user, pwd


def get_existing_categories(base: str, auth: tuple) -> dict[str, int]:
    """获取已有的 Miniflux 分类 {name: id}。"""
    try:
        resp = requests.get(f"{base}/v1/categories", auth=auth, timeout=10)
        resp.raise_for_status()
        return {c["title"]: c["id"] for c in resp.json()}
    except Exception as e:
        print(f"[ERROR] 获取分类失败: {e}")
        return {}


def create_category(base: str, auth: tuple, name: str) -> int | None:
    """创建 Miniflux 分类，返回 ID。"""
    try:
        resp = requests.post(
            f"{base}/v1/categories",
            json={"title": name},
            auth=auth,
            timeout=10,
        )
        if resp.status_code == 201:
            cat_id = resp.json()["id"]
            print(f"  [CREATE] 分类 '{name}' → id={cat_id}", flush=True)
            return cat_id
        elif resp.status_code in (400, 409):
            print(f"  [SKIP] 分类 '{name}' 已存在", flush=True)
            return None
        else:
            print(f"  [ERROR] 创建分类 '{name}' 失败: {resp.status_code} {resp.text}")
            return None
    except Exception as e:
        print(f"  [ERROR] 创建分类 '{name}' 异常: {e}")
        return None


def ensure_categories(base: str, auth: tuple) -> dict[str, int]:
    """确保所有分类存在，返回 {name: id} 映射。"""
    existing = get_existing_categories(base, auth)
    print(f"\n[INFO] 已有分类: {existing}", flush=True)

    result = {}
    for name in CATEGORY_NAMES:
        if name in existing:
            result[name] = existing[name]
            print(f"  [OK] 分类 '{name}' 已存在, id={existing[name]}")
        else:
            cat_id = create_category(base, auth, name)
            if cat_id:
                result[name] = cat_id
            else:
                # 创建失败后再查一次（可能并发创建）
                existing2 = get_existing_categories(base, auth)
                if name in existing2:
                    result[name] = existing2[name]
                else:
                    print(f"  [FATAL] 无法创建分类 '{name}'，跳过")
    return result


def get_existing_feeds(base: str, auth: tuple) -> set[str]:
    """获取已有的 feed URL 集合。"""
    try:
        resp = requests.get(f"{base}/v1/feeds", auth=auth, timeout=10)
        resp.raise_for_status()
        return {f["feed_url"] for f in resp.json()}
    except Exception:
        return set()


def subscribe_feed(
    base: str, auth: tuple, feed_url: str,
    category_id: int, name: str,
) -> bool:
    """订阅一个 feed 到指定分类。"""
    try:
        resp = requests.post(
            f"{base}/v1/feeds",
            json={
                "feed_url": feed_url,
                "category_id": category_id,
                "disabled": False,
            },
            auth=auth,
            timeout=15,
        )
        if resp.status_code == 201:
            feed_id = resp.json().get("id", "?")
            print(f"    [CREATE] '{name}' ({feed_url}) → feed_id={feed_id}",
                  flush=True)
            return True
        elif resp.status_code == 409:
            print(f"    [SKIP] '{name}' 已订阅", flush=True)
            return True
        else:
            print(f"    [WARN] '{name}' 订阅失败: {resp.status_code} "
                  f"{resp.text[:100]}", flush=True)
            return False
    except requests.exceptions.Timeout:
        print(f"    [WARN] '{name}' 订阅超时", flush=True)
        return False
    except Exception as e:
        print(f"    [WARN] '{name}' 订阅异常: {e}", flush=True)
        return False


def migrate_feeds(
    conf: dict, base: str, auth: tuple,
    category_map: dict[str, int],
) -> dict[str, str]:
    """迁移 config.yaml 中的 RSS feeds 到 Miniflux。返回 cctv_channel_map。"""
    rss_conf = conf.get("intel", {}).get("rss", {})
    if not rss_conf:
        print("\n[WARN] config.yaml 中没有 intel.rss 配置，跳过迁移")
        return {}

    existing_feeds = get_existing_feeds(base, auth)
    cctv_channel_map: dict[str, str] = {}
    total_created = 0
    total_skipped = 0

    for cat_name, feeds in rss_conf.items():
        cat_id = category_map.get(cat_name)
        if not cat_id:
            print(f"\n[SKIP] 分类 '{cat_name}' 没有对应的 Miniflux category_id")
            continue

        print(f"\n[INFO] 迁移分类 '{cat_name}' (category_id={cat_id}):")
        if not isinstance(feeds, list):
            continue

        for feed in feeds:
            url = feed.get("url", "")
            name = feed.get("name", url)
            if not url:
                continue

            if url in existing_feeds:
                print(f"    [SKIP] '{name}' 已订阅")
                total_skipped += 1
            else:
                ok = subscribe_feed(base, auth, url, cat_id, name)
                if ok:
                    total_created += 1
                else:
                    total_skipped += 1

            # 构建 CCTV channel 映射
            if cat_name == "cctv_news" and feed.get("channel"):
                cctv_channel_map[name] = feed["channel"]

    print(f"\n[SUMMARY] 新订阅: {total_created}, 跳过: {total_skipped}")
    return cctv_channel_map


def update_config_yaml(conf: dict, category_map: dict[str, int],
                        cctv_channel_map: dict[str, str]):
    """将迁移结果写回 config.yaml。"""
    intel = conf.setdefault("intel", {})
    api = intel.setdefault("api", {})
    mf = api.setdefault("miniflux", {})

    # 写入 categories 映射
    mf["categories"] = category_map
    # 写入 cctv_channel_map
    mf["cctv_channel_map"] = cctv_channel_map

    # 移除 intel.rss（已迁移到 Miniflux）
    if "rss" in intel:
        del intel["rss"]
        print("[INFO] 已从 config.yaml 移除 intel.rss 段落")

    save_config(conf)
    print(f"[INFO] 已写入 config.yaml:")
    print(f"  categories: {category_map}")
    print(f"  cctv_channel_map: {cctv_channel_map}")


def main():
    print("=" * 60)
    print("RSS → Miniflux 迁移工具")
    print("=" * 60)

    # 加载配置
    conf = load_config()
    base, user, pwd = get_miniflux_auth(conf)
    auth = (user, pwd)
    print(f"\n[INFO] Miniflux: {base}")

    # 检查连通性
    try:
        resp = requests.get(f"{base}/v1/me", auth=auth, timeout=5)
        resp.raise_for_status()
        print(f"[INFO] 连接成功，用户: {resp.json().get('username', '?')}")
    except Exception as e:
        print(f"[FATAL] 无法连接 Miniflux: {e}")
        print("请确认 Miniflux 正在运行: docker compose up -d miniflux")
        sys.exit(1)

    # Step 1: 创建分类
    print("\n" + "-" * 40)
    print("Step 1: 创建 Miniflux 分类")
    print("-" * 40)
    category_map = ensure_categories(base, auth)

    if not category_map:
        print("[FATAL] 没有成功创建任何分类，退出")
        sys.exit(1)

    # Step 2: 迁移 feeds
    print("\n" + "-" * 40)
    print("Step 2: 迁移 RSS feeds")
    print("-" * 40)
    cctv_channel_map = migrate_feeds(conf, base, auth, category_map)

    # Step 3: 写回 config.yaml
    print("\n" + "-" * 40)
    print("Step 3: 更新 config.yaml")
    print("-" * 40)
    update_config_yaml(conf, category_map, cctv_channel_map)

    print("\n" + "=" * 60)
    print("迁移完成！")
    print(f"  Miniflux UI: {base}")
    print(f"  分类数: {len(category_map)}")
    print(f"  CCTV channel 映射: {len(cctv_channel_map)} 条")
    print("=" * 60)


if __name__ == "__main__":
    main()
