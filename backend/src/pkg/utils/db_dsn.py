"""独立脚本读取数据库 DSN 的零副作用工具。

合并 conf/config.yaml 与 conf/config.local.yaml（后者已 gitignore，
存放本地真实密码/密钥），不经过 conf.settings——其包初始化会连接
MinIO，不适合 scripts/ 等轻量场景。
"""
from pathlib import Path

import yaml


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, extra: dict) -> None:
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def load_db_dsn(backend_root: Path | None = None) -> str:
    """返回 database.url（本地覆盖文件优先）。"""
    root = backend_root or Path(__file__).resolve().parents[3]
    conf_dir = root / "conf"
    conf = _read_yaml(conf_dir / "config.yaml")
    _deep_merge(conf, _read_yaml(conf_dir / "config.local.yaml"))
    return conf["database"]["url"]
