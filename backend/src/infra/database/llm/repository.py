"""
LLM config repository implementation.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import text
from sqlmodel import select

from src.domain.llm.models import LLMConfig, MASKED_KEY
from src.domain.llm.repository_interface import ILLMConfigRepository
from src.infra.database.llm.entity import LLMConfigTable
from src.infra.database.sql_engine.engine import DBConnection, create_db_connection
from src.infra.database.sql_engine.dsn import get_dsn
from src.infra.llm.key_encryptor import KeyEncryptor, generate_fernet_key


# ── Helpers ──────────────────────────────────────────────────────────────

_db_connection: DBConnection | None = None
_db_lock = threading.Lock()
_encryptor: KeyEncryptor | None = None


def _get_db_connection() -> DBConnection:
    """Thread-safe singleton DB connection for LLM configs."""
    global _db_connection
    if _db_connection is None:
        with _db_lock:
            if _db_connection is None:
                _db_connection = create_db_connection(get_dsn())
    return _db_connection


def _get_encryptor() -> KeyEncryptor:
    """Get or create the Fernet encryptor, auto-generating key if needed."""
    global _encryptor
    if _encryptor is None:
        from conf import app_config

        key_str = app_config.llm.encryption_key
        if not key_str:
            # Auto-generate and persist to config.yaml
            key_bytes = generate_fernet_key()
            _persist_encryption_key(key_bytes.decode("utf-8"))
            _encryptor = KeyEncryptor(key_bytes)
        else:
            _encryptor = KeyEncryptor(key_str.encode("utf-8"))
    return _encryptor


def _persist_encryption_key(key_str: str) -> None:
    """Write the generated encryption key back to config.yaml."""
    try:
        import yaml

        config_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "..", "conf", "config.yaml",
        )
        config_path = os.path.normpath(config_path)
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)
        if "llm" not in data:
            data["llm"] = {}
        data["llm"]["encryption_key"] = key_str
        with open(config_path, "w") as f:
            yaml.dump(
                data, f, default_flow_style=False, allow_unicode=True
            )
        logger.info(
            "LLM encryption key auto-generated and saved to config.yaml"
        )
    except Exception as e:
        logger.warning(
            f"Failed to persist LLM encryption key: {e}"
        )


def _row_to_config(
    row: LLMConfigTable, mask_key: bool = True
) -> LLMConfig:
    """Convert a DB row to domain model."""
    return LLMConfig(
        id=row.id,
        name=row.name,
        provider_type=row.provider_type,
        base_url=row.base_url,
        api_key=(
            MASKED_KEY
            if mask_key
            else _get_encryptor().decrypt_key(row.api_key_encrypted)
        ),
        model=row.model,
        is_default=row.is_default,
        extra_params=json.loads(row.extra_params) if row.extra_params else {},
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


# ── Repository ───────────────────────────────────────────────────────────

class LLMConfigRepository(ILLMConfigRepository):
    """LLM config repository with encrypted key storage."""

    def __init__(self, db_connection: DBConnection | None = None):
        self._db = db_connection or _get_db_connection()

    def list_configs(self) -> list[LLMConfig]:
        with self._db.session_scope() as session:
            rows = session.exec(select(LLMConfigTable)).all()
            return [_row_to_config(r, mask_key=True) for r in rows]

    def get_config(self, config_id: str) -> LLMConfig | None:
        with self._db.session_scope() as session:
            row = session.get(LLMConfigTable, config_id)
            if row is None:
                return None
            return _row_to_config(row, mask_key=True)

    def get_default_config(self) -> LLMConfig | None:
        with self._db.session_scope() as session:
            stmt = (
                select(LLMConfigTable)
                .where(LLMConfigTable.is_default == True)  # noqa: E712
                .limit(1)
            )
            row = session.exec(stmt).first()
            if row is None:
                return None
            return _row_to_config(row, mask_key=False)

    def get_decrypted_config(self, config_id: str) -> LLMConfig | None:
        with self._db.session_scope() as session:
            row = session.get(LLMConfigTable, config_id)
            if row is None:
                return None
            return _row_to_config(row, mask_key=False)

    def create_config(self, config: LLMConfig) -> LLMConfig:
        encrypted_key = _get_encryptor().encrypt_key(config.api_key)
        row = LLMConfigTable(
            name=config.name,
            provider_type=config.provider_type,
            base_url=config.base_url,
            api_key_encrypted=encrypted_key,
            model=config.model,
            is_default=config.is_default,
            extra_params=json.dumps(config.extra_params),
        )
        with self._db.session_scope() as session:
            if config.is_default:
                session.exec(
                    text(
                        "UPDATE llm_config SET is_default = false "
                        "WHERE is_default = true"
                    )
                )
            session.add(row)
            session.flush()
            session.refresh(row)
            result = _row_to_config(row, mask_key=True)
        return result

    def update_config(
        self, config_id: str, updates: dict
    ) -> LLMConfig | None:
        with self._db.session_scope() as session:
            row = session.get(LLMConfigTable, config_id)
            if row is None:
                return None
            for key, value in updates.items():
                if key == "api_key":
                    if not value:
                        continue
                    setattr(
                        row,
                        "api_key_encrypted",
                        _get_encryptor().encrypt_key(value),
                    )
                elif key == "extra_params":
                    setattr(row, key, json.dumps(value))
                elif key == "is_default" and value:
                    session.exec(
                        text(
                            "UPDATE llm_config SET is_default = false "
                            "WHERE is_default = true"
                        )
                    )
                    setattr(row, key, value)
                else:
                    setattr(row, key, value)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.flush()
            session.refresh(row)
            result = _row_to_config(row, mask_key=True)
        return result

    def delete_config(self, config_id: str) -> bool:
        with self._db.session_scope() as session:
            row = session.get(LLMConfigTable, config_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
        return True

    def set_default(self, config_id: str) -> None:
        with self._db.session_scope() as session:
            session.exec(
                text(
                    "UPDATE llm_config SET is_default = false "
                    "WHERE is_default = true"
                )
            )
            row = session.get(LLMConfigTable, config_id)
            if row:
                row.is_default = True
                session.add(row)
            session.commit()


# ── Factory ─────────────────────────────────────────────────────────────

def create_llm_repository(
    db_connection: DBConnection | None = None,
) -> LLMConfigRepository:
    """Factory function for LLMConfigRepository."""
    return LLMConfigRepository(db_connection)
