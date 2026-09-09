"""
Centralized Database DSN Provider
=================================
All modules must import DSN from here — never hardcode connection strings.

Uses lazy import to avoid circular dependency with conf/__init__.
"""

def get_dsn() -> str:
    """Return the database DSN from central configuration (lazy import)."""
    from conf import app_config
    return app_config.database.url
