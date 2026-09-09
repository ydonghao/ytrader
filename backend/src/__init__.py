# src 包 - 源代码根目录
# NOTE: All imports are lazy to avoid triggering side effects during testing.
# Only 'domain' is eagerly imported (safe - it has no heavy deps).
from . import domain

__all__ = ['api', 'application', 'domain', 'infra', 'pkg', 'typings']


def __getattr__(name: str):
    if name in ("api", "application", "infra", "pkg", "typings"):
        import importlib

        return importlib.import_module(f"src.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
