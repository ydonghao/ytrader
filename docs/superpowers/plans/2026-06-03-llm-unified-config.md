# LLM Unified Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified LLM calling facade supporting OpenAI Chat, OpenAI Response, and Anthropic Messages protocols, with model configs stored in PostgreSQL (AES-encrypted API keys) and a frontend Settings page for CRUD management.

**Architecture:** Provider Factory pattern — domain layer defines `LLMProvider` interface and `ILLMConfigRepository`, infra layer implements three SDK-backed providers (`openai`, `anthropic`) plus AES encryption and `LLMManager`. API layer exposes REST endpoints. Frontend Settings page replaces the old MiniMax-only localStorage approach.

**Tech Stack:** Python 3.13, FastAPI, SQLModel, openai SDK, anthropic SDK, cryptography (Fernet), React + TypeScript

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `backend/src/domain/llm/__init__.py` | Package exports |
| `backend/src/domain/llm/models.py` | Data classes: `LLMResponse`, `LLMConfig`, `TokenUsage`, `LLMChunk`, `TestResult` |
| `backend/src/domain/llm/provider_interface.py` | `LLMProvider(ABC)` with `chat()`, `complete()`, `chat_stream()` |
| `backend/src/domain/llm/repository_interface.py` | `ILLMConfigRepository(ABC)` |
| `backend/src/infra/llm/__init__.py` | Package exports |
| `backend/src/infra/llm/providers/__init__.py` | Package exports |
| `backend/src/infra/llm/providers/openai_chat_provider.py` | OpenAI Chat Completions via `openai` SDK |
| `backend/src/infra/llm/providers/openai_response_provider.py` | OpenAI Responses API via `openai` SDK |
| `backend/src/infra/llm/providers/anthropic_provider.py` | Anthropic Messages via `anthropic` SDK |
| `backend/src/infra/llm/provider_factory.py` | `create_provider(config) -> LLMProvider` |
| `backend/src/infra/llm/key_encryptor.py` | `encrypt_key()` / `decrypt_key()` using Fernet |
| `backend/src/infra/llm/manager.py` | `LLMManager` — unified entry point with caching |
| `backend/src/infra/database/impl/llm_db.py` | `LLMConfigTable` SQLModel + `LLMConfigRepository` |
| `backend/src/api/model/llm_config_model.py` | Pydantic request/response models |
| `backend/src/api/router/llm_config_router.py` | REST endpoints for LLM config CRUD + test |
| `backend/tests/domain/llm/__init__.py` | Test package |
| `backend/tests/domain/llm/test_models.py` | Unit tests for domain models |
| `backend/tests/domain/llm/test_provider_interface.py` | Unit tests for provider interface contract |
| `backend/tests/infra/llm/__init__.py` | Test package |
| `backend/tests/infra/llm/test_key_encryptor.py` | Unit tests for AES encrypt/decrypt |
| `backend/tests/infra/llm/test_provider_factory.py` | Unit tests for factory |
| `backend/tests/infra/llm/test_openai_chat_provider.py` | Unit tests for OpenAI Chat provider |
| `backend/tests/infra/llm/test_openai_response_provider.py` | Unit tests for OpenAI Response provider |
| `backend/tests/infra/llm/test_anthropic_provider.py` | Unit tests for Anthropic provider |
| `backend/tests/infra/llm/test_manager.py` | Unit tests for LLMManager |
| `backend/tests/infra/database/test_llm_db.py` | Integration tests for LLM config repository |
| `backend/tests/api/test_llm_config_router.py` | API integration tests |

### Modified Files

| File | Change |
|------|--------|
| `backend/conf/config.yaml` | Add `llm:` section with `encryption_key` |
| `backend/conf/settings.py` | Add `LLMSettings` model + `llm` field to `AppConfig` |
| `backend/pyproject.toml` | Add `anthropic>=0.40.0`, `cryptography>=43.0.0`, `openai` dependencies |
| `backend/main.py` | Import and register `llm_config_router`, add MiniMax migration in lifespan |
| `backend/src/api/router/signal_router.py` | Replace `get_llm_client()` with `llm_manager.get_default_provider()` |
| `backend/src/domain/market/intel/processor.py` | Fix broken LLM imports → use `llm_manager` |
| `backend/src/domain/market/strategy/agents/base.py` | Type hint `llm` param as `LLMProvider` |
| `frontend/apps/web/src/pages/Settings.tsx` | Replace MiniMax key section with LLM model config UI |
| `frontend/apps/web/src/pages/Settings.css` | Add LLM config card styles + modal styles |
| `frontend/apps/web/src/pages/Market.tsx` | Remove `x-llm-api-key` header logic |

---

## Task 1: Domain Layer — Models and Interfaces

**Files:**
- Create: `backend/src/domain/llm/__init__.py`
- Create: `backend/src/domain/llm/models.py`
- Create: `backend/src/domain/llm/provider_interface.py`
- Create: `backend/src/domain/llm/repository_interface.py`
- Test: `backend/tests/domain/llm/test_models.py`

- [ ] **Step 1: Create the domain llm package directory**

```bash
mkdir -p backend/src/domain/llm
mkdir -p backend/tests/domain/llm
```

- [ ] **Step 2: Write `backend/tests/domain/llm/__init__.py`**

```python
# Test package
```

- [ ] **Step 3: Write `backend/src/domain/llm/models.py`**

```python
"""LLM domain models — provider-agnostic data classes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: TokenUsage | None = None
    raw_response: dict[str, Any] | None = None


@dataclass
class LLMChunk:
    content: str
    model: str
    finish_reason: str | None = None


@dataclass
class LLMConfig:
    """A single model configuration (domain model, api_key is plaintext)."""
    id: str = ""
    name: str = ""
    provider_type: str = ""  # "openai_chat" | "openai_response" | "anthropic"
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    is_default: bool = False
    extra_params: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class TestResult:
    success: bool
    message: str
    latency_ms: float | None = None


# Sentinel value for masked API keys in read responses
MASKED_KEY = "****"
```

- [ ] **Step 4: Write `backend/src/domain/llm/provider_interface.py`**

```python
"""LLM provider interface — all providers must implement this."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from src.domain.llm.models import LLMResponse, LLMChunk


class LLMProvider(ABC):
    """Unified LLM calling interface."""

    @abstractmethod
    async def chat(
        self, messages: list[dict[str, str]], **kwargs
    ) -> LLMResponse:
        """Multi-turn chat. messages format: [{"role": "user", "content": "..."}]."""

    @abstractmethod
    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        """Single-prompt completion."""

    @abstractmethod
    async def chat_stream(
        self, messages: list[dict[str, str]], **kwargs
    ) -> AsyncIterator[LLMChunk]:
        """Streaming multi-turn chat."""
```

- [ ] **Step 5: Write `backend/src/domain/llm/repository_interface.py`**

```python
"""LLM config repository interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.llm.models import LLMConfig


class ILLMConfigRepository(ABC):

    @abstractmethod
    def list_configs(self) -> list[LLMConfig]:
        """List all configs. API keys are masked (****)."""

    @abstractmethod
    def get_config(self, config_id: str) -> LLMConfig | None:
        """Get a single config by ID. API key is masked."""

    @abstractmethod
    def get_default_config(self) -> LLMConfig | None:
        """Get the default config. API key is decrypted (plaintext)."""

    @abstractmethod
    def get_decrypted_config(self, config_id: str) -> LLMConfig | None:
        """Get a config with decrypted API key. Used internally by LLMManager."""

    @abstractmethod
    def create_config(self, config: LLMConfig) -> LLMConfig:
        """Create a new config. Encrypts api_key before storing."""

    @abstractmethod
    def update_config(self, config_id: str, updates: dict) -> LLMConfig | None:
        """Update fields. If api_key is empty/None, keeps existing."""

    @abstractmethod
    def delete_config(self, config_id: str) -> bool:
        """Delete a config. Returns True if deleted."""

    @abstractmethod
    def set_default(self, config_id: str) -> None:
        """Set a config as default. Clears other defaults first."""
```

- [ ] **Step 6: Write `backend/src/domain/llm/__init__.py`**

```python
"""LLM domain layer — interfaces and models."""
from src.domain.llm.models import (
    LLMResponse,
    LLMConfig,
    TokenUsage,
    LLMChunk,
    TestResult,
    MASKED_KEY,
)
from src.domain.llm.provider_interface import LLMProvider
from src.domain.llm.repository_interface import ILLMConfigRepository

__all__ = [
    "LLMResponse",
    "LLMConfig",
    "TokenUsage",
    "LLMChunk",
    "TestResult",
    "MASKED_KEY",
    "LLMProvider",
    "ILLMConfigRepository",
]
```

- [ ] **Step 7: Write the failing test `backend/tests/domain/llm/test_models.py`**

```python
"""Unit tests for LLM domain models."""
from src.domain.llm.models import (
    LLMConfig,
    LLMResponse,
    TokenUsage,
    LLMChunk,
    TestResult,
    MASKED_KEY,
)


def test_llm_config_defaults():
    config = LLMConfig()
    assert config.id == ""
    assert config.is_default is False
    assert config.extra_params == {}


def test_llm_config_with_values():
    config = LLMConfig(
        id="abc",
        name="GPT-4o",
        provider_type="openai_chat",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
        is_default=True,
    )
    assert config.name == "GPT-4o"
    assert config.provider_type == "openai_chat"


def test_llm_response():
    resp = LLMResponse(content="hello", model="gpt-4o")
    assert resp.content == "hello"
    assert resp.usage is None
    assert resp.raw_response is None


def test_llm_response_with_usage():
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    resp = LLMResponse(content="hi", model="gpt-4o", usage=usage)
    assert resp.usage.total_tokens == 15


def test_llm_chunk():
    chunk = LLMChunk(content="hel", model="gpt-4o", finish_reason=None)
    assert chunk.content == "hel"
    assert chunk.finish_reason is None


def test_test_result():
    result = TestResult(success=True, message="OK", latency_ms=150.3)
    assert result.success is True
    assert result.latency_ms == 150.3


def test_masked_key_constant():
    assert MASKED_KEY == "****"
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/llm/test_models.py -v`
Expected: All 7 tests PASS

- [ ] **Step 9: Commit**

```bash
git add src/domain/llm/ tests/domain/llm/
git commit -m "feat(llm): add domain layer — models, provider interface, repository interface"
```

---

## Task 2: Configuration — config.yaml and settings.py

**Files:**
- Modify: `backend/conf/config.yaml` (add `llm:` section after `intel:`)
- Modify: `backend/conf/settings.py` (add `LLMSettings` + `AppConfig.llm` field)

- [ ] **Step 1: Add `llm` section to `backend/conf/config.yaml`**

Append at the end of `config.yaml`:

```yaml

# LLM unified configuration
llm:
  encryption_key: ""  # Auto-generated on first start (Fernet key)
```

- [ ] **Step 2: Add `LLMSettings` to `backend/conf/settings.py`**

After the existing `IntelConfig` class (around line 101), add:

```python
class LLMSettings(BaseModel):
    encryption_key: str = ""
```

Then in `AppConfig` class, add the `llm` field:

```python
class AppConfig(BaseModel):
    server: ServerConfig = ServerConfig()
    nacos: NacosConfig = NacosConfig()
    database: DatabaseConfig = DatabaseConfig()
    elasticsearch: ElasticsearchConfig = ElasticsearchConfig()
    minio: MinioConfig = MinioConfig()
    root_path: str = ""
    logging: LoggingConfig = LoggingConfig()
    file_parse: FileParseConfig = FileParseConfig()
    intel: IntelConfig = IntelConfig()
    llm: LLMSettings = LLMSettings()  # <-- NEW
```

- [ ] **Step 3: Verify config loads correctly**

Run: `cd backend && .venv/bin/python -c "from conf import app_config; print(app_config.llm.encryption_key)"`
Expected: prints empty string (no error)

- [ ] **Step 4: Commit**

```bash
git add conf/config.yaml conf/settings.py
git commit -m "feat(llm): add LLM settings to config.yaml and AppConfig"
```

---

## Task 3: Dependencies — pyproject.toml

**Files:**
- Modify: `backend/pyproject.toml` (add `anthropic`, `cryptography`, `openai`)

- [ ] **Step 1: Add dependencies to `backend/pyproject.toml`**

In the `[project]` `dependencies` array, add these three entries:

```toml
    "openai>=1.0.0",
    "anthropic>=0.40.0",
    "cryptography>=43.0.0",
```

- [ ] **Step 2: Install new dependencies**

Run: `cd backend && uv sync`

- [ ] **Step 3: Verify imports work**

Run: `cd backend && .venv/bin/python -c "import openai; import anthropic; from cryptography.fernet import Fernet; print('All imports OK')"`
Expected: `All imports OK`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(llm): add openai, anthropic, cryptography dependencies"
```

---

## Task 4: Key Encryptor

**Files:**
- Create: `backend/src/infra/llm/__init__.py`
- Create: `backend/src/infra/llm/key_encryptor.py`
- Test: `backend/tests/infra/llm/__init__.py`
- Test: `backend/tests/infra/llm/test_key_encryptor.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p backend/src/infra/llm/providers
mkdir -p backend/tests/infra/llm
```

- [ ] **Step 2: Write `backend/tests/infra/llm/__init__.py`**

```python
# Test package
```

- [ ] **Step 3: Write the failing test `backend/tests/infra/llm/test_key_encryptor.py`**

```python
"""Unit tests for AES key encryptor."""
import pytest
from src.infra.llm.key_encryptor import KeyEncryptor, generate_fernet_key


def test_generate_fernet_key_returns_bytes():
    key = generate_fernet_key()
    assert isinstance(key, bytes)
    assert len(key) > 0


def test_generate_fernet_key_unique():
    key1 = generate_fernet_key()
    key2 = generate_fernet_key()
    assert key1 != key2


def test_encrypt_decrypt_roundtrip():
    encryptor = KeyEncryptor(generate_fernet_key())
    plaintext = "sk-test-api-key-12345"
    encrypted = encryptor.encrypt_key(plaintext)
    assert encrypted != plaintext
    decrypted = encryptor.decrypt_key(encrypted)
    assert decrypted == plaintext


def test_encrypt_produces_different_ciphertext():
    encryptor = KeyEncryptor(generate_fernet_key())
    plaintext = "same-key"
    enc1 = encryptor.encrypt_key(plaintext)
    enc2 = encryptor.encrypt_key(plaintext)
    # Fernet uses timestamp, so ciphertexts differ
    assert enc1 != enc2


def test_decrypt_wrong_key_fails():
    enc1 = KeyEncryptor(generate_fernet_key())
    enc2 = KeyEncryptor(generate_fernet_key())
    encrypted = enc1.encrypt_key("secret")
    with pytest.raises(Exception):
        enc2.decrypt_key(encrypted)


def test_encrypt_empty_string():
    encryptor = KeyEncryptor(generate_fernet_key())
    encrypted = encryptor.encrypt_key("")
    assert encryptor.decrypt_key(encrypted) == ""
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/llm/test_key_encryptor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.infra.llm.key_encryptor'`

- [ ] **Step 5: Write `backend/src/infra/llm/key_encryptor.py`**

```python
"""AES-256 key encryption using Fernet (cryptography library)."""
from __future__ import annotations

from cryptography.fernet import Fernet


def generate_fernet_key() -> bytes:
    """Generate a new Fernet encryption key."""
    return Fernet.generate_key()


class KeyEncryptor:
    """Encrypts and decrypts API keys using Fernet symmetric encryption."""

    def __init__(self, key: bytes):
        self._fernet = Fernet(key)

    def encrypt_key(self, plaintext: str) -> str:
        """Encrypt a plaintext API key. Returns base64-encoded ciphertext."""
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt_key(self, ciphertext: str) -> str:
        """Decrypt a ciphertext back to plaintext API key."""
        return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
```

- [ ] **Step 6: Write `backend/src/infra/llm/__init__.py`**

```python
"""LLM infrastructure — providers, encryption, manager."""
from src.infra.llm.key_encryptor import KeyEncryptor, generate_fernet_key

__all__ = ["KeyEncryptor", "generate_fernet_key"]
```

- [ ] **Step 7: Write `backend/src/infra/llm/providers/__init__.py`**

```python
# LLM providers package
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/llm/test_key_encryptor.py -v`
Expected: All 6 tests PASS

- [ ] **Step 9: Commit**

```bash
git add src/infra/llm/ tests/infra/llm/
git commit -m "feat(llm): add key encryptor with Fernet AES encryption"
```

---

## Task 5: Database Layer — LLMConfigTable and Repository

**Files:**
- Create: `backend/src/infra/database/impl/llm_db.py`
- Test: `backend/tests/infra/database/test_llm_db.py`

- [ ] **Step 1: Write the failing test `backend/tests/infra/database/test_llm_db.py`**

This test requires a running PostgreSQL at localhost:5432. It will create/use the `ytrader` database.

```python
"""Integration tests for LLM config repository."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from src.domain.llm.models import LLMConfig
from src.infra.database.impl.llm_db import (
    create_llm_repository,
    LLMConfigTable,
)


@pytest.fixture(scope="module")
def llm_repo():
    """Create a repository connected to the real DB."""
    repo = create_llm_repository()
    # Cleanup: delete all test rows after suite
    yield repo
    with repo._db.session_scope() as session:
        session.exec(
            LLMConfigTable.__table__.delete()
        )
        session.commit()


def test_create_config(llm_repo):
    config = LLMConfig(
        name="Test GPT",
        provider_type="openai_chat",
        base_url="https://api.openai.com/v1",
        api_key="sk-test-key-123",
        model="gpt-4o",
        is_default=True,
    )
    result = llm_repo.create_config(config)
    assert result.id != ""
    assert result.name == "Test GPT"
    assert result.api_key == "****"  # Masked in return value


def test_list_configs(llm_repo):
    configs = llm_repo.list_configs()
    assert isinstance(configs, list)
    for c in configs:
        assert c.api_key == "****"


def test_get_default_config(llm_repo):
    config = llm_repo.get_default_config()
    assert config is not None
    assert config.is_default is True
    assert config.api_key != "****"  # Decrypted for internal use


def test_get_decrypted_config(llm_repo):
    configs = llm_repo.list_configs()
    if not configs:
        pytest.skip("No configs in DB")
    c = configs[0]
    decrypted = llm_repo.get_decrypted_config(c.id)
    assert decrypted is not None
    assert decrypted.api_key == "sk-test-key-123"


def test_update_config(llm_repo):
    configs = llm_repo.list_configs()
    if not configs:
        pytest.skip("No configs in DB")
    c = configs[0]
    updated = llm_repo.update_config(c.id, {"name": "Updated GPT"})
    assert updated is not None
    assert updated.name == "Updated GPT"


def test_update_config_keep_api_key(llm_repo):
    configs = llm_repo.list_configs()
    if not configs:
        pytest.skip("No configs in DB")
    c = configs[0]
    # Update without providing api_key — should keep original
    llm_repo.update_config(c.id, {"name": "Keep Key Test"})
    decrypted = llm_repo.get_decrypted_config(c.id)
    assert decrypted.api_key == "sk-test-key-123"


def test_set_default(llm_repo):
    # Create a second config
    config2 = LLMConfig(
        name="Test Claude",
        provider_type="anthropic",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-test",
        model="claude-sonnet-4-20250514",
        is_default=False,
    )
    created = llm_repo.create_config(config2)

    # Set second as default
    llm_repo.set_default(created.id)

    # Verify only the second is default
    default = llm_repo.get_default_config()
    assert default is not None
    assert default.id == created.id


def test_delete_config(llm_repo):
    configs = llm_repo.list_configs()
    if not configs:
        pytest.skip("No configs to delete")
    c = configs[0]
    result = llm_repo.delete_config(c.id)
    assert result is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/database/test_llm_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.infra.database.impl.llm_db'`

- [ ] **Step 3: Write `backend/src/infra/database/impl/llm_db.py`**

```python
"""LLM config database table and repository implementation."""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger
from sqlmodel import SQLModel, Field, select
from sqlalchemy import text

from src.domain.llm.models import LLMConfig, MASKED_KEY
from src.domain.llm.repository_interface import ILLMConfigRepository
from src.infra.database.db_helper import DBConnection, create_db_connection
from src.infra.llm.key_encryptor import KeyEncryptor, generate_fernet_key


# ── Table Model ─────────────────────────────────────────────────────────

class LLMConfigTable(SQLModel, table=True):
    __tablename__ = "llm_config"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    name: str = Field(index=True)
    provider_type: str                              # "openai_chat" | "openai_response" | "anthropic"
    base_url: str
    api_key_encrypted: str                          # Fernet-encrypted ciphertext
    model: str
    is_default: bool = Field(default=False, index=True)
    extra_params: str = Field(default="{}")         # JSON string
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
                from src.infra.database.dsn import get_dsn
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
        from conf.settings import load_local_config
        config_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "conf", "config.yaml")
        config_path = os.path.normpath(config_path)
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)
        if "llm" not in data:
            data["llm"] = {}
        data["llm"]["encryption_key"] = key_str
        with open(config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
        logger.info("LLM encryption key auto-generated and saved to config.yaml")
    except Exception as e:
        logger.warning(f"Failed to persist LLM encryption key: {e}")


def _row_to_config(row: LLMConfigTable, mask_key: bool = True) -> LLMConfig:
    """Convert a DB row to domain model."""
    return LLMConfig(
        id=row.id,
        name=row.name,
        provider_type=row.provider_type,
        base_url=row.base_url,
        api_key=MASKED_KEY if mask_key else _get_encryptor().decrypt_key(row.api_key_encrypted),
        model=row.model,
        is_default=row.is_default,
        extra_params=json.loads(row.extra_params) if row.extra_params else {},
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


# ── Repository ───────────────────────────────────────────────────────────

class LLMConfigRepository(ILLMConfigRepository):

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
            stmt = select(LLMConfigTable).where(LLMConfigTable.is_default == True).limit(1)
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
                    text("UPDATE llm_config SET is_default = false WHERE is_default = true")
                )
            session.add(row)
            session.commit()
            session.refresh(row)
        return _row_to_config(row, mask_key=True)

    def update_config(self, config_id: str, updates: dict) -> LLMConfig | None:
        with self._db.session_scope() as session:
            row = session.get(LLMConfigTable, config_id)
            if row is None:
                return None
            for key, value in updates.items():
                if key == "api_key":
                    # Keep existing if empty or None
                    if not value:
                        continue
                    setattr(row, "api_key_encrypted", _get_encryptor().encrypt_key(value))
                elif key == "extra_params":
                    setattr(row, key, json.dumps(value))
                elif key == "is_default" and value:
                    session.exec(
                        text("UPDATE llm_config SET is_default = false WHERE is_default = true")
                    )
                    setattr(row, key, value)
                else:
                    setattr(row, key, value)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
            session.refresh(row)
        return _row_to_config(row, mask_key=True)

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
                text("UPDATE llm_config SET is_default = false WHERE is_default = true")
            )
            row = session.get(LLMConfigTable, config_id)
            if row:
                row.is_default = True
                session.add(row)
            session.commit()


def create_llm_repository(db_connection: DBConnection | None = None) -> LLMConfigRepository:
    """Factory function for LLMConfigRepository."""
    return LLMConfigRepository(db_connection)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/database/test_llm_db.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/infra/database/impl/llm_db.py tests/infra/database/test_llm_db.py
git commit -m "feat(llm): add LLM config database table and repository"
```

---

## Task 6: Provider Implementations — OpenAI Chat

**Files:**
- Create: `backend/src/infra/llm/providers/openai_chat_provider.py`
- Test: `backend/tests/infra/llm/test_openai_chat_provider.py`

- [ ] **Step 1: Write the failing test `backend/tests/infra/llm/test_openai_chat_provider.py`**

This test uses `unittest.mock` to mock the `openai` SDK. No real API calls.

```python
"""Unit tests for OpenAI Chat provider."""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.domain.llm.models import LLMConfig
from src.infra.llm.providers.openai_chat_provider import OpenAIChatProvider


@pytest.fixture
def config():
    return LLMConfig(
        id="test",
        name="GPT-4o",
        provider_type="openai_chat",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
    )


@pytest.fixture
def provider(config):
    return OpenAIChatProvider(config)


def test_provider_creates_client(provider):
    assert provider._client is not None


@pytest.mark.asyncio
async def test_chat_returns_llm_response(provider):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello!"
    mock_response.model = "gpt-4o"
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 5
    mock_response.usage.total_tokens = 15

    provider._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await provider.chat([{"role": "user", "content": "Hi"}])
    assert result.content == "Hello!"
    assert result.model == "gpt-4o"
    assert result.usage.total_tokens == 15


@pytest.mark.asyncio
async def test_complete_wraps_chat(provider):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "2+2=4"
    mock_response.model = "gpt-4o"
    mock_response.usage = None

    provider._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await provider.complete("What is 2+2?")
    assert result.content == "2+2=4"


@pytest.mark.asyncio
async def test_chat_with_kwargs(provider):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "creative answer"
    mock_response.model = "gpt-4o"
    mock_response.usage = None

    provider._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await provider.chat(
        [{"role": "user", "content": "Be creative"}],
        temperature=0.9,
        max_tokens=500,
    )
    assert result.content == "creative answer"
    provider._client.chat.completions.create.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/llm/test_openai_chat_provider.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `backend/src/infra/llm/providers/openai_chat_provider.py`**

```python
"""OpenAI Chat Completions provider."""
from __future__ import annotations

from typing import AsyncIterator

from openai import OpenAI

from src.domain.llm.models import LLMConfig, LLMResponse, TokenUsage, LLMChunk
from src.domain.llm.provider_interface import LLMProvider


class OpenAIChatProvider(LLMProvider):
    """Provider using OpenAI Chat Completions API."""

    def __init__(self, config: LLMConfig):
        self._config = config
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    async def chat(self, messages: list[dict[str, str]], **kwargs) -> LLMResponse:
        response = self._client.chat.completions.create(
            model=self._config.model,
            messages=messages,
            **kwargs,
        )
        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )
        return LLMResponse(
            content=response.choices[0].message.content,
            model=response.model,
            usage=usage,
            raw_response=response.model_dump() if hasattr(response, "model_dump") else None,
        )

    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        return await self.chat([{"role": "user", "content": prompt}], **kwargs)

    async def chat_stream(
        self, messages: list[dict[str, str]], **kwargs
    ) -> AsyncIterator[LLMChunk]:
        stream = self._client.chat.completions.create(
            model=self._config.model,
            messages=messages,
            stream=True,
            **kwargs,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield LLMChunk(
                    content=delta.content,
                    model=chunk.model,
                    finish_reason=chunk.choices[0].finish_reason if chunk.choices else None,
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/llm/test_openai_chat_provider.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/infra/llm/providers/openai_chat_provider.py tests/infra/llm/test_openai_chat_provider.py
git commit -m "feat(llm): add OpenAI Chat Completions provider"
```

---

## Task 7: Provider Implementations — OpenAI Response

**Files:**
- Create: `backend/src/infra/llm/providers/openai_response_provider.py`
- Test: `backend/tests/infra/llm/test_openai_response_provider.py`

- [ ] **Step 1: Write the failing test `backend/tests/infra/llm/test_openai_response_provider.py`**

```python
"""Unit tests for OpenAI Response provider."""
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.domain.llm.models import LLMConfig
from src.infra.llm.providers.openai_response_provider import OpenAIResponseProvider


@pytest.fixture
def config():
    return LLMConfig(
        id="test",
        name="GPT-4o Response",
        provider_type="openai_response",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
    )


@pytest.fixture
def provider(config):
    return OpenAIResponseProvider(config)


@pytest.mark.asyncio
async def test_chat_returns_llm_response(provider):
    mock_response = MagicMock()
    # Responses API returns output_text
    mock_response.output_text = "Hello from responses API!"
    mock_response.model = "gpt-4o"
    mock_response.usage = MagicMock()
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 5
    mock_response.usage.total_tokens = 15

    provider._client.responses.create = AsyncMock(return_value=mock_response)

    result = await provider.chat([{"role": "user", "content": "Hi"}])
    assert result.content == "Hello from responses API!"
    assert result.model == "gpt-4o"


@pytest.mark.asyncio
async def test_complete_wraps_chat(provider):
    mock_response = MagicMock()
    mock_response.output_text = "42"
    mock_response.model = "gpt-4o"
    mock_response.usage = None

    provider._client.responses.create = AsyncMock(return_value=mock_response)

    result = await provider.complete("What is 6*7?")
    assert result.content == "42"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/llm/test_openai_response_provider.py -v`
Expected: FAIL

- [ ] **Step 3: Write `backend/src/infra/llm/providers/openai_response_provider.py`**

```python
"""OpenAI Responses API provider."""
from __future__ import annotations

from typing import AsyncIterator

from openai import OpenAI

from src.domain.llm.models import LLMConfig, LLMResponse, TokenUsage, LLMChunk
from src.domain.llm.provider_interface import LLMProvider


class OpenAIResponseProvider(LLMProvider):
    """Provider using OpenAI Responses API."""

    def __init__(self, config: LLMConfig):
        self._config = config
        self._client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    async def chat(self, messages: list[dict[str, str]], **kwargs) -> LLMResponse:
        # Responses API takes a single input string
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg["content"]
                break
        if not last_user_msg:
            last_user_msg = messages[-1]["content"] if messages else ""

        response = self._client.responses.create(
            model=self._config.model,
            input=last_user_msg,
            **kwargs,
        )
        usage = None
        if hasattr(response, "usage") and response.usage:
            usage = TokenUsage(
                prompt_tokens=getattr(response.usage, "input_tokens", 0),
                completion_tokens=getattr(response.usage, "output_tokens", 0),
                total_tokens=getattr(response.usage, "total_tokens", 0),
            )
        return LLMResponse(
            content=getattr(response, "output_text", "") or "",
            model=response.model,
            usage=usage,
            raw_response=response.model_dump() if hasattr(response, "model_dump") else None,
        )

    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        return await self.chat([{"role": "user", "content": prompt}], **kwargs)

    async def chat_stream(
        self, messages: list[dict[str, str]], **kwargs
    ) -> AsyncIterator[LLMChunk]:
        last_user_msg = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_msg = msg["content"]
                break

        stream = self._client.responses.create(
            model=self._config.model,
            input=last_user_msg,
            stream=True,
            **kwargs,
        )
        for event in stream:
            if hasattr(event, "delta") and event.delta:
                yield LLMChunk(
                    content=event.delta,
                    model=self._config.model,
                    finish_reason=None,
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/llm/test_openai_response_provider.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/infra/llm/providers/openai_response_provider.py tests/infra/llm/test_openai_response_provider.py
git commit -m "feat(llm): add OpenAI Responses API provider"
```

---

## Task 8: Provider Implementations — Anthropic

**Files:**
- Create: `backend/src/infra/llm/providers/anthropic_provider.py`
- Test: `backend/tests/infra/llm/test_anthropic_provider.py`

- [ ] **Step 1: Write the failing test `backend/tests/infra/llm/test_anthropic_provider.py`**

```python
"""Unit tests for Anthropic provider."""
from unittest.mock import AsyncMock, MagicMock
import pytest

from src.domain.llm.models import LLMConfig
from src.infra.llm.providers.anthropic_provider import AnthropicProvider


@pytest.fixture
def config():
    return LLMConfig(
        id="test",
        name="Claude Sonnet",
        provider_type="anthropic",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-test",
        model="claude-sonnet-4-20250514",
    )


@pytest.fixture
def provider(config):
    return AnthropicProvider(config)


def test_provider_creates_client(provider):
    assert provider._client is not None


@pytest.mark.asyncio
async def test_chat_returns_llm_response(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = "Hello from Claude!"
    mock_response.model = "claude-sonnet-4-20250514"
    mock_response.usage = MagicMock()
    mock_response.usage.input_tokens = 10
    mock_response.usage.output_tokens = 5

    provider._client.messages.create = AsyncMock(return_value=mock_response)

    result = await provider.chat([{"role": "user", "content": "Hi"}])
    assert result.content == "Hello from Claude!"
    assert result.model == "claude-sonnet-4-20250514"
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 5


@pytest.mark.asyncio
async def test_complete_wraps_chat(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = "42"
    mock_response.model = "claude-sonnet-4-20250514"
    mock_response.usage = None

    provider._client.messages.create = AsyncMock(return_value=mock_response)

    result = await provider.complete("6*7?")
    assert result.content == "42"


@pytest.mark.asyncio
async def test_chat_passes_max_tokens(provider):
    mock_response = MagicMock()
    mock_response.content = [MagicMock()]
    mock_response.content[0].text = "short"
    mock_response.model = "claude-sonnet-4-20250514"
    mock_response.usage = None

    provider._client.messages.create = AsyncMock(return_value=mock_response)

    await provider.chat([{"role": "user", "content": "Hi"}], max_tokens=100)
    call_kwargs = provider._client.messages.create.call_args[1]
    assert call_kwargs["max_tokens"] == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/llm/test_anthropic_provider.py -v`
Expected: FAIL

- [ ] **Step 3: Write `backend/src/infra/llm/providers/anthropic_provider.py`**

```python
"""Anthropic Messages API provider."""
from __future__ import annotations

from typing import AsyncIterator

import anthropic

from src.domain.llm.models import LLMConfig, LLMResponse, TokenUsage, LLMChunk
from src.domain.llm.provider_interface import LLMProvider


class AnthropicProvider(LLMProvider):
    """Provider using Anthropic Messages API."""

    def __init__(self, config: LLMConfig):
        self._config = config
        self._client = anthropic.Anthropic(
            api_key=config.api_key,
            base_url=config.base_url if config.base_url != "https://api.anthropic.com" else None,
        )

    async def chat(self, messages: list[dict[str, str]], **kwargs) -> LLMResponse:
        # Anthropic requires max_tokens; default to 1024 if not provided
        max_tokens = kwargs.pop("max_tokens", 1024)
        temperature = kwargs.pop("temperature", None)

        params = {
            "model": self._config.model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            params["temperature"] = temperature

        response = self._client.messages.create(**params)

        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            )

        return LLMResponse(
            content=response.content[0].text if response.content else "",
            model=response.model,
            usage=usage,
            raw_response=response.model_dump() if hasattr(response, "model_dump") else None,
        )

    async def complete(self, prompt: str, **kwargs) -> LLMResponse:
        return await self.chat([{"role": "user", "content": prompt}], **kwargs)

    async def chat_stream(
        self, messages: list[dict[str, str]], **kwargs
    ) -> AsyncIterator[LLMChunk]:
        max_tokens = kwargs.pop("max_tokens", 1024)

        with self._client.messages.stream(
            model=self._config.model,
            messages=messages,
            max_tokens=max_tokens,
        ) as stream:
            for text in stream.text_stream:
                yield LLMChunk(
                    content=text,
                    model=self._config.model,
                    finish_reason=None,
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/llm/test_anthropic_provider.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/infra/llm/providers/anthropic_provider.py tests/infra/llm/test_anthropic_provider.py
git commit -m "feat(llm): add Anthropic Messages API provider"
```

---

## Task 9: Provider Factory

**Files:**
- Create: `backend/src/infra/llm/provider_factory.py`
- Test: `backend/tests/infra/llm/test_provider_factory.py`

- [ ] **Step 1: Write the failing test `backend/tests/infra/llm/test_provider_factory.py`**

```python
"""Unit tests for LLM provider factory."""
import pytest

from src.domain.llm.models import LLMConfig
from src.infra.llm.providers.openai_chat_provider import OpenAIChatProvider
from src.infra.llm.providers.openai_response_provider import OpenAIResponseProvider
from src.infra.llm.providers.anthropic_provider import AnthropicProvider
from src.infra.llm.provider_factory import create_provider


def test_create_openai_chat_provider():
    config = LLMConfig(
        provider_type="openai_chat",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
    )
    provider = create_provider(config)
    assert isinstance(provider, OpenAIChatProvider)


def test_create_openai_response_provider():
    config = LLMConfig(
        provider_type="openai_response",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
    )
    provider = create_provider(config)
    assert isinstance(provider, OpenAIResponseProvider)


def test_create_anthropic_provider():
    config = LLMConfig(
        provider_type="anthropic",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-test",
        model="claude-sonnet-4-20250514",
    )
    provider = create_provider(config)
    assert isinstance(provider, AnthropicProvider)


def test_create_unknown_provider_raises():
    config = LLMConfig(
        provider_type="unknown_type",
        base_url="http://example.com",
        api_key="key",
        model="model",
    )
    with pytest.raises(ValueError, match="Unknown provider type"):
        create_provider(config)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/llm/test_provider_factory.py -v`
Expected: FAIL

- [ ] **Step 3: Write `backend/src/infra/llm/provider_factory.py`**

```python
"""Factory for creating LLM provider instances."""
from __future__ import annotations

from src.domain.llm.models import LLMConfig
from src.domain.llm.provider_interface import LLMProvider
from src.infra.llm.providers.openai_chat_provider import OpenAIChatProvider
from src.infra.llm.providers.openai_response_provider import OpenAIResponseProvider
from src.infra.llm.providers.anthropic_provider import AnthropicProvider

PROVIDER_MAP: dict[str, type[LLMProvider]] = {
    "openai_chat": OpenAIChatProvider,
    "openai_response": OpenAIResponseProvider,
    "anthropic": AnthropicProvider,
}


def create_provider(config: LLMConfig) -> LLMProvider:
    """Create a provider instance based on config.provider_type."""
    provider_cls = PROVIDER_MAP.get(config.provider_type)
    if not provider_cls:
        raise ValueError(
            f"Unknown provider type: {config.provider_type}. "
            f"Supported: {list(PROVIDER_MAP.keys())}"
        )
    return provider_cls(config)
```

- [ ] **Step 4: Update `backend/src/infra/llm/providers/__init__.py`**

```python
"""LLM provider implementations."""
from src.infra.llm.providers.openai_chat_provider import OpenAIChatProvider
from src.infra.llm.providers.openai_response_provider import OpenAIResponseProvider
from src.infra.llm.providers.anthropic_provider import AnthropicProvider

__all__ = ["OpenAIChatProvider", "OpenAIResponseProvider", "AnthropicProvider"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/llm/test_provider_factory.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/infra/llm/provider_factory.py src/infra/llm/providers/__init__.py tests/infra/llm/test_provider_factory.py
git commit -m "feat(llm): add provider factory with type routing"
```

---

## Task 10: LLM Manager

**Files:**
- Create: `backend/src/infra/llm/manager.py`
- Test: `backend/tests/infra/llm/test_manager.py`

- [ ] **Step 1: Write the failing test `backend/tests/infra/llm/test_manager.py`**

```python
"""Unit tests for LLM Manager."""
from unittest.mock import MagicMock, patch
import pytest

from src.domain.llm.models import LLMConfig, TestResult
from src.domain.llm.provider_interface import LLMProvider
from src.infra.llm.manager import LLMManager


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    return repo


@pytest.fixture
def sample_config():
    return LLMConfig(
        id="cfg-1",
        name="Test GPT",
        provider_type="openai_chat",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        model="gpt-4o",
        is_default=True,
    )


def test_get_provider_returns_none_when_no_default(mock_repo):
    mock_repo.get_default_config.return_value = None
    manager = LLMManager(mock_repo)
    assert manager.get_provider() is None


def test_get_provider_returns_provider(mock_repo, sample_config):
    mock_repo.get_default_config.return_value = sample_config
    manager = LLMManager(mock_repo)
    provider = manager.get_provider()
    assert provider is not None


def test_get_provider_by_id(mock_repo, sample_config):
    mock_repo.get_decrypted_config.return_value = sample_config
    manager = LLMManager(mock_repo)
    provider = manager.get_provider("cfg-1")
    assert provider is not None
    mock_repo.get_decrypted_config.assert_called_once_with("cfg-1")


def test_get_provider_caches(mock_repo, sample_config):
    mock_repo.get_default_config.return_value = sample_config
    manager = LLMManager(mock_repo)
    p1 = manager.get_provider()
    p2 = manager.get_provider()
    assert p1 is p2  # Same instance from cache


def test_refresh_clears_cache(mock_repo, sample_config):
    mock_repo.get_default_config.return_value = sample_config
    manager = LLMManager(mock_repo)
    p1 = manager.get_provider()
    manager.refresh()
    p2 = manager.get_provider()
    assert p1 is not p2  # New instance after refresh


@pytest.mark.asyncio
async def test_test_connection_success(mock_repo, sample_config):
    mock_repo.get_decrypted_config.return_value = sample_config
    mock_provider = MagicMock(spec=LLMProvider)
    mock_provider.complete = AsyncMock(
        return_value=MagicMock(content="Hi there!", model="gpt-4o")
    )

    manager = LLMManager(mock_repo)
    with patch.object(manager, "get_provider", return_value=mock_provider):
        result = await manager.test_connection("cfg-1")
    assert result.success is True
    assert result.latency_ms is not None


@pytest.mark.asyncio
async def test_test_connection_failure(mock_repo):
    mock_repo.get_decrypted_config.return_value = None
    manager = LLMManager(mock_repo)
    result = await manager.test_connection("nonexistent")
    assert result.success is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/llm/test_manager.py -v`
Expected: FAIL

- [ ] **Step 3: Write `backend/src/infra/llm/manager.py`**

```python
"""LLM Manager — unified entry point for LLM operations."""
from __future__ import annotations

import time
from typing import Optional

from loguru import logger

from src.domain.llm.models import TestResult
from src.domain.llm.provider_interface import LLMProvider
from src.domain.llm.repository_interface import ILLMConfigRepository
from src.infra.llm.provider_factory import create_provider


class LLMManager:
    """Manages LLM provider instances with caching and lifecycle."""

    def __init__(self, repo: ILLMConfigRepository):
        self._repo = repo
        self._cache: dict[str, LLMProvider] = {}

    def get_provider(self, config_id: str | None = None) -> LLMProvider | None:
        """Get a provider instance. None=config_id → default model. Returns None if no config."""
        if config_id is not None:
            return self._get_or_create(config_id)

        # Get default config
        default = self._repo.get_default_config()
        if default is None:
            return None
        return self._get_or_create(default.id)

    def _get_or_create(self, config_id: str) -> LLMProvider | None:
        """Get from cache or create a new provider from DB config."""
        if config_id in self._cache:
            return self._cache[config_id]

        config = self._repo.get_decrypted_config(config_id)
        if config is None:
            return None

        provider = create_provider(config)
        self._cache[config_id] = provider
        return provider

    async def test_connection(self, config_id: str) -> TestResult:
        """Test a model connection by sending 'Hi' and checking response."""
        config = self._repo.get_decrypted_config(config_id)
        if config is None:
            return TestResult(success=False, message="Configuration not found")

        try:
            provider = create_provider(config)
            start = time.monotonic()
            response = await provider.complete("Hi", max_tokens=50)
            elapsed = (time.monotonic() - start) * 1000

            if response.content:
                return TestResult(
                    success=True,
                    message=f"Connected to {config.name}. Response: {response.content[:50]}",
                    latency_ms=round(elapsed, 1),
                )
            return TestResult(success=False, message="Empty response from model")
        except Exception as e:
            logger.error(f"LLM connection test failed for {config_id}: {e}")
            return TestResult(
                success=False,
                message=f"Connection failed: {str(e)[:200]}",
            )

    def refresh(self) -> None:
        """Clear provider cache. Call after config changes."""
        self._cache.clear()
        logger.debug("LLM provider cache cleared")
```

- [ ] **Step 4: Update `backend/src/infra/llm/__init__.py`**

```python
"""LLM infrastructure — providers, encryption, manager."""
from src.infra.llm.key_encryptor import KeyEncryptor, generate_fernet_key
from src.infra.llm.manager import LLMManager
from src.infra.llm.provider_factory import create_provider

__all__ = ["KeyEncryptor", "generate_fernet_key", "LLMManager", "create_provider"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/llm/test_manager.py -v`
Expected: All 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/infra/llm/manager.py src/infra/llm/__init__.py tests/infra/llm/test_manager.py
git commit -m "feat(llm): add LLMManager with caching and connection test"
```

---

## Task 11: API Layer — Router and Models

**Files:**
- Create: `backend/src/api/model/llm_config_model.py`
- Create: `backend/src/api/router/llm_config_router.py`
- Test: `backend/tests/api/test_llm_config_router.py`

- [ ] **Step 1: Write `backend/src/api/model/llm_config_model.py`**

```python
"""Request/response models for LLM config API."""
from __future__ import annotations

from typing import Literal, Any
from pydantic import BaseModel


class LLMConfigCreate(BaseModel):
    name: str
    provider_type: Literal["openai_chat", "openai_response", "anthropic"]
    base_url: str
    api_key: str
    model: str
    is_default: bool = False
    extra_params: dict[str, Any] = {}


class LLMConfigUpdate(BaseModel):
    name: str | None = None
    provider_type: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    is_default: bool | None = None
    extra_params: dict[str, Any] | None = None


class LLMConfigResponse(BaseModel):
    id: str
    name: str
    provider_type: str
    base_url: str
    api_key: str
    model: str
    is_default: bool
    extra_params: dict[str, Any]
    created_at: str | None = None
    updated_at: str | None = None


class LLMTestRequest(BaseModel):
    config_id: str | None = None


class LLMTestResponse(BaseModel):
    success: bool
    message: str
    latency_ms: float | None = None
```

- [ ] **Step 2: Write `backend/src/api/router/llm_config_router.py`**

```python
"""LLM config management API router."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.pkg.responses import ok, fail
from src.domain.llm.models import LLMConfig, MASKED_KEY
from src.infra.database.impl.llm_db import create_llm_repository
from src.infra.llm.manager import LLMManager
from src.api.model.llm_config_model import (
    LLMConfigCreate,
    LLMConfigUpdate,
    LLMConfigResponse,
    LLMTestRequest,
    LLMTestResponse,
)

router = APIRouter(prefix="/llm", tags=["llm"])

# Module-level manager instance
_repo = create_llm_repository()
_manager = LLMManager(_repo)


def _to_response(config: LLMConfig) -> LLMConfigResponse:
    return LLMConfigResponse(
        id=config.id,
        name=config.name,
        provider_type=config.provider_type,
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        is_default=config.is_default,
        extra_params=config.extra_params,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.get("/configs")
def list_configs():
    """List all LLM model configs (API keys masked)."""
    configs = _repo.list_configs()
    return ok([_to_response(c) for c in configs])


@router.post("/configs", status_code=201)
def create_config(body: LLMConfigCreate):
    """Create a new LLM model config."""
    config = LLMConfig(
        name=body.name,
        provider_type=body.provider_type,
        base_url=body.base_url,
        api_key=body.api_key,
        model=body.model,
        is_default=body.is_default,
        extra_params=body.extra_params,
    )
    created = _repo.create_config(config)
    _manager.refresh()
    return ok(_to_response(created))


@router.put("/configs/{config_id}")
def update_config(config_id: str, body: LLMConfigUpdate):
    """Update an existing LLM model config."""
    updates = body.model_dump(exclude_none=True)
    # Treat empty string api_key as "keep existing"
    if "api_key" in updates and not updates["api_key"]:
        del updates["api_key"]
    updated = _repo.update_config(config_id, updates)
    if updated is None:
        raise HTTPException(status_code=404, detail="Config not found")
    _manager.refresh()
    return ok(_to_response(updated))


@router.delete("/configs/{config_id}")
def delete_config(config_id: str):
    """Delete an LLM model config."""
    deleted = _repo.delete_config(config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Config not found")
    _manager.refresh()
    return ok({"deleted": True})


@router.put("/configs/{config_id}/default")
def set_default(config_id: str):
    """Set a config as the default model."""
    config = _repo.get_config(config_id)
    if config is None:
        raise HTTPException(status_code=404, detail="Config not found")
    _repo.set_default(config_id)
    _manager.refresh()
    return ok({"id": config_id, "is_default": True})


@router.post("/test")
async def test_connection(body: LLMTestRequest):
    """Test LLM connection by sending a simple message."""
    config_id = body.config_id
    if config_id is None:
        default = _repo.get_default_config()
        if default is None:
            return ok(LLMTestResponse(
                success=False,
                message="No default model configured. Please add and set a default model.",
            ))
        config_id = default.id

    result = await _manager.test_connection(config_id)
    return ok(LLMTestResponse(
        success=result.success,
        message=result.message,
        latency_ms=result.latency_ms,
    ))
```

- [ ] **Step 3: Write the test `backend/tests/api/test_llm_config_router.py`**

This is an integration test that requires the backend running. Mark it so it can be skipped in CI.

```python
"""API integration tests for LLM config router."""
import pytest

# These tests require a running backend
pytestmark = pytest.mark.skipif(
    not pytest.importorskip("requests", reason="requests not installed"),
    reason="Backend must be running for API tests",
)


@pytest.fixture
def api_client(api_base_url):
    """Reuse the conftest api_client fixture."""
    import requests
    class Client:
        def __init__(self, base_url):
            self.base = base_url
            self.session = requests.Session()
            self.session.headers["Content-Type"] = "application/json"
        def get(self, path, **kwargs):
            return self.session.get(f"{self.base}{path}", timeout=10, **kwargs)
        def post(self, path, json=None, **kwargs):
            return self.session.post(f"{self.base}{path}", json=json, timeout=10, **kwargs)
        def put(self, path, json=None, **kwargs):
            return self.session.put(f"{self.base}{path}", json=json, timeout=10, **kwargs)
        def delete(self, path, **kwargs):
            return self.session.delete(f"{self.base}{path}", timeout=10, **kwargs)
    return Client(api_base_url)


class TestLLMConfigRouter:

    def test_list_configs_returns_200(self, api_client):
        resp = api_client.get("/llm/configs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert isinstance(data["data"], list)

    def test_create_and_delete_config(self, api_client):
        # Create
        resp = api_client.post("/llm/configs", json={
            "name": "Test Model",
            "provider_type": "openai_chat",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test-delete-me",
            "model": "gpt-4o",
        })
        assert resp.status_code == 201
        config_id = resp.json()["data"]["id"]

        # Verify it appears in list
        resp = api_client.get("/llm/configs")
        ids = [c["id"] for c in resp.json()["data"]]
        assert config_id in ids

        # Delete
        resp = api_client.delete(f"/llm/configs/{config_id}")
        assert resp.status_code == 200

    def test_api_key_masked_in_response(self, api_client):
        resp = api_client.post("/llm/configs", json={
            "name": "Mask Test",
            "provider_type": "openai_chat",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-secret-key-123",
            "model": "gpt-4o",
        })
        data = resp.json()["data"]
        assert data["api_key"] == "****"

        # Cleanup
        api_client.delete(f"/llm/configs/{data['id']}")
```

- [ ] **Step 4: Register the router in `backend/main.py`**

Add the import at the top of `main.py` (around line 35, with other router imports):

```python
from src.api.router.llm_config_router import router as llm_config_router
```

Add the router registration (after `intel_router` line, around line 217):

```python
app.include_router(llm_config_router, prefix="/api/v1")
```

- [ ] **Step 5: Verify backend starts**

Run: `cd backend && timeout 5 .venv/bin/python main.py 2>&1 || true`
Check that no import errors appear in the output.

- [ ] **Step 6: Commit**

```bash
git add src/api/model/llm_config_model.py src/api/router/llm_config_router.py main.py tests/api/test_llm_config_router.py
git commit -m "feat(llm): add LLM config API router with CRUD and test endpoints"
```

---

## Task 12: Migrate Existing Code — Backend

**Files:**
- Modify: `backend/src/api/router/signal_router.py`
- Modify: `backend/src/domain/market/intel/processor.py`
- Modify: `backend/src/domain/market/strategy/agents/base.py`

- [ ] **Step 1: Update `backend/src/api/router/signal_router.py`**

Replace the import on line ~14:

```python
# Old: from src.llm import get_llm_client
# New:
from src.infra.llm.manager import LLMManager
from src.infra.database.impl.llm_db import create_llm_repository
```

Add module-level manager near the top of the file:

```python
_llm_manager = LLMManager(create_llm_repository())
```

In the `generate_signal` function, replace `get_llm_client()` usage:

```python
# Old:
# llm = get_llm_client()
# if not llm:
#     raise HTTPException(status_code=503, ...)

# New:
llm = _llm_manager.get_provider()
if llm is None:
    raise HTTPException(
        status_code=503,
        detail="No LLM model configured. Please add a model in Settings.",
    )
```

The `llm.chat()` / `llm.complete()` calls remain the same since the `LLMProvider` interface has the same method names. But the return type changed from `str` to `LLMResponse`, so update the response access:

```python
# Old: result = llm.chat(messages)
# New: result = await llm.chat(messages)
#      analysis_text = result.content
```

Note: The provider methods are `async`, so the route handler must also be `async def generate_signal(...)`.

- [ ] **Step 2: Update `backend/src/domain/market/intel/processor.py`**

Replace the broken `get_llm_client()` function (lines 10-22) with:

```python
def _get_llm_provider():
    """Get the default LLM provider from the unified manager."""
    try:
        from src.infra.llm.manager import LLMManager
        from src.infra.database.impl.llm_db import create_llm_repository
        _manager = LLMManager(create_llm_repository())
        return _manager.get_provider()
    except Exception:
        return None
```

In `process_unprocessed` method, update the LLM check:

```python
# Old: llm = get_llm_client()
# New:
llm = _get_llm_provider()
```

In `_process_with_llm`, update the call pattern:

```python
# Old: result = llm.chat(prompt)
# New: result = await llm.chat(prompt)
#      text = result.content
```

Note: Since `_process_with_llm` calls an async method, `process_unprocessed` and `_process_with_llm` need to become async. The scheduler already supports async jobs.

- [ ] **Step 3: Update `backend/src/domain/market/strategy/agents/base.py`**

Update the type hint on line ~58:

```python
# Old:
# def __init__(self, llm: Any, memory: Any | None = None):

# New:
from src.domain.llm.provider_interface import LLMProvider

def __init__(self, llm: LLMProvider | Any = None, memory: Any | None = None):
```

This maintains backward compatibility while adding proper typing.

- [ ] **Step 4: Verify no import errors**

Run: `cd backend && .venv/bin/python -c "from src.api.router.signal_router import router; print('signal_router OK')"`
Run: `cd backend && .venv/bin/python -c "from src.domain.market.intel.processor import NewsProcessorService; print('processor OK')"`
Run: `cd backend && .venv/bin/python -c "from src.domain.market.strategy.agents.base import Agent; print('agents OK')"`

- [ ] **Step 5: Commit**

```bash
git add src/api/router/signal_router.py src/domain/market/intel/processor.py src/domain/market/strategy/agents/base.py
git commit -m "refactor(llm): migrate signal_router, intel processor, agents to unified LLMManager"
```

---

## Task 13: MiniMax Auto-Migration

**Files:**
- Modify: `backend/main.py` (add migration in lifespan)

- [ ] **Step 1: Add MiniMax migration in `backend/main.py` lifespan**

In the lifespan function (around line 115, after `setup_scheduler(app)`), add:

```python
    # Auto-migrate MiniMax env var to llm_config table
    try:
        from src.infra.database.impl.llm_db import create_llm_repository
        _llm_repo = create_llm_repository()
        configs = _llm_repo.list_configs()
        if not configs:
            minimax_key = os.environ.get("MINIMAX_API_KEY", "")
            if minimax_key:
                from src.domain.llm.models import LLMConfig
                _llm_repo.create_config(LLMConfig(
                    name="MiniMax",
                    provider_type="openai_chat",
                    base_url="https://api.minimaxi.com/v1",
                    api_key=minimax_key,
                    model="MiniMax-M2.7",
                    is_default=True,
                ))
                logger.info("Auto-migrated MINIMAX_API_KEY to llm_config table")
    except Exception as e:
        logger.warning(f"MiniMax auto-migration failed: {e}")
```

- [ ] **Step 2: Verify backend starts**

Run: `cd backend && timeout 5 .venv/bin/python main.py 2>&1 || true`
Expected: No errors. If `MINIMAX_API_KEY` is set, should see "Auto-migrated MINIMAX_API_KEY" log.

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(llm): auto-migrate MINIMAX_API_KEY to llm_config table on first start"
```

---

## Task 14: Frontend — LLM Config Settings UI

**Files:**
- Modify: `frontend/apps/web/src/pages/Settings.tsx`
- Modify: `frontend/apps/web/src/pages/Settings.css`

- [ ] **Step 1: Rewrite the LLM section in `frontend/apps/web/src/pages/Settings.tsx`**

Replace the entire `Settings` component. Key changes:
1. Remove `STORAGE_KEY_LLM_KEY`, `llmKey`, `showLlmKey`, `llmSaved`, `saveLlmKey` state and logic
2. Add new state for LLM config CRUD
3. Replace the "AI / LLM Configuration" Card with the new LLM model config section

New state variables to add (after existing state declarations):

```typescript
  // LLM Model Config
  const [llmConfigs, setLlmConfigs] = useState<any[]>([]);
  const [llmLoading, setLlmLoading] = useState(false);
  const [showLlmModal, setShowLlmModal] = useState(false);
  const [editingConfig, setEditingConfig] = useState<any>(null);
  const [llmForm, setLlmForm] = useState({
    name: '', provider_type: 'openai_chat' as string,
    base_url: '', api_key: '', model: '', is_default: false,
  });
  const [llmTestResult, setLlmTestResult] = useState<{success: boolean; message: string; latency_ms?: number} | null>(null);
  const [llmTesting, setLlmTesting] = useState(false);
```

Add data fetching function:

```typescript
  const fetchLlmConfigs = useCallback(() => {
    setLlmLoading(true);
    fetch(`${getStoredApiBase()}/llm/configs`)
      .then(r => r.json())
      .then(j => { if (j.code === 0) setLlmConfigs(j.data); })
      .catch(() => {})
      .finally(() => setLlmLoading(false));
  }, []);
```

Add CRUD functions:

```typescript
  const saveLlmConfig = async () => {
    const url = editingConfig
      ? `${getStoredApiBase()}/llm/configs/${editingConfig.id}`
      : `${getStoredApiBase()}/llm/configs`;
    const method = editingConfig ? 'PUT' : 'POST';
    const res = await fetch(url, {
      method,
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(llmForm),
    });
    const j = await res.json();
    if (j.code === 0 || j.code === 201) {
      setShowLlmModal(false);
      setEditingConfig(null);
      fetchLlmConfigs();
    }
  };

  const deleteLlmConfig = async (id: string) => {
    if (!confirm('确定删除此模型配置？')) return;
    await fetch(`${getStoredApiBase()}/llm/configs/${id}`, {method: 'DELETE'});
    fetchLlmConfigs();
  };

  const setDefaultConfig = async (id: string) => {
    await fetch(`${getStoredApiBase()}/llm/configs/${id}/default`, {method: 'PUT'});
    fetchLlmConfigs();
  };

  const testLlmConnection = async (configId?: string) => {
    setLlmTesting(true);
    setLlmTestResult(null);
    try {
      const res = await fetch(`${getStoredApiBase()}/llm/test`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({config_id: configId || null}),
      });
      const j = await res.json();
      if (j.code === 0) {
        setLlmTestResult(j.data);
      }
    } catch (e: any) {
      setLlmTestResult({success: false, message: e.message});
    } finally {
      setLlmTesting(false);
    }
  };

  const openEditModal = (config?: any) => {
    if (config) {
      setEditingConfig(config);
      setLlmForm({
        name: config.name,
        provider_type: config.provider_type,
        base_url: config.base_url,
        api_key: '',  // Don't prefill
        model: config.model,
        is_default: config.is_default,
      });
    } else {
      setEditingConfig(null);
      setLlmForm({
        name: '', provider_type: 'openai_chat',
        base_url: '', api_key: '', model: '', is_default: false,
      });
    }
    setShowLlmModal(true);
  };
```

Add `useEffect` to fetch configs on mount:

```typescript
  useEffect(() => {
    fetchLlmConfigs();
  }, [fetchLlmConfigs]);
```

Replace the "AI / LLM Configuration" Card (lines 197-229) with:

```tsx
        {/* ── LLM Model Configuration ── */}
        <Card>
          <CardHeader>
            <CardTitle>LLM 模型配置</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="settings__llm-toolbar">
              <Button size="sm" onClick={() => openEditModal()}>+ 添加模型</Button>
              <Button variant="secondary" size="sm" onClick={() => testLlmConnection()} disabled={llmTesting}>
                {llmTesting ? '测试中...' : '测试连接'}
              </Button>
            </div>

            {llmTestResult && (
              <div className={`settings__test-msg settings__test-msg--${llmTestResult.success ? 'success' : 'error'}`}>
                {llmTestResult.message}
                {llmTestResult.latency_ms && ` (${llmTestResult.latency_ms}ms)`}
              </div>
            )}

            <div className="settings__llm-list">
              {llmConfigs.length === 0 && !llmLoading && (
                <div className="settings__llm-empty">暂无模型配置，请点击"添加模型"</div>
              )}
              {llmConfigs.map(cfg => (
                <div key={cfg.id} className="settings__llm-card">
                  <div className="settings__llm-card-header">
                    <span className="settings__llm-card-name">
                      {cfg.is_default && <span className="settings__llm-default-badge">★</span>}
                      {cfg.name}
                    </span>
                    <div className="settings__llm-card-actions">
                      {!cfg.is_default && (
                        <Button variant="secondary" size="sm" onClick={() => setDefaultConfig(cfg.id)}>
                          设为默认
                        </Button>
                      )}
                      <Button variant="secondary" size="sm" onClick={() => openEditModal(cfg)}>编辑</Button>
                      <Button variant="secondary" size="sm" onClick={() => deleteLlmConfig(cfg.id)}>删除</Button>
                    </div>
                  </div>
                  <div className="settings__llm-card-meta">
                    <span>协议: {{openai_chat: 'OpenAI Chat', openai_response: 'OpenAI Response', anthropic: 'Anthropic'}[cfg.provider_type] || cfg.provider_type}</span>
                    <span>模型: {cfg.model}</span>
                  </div>
                  <div className="settings__llm-card-url">{cfg.base_url}</div>
                </div>
              ))}
            </div>

            {/* Modal */}
            {showLlmModal && (
              <div className="settings__modal-overlay" onClick={() => setShowLlmModal(false)}>
                <div className="settings__modal" onClick={e => e.stopPropagation()}>
                  <h3 className="settings__modal-title">{editingConfig ? '编辑模型' : '添加模型'}</h3>
                  <div className="settings__field">
                    <label className="settings__label">名称</label>
                    <input className="settings__input" value={llmForm.name}
                      onChange={e => setLlmForm({...llmForm, name: e.target.value})} placeholder="GPT-4o" />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">协议</label>
                    <select className="settings__input" value={llmForm.provider_type}
                      onChange={e => setLlmForm({...llmForm, provider_type: e.target.value})}>
                      <option value="openai_chat">OpenAI Chat</option>
                      <option value="openai_response">OpenAI Response</option>
                      <option value="anthropic">Anthropic</option>
                    </select>
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">Base URL</label>
                    <input className="settings__input" value={llmForm.base_url}
                      onChange={e => setLlmForm({...llmForm, base_url: e.target.value})}
                      placeholder="https://api.openai.com/v1" />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">API Key</label>
                    <input type="password" className="settings__input" value={llmForm.api_key}
                      onChange={e => setLlmForm({...llmForm, api_key: e.target.value})}
                      placeholder={editingConfig ? '留空则保留原值' : 'sk-...'} />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">模型</label>
                    <input className="settings__input" value={llmForm.model}
                      onChange={e => setLlmForm({...llmForm, model: e.target.value})}
                      placeholder="gpt-4o" />
                  </div>
                  <div className="settings__field">
                    <label className="settings__label">
                      <input type="checkbox" checked={llmForm.is_default}
                        onChange={e => setLlmForm({...llmForm, is_default: e.target.checked})} />
                      {' '}设为默认模型
                    </label>
                  </div>
                  <div className="settings__modal-actions">
                    <Button onClick={saveLlmConfig}>保存</Button>
                    <Button variant="secondary" onClick={() => setShowLlmModal(false)}>取消</Button>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
```

Remove the `STORAGE_KEY_LLM_KEY` constant and all related state/logic.

- [ ] **Step 2: Add CSS for LLM config section to `frontend/apps/web/src/pages/Settings.css`**

Append to the end of the file:

```css
/* LLM Model Config */
.settings__llm-toolbar {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.settings__llm-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.settings__llm-empty {
  text-align: center;
  padding: 2rem;
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.settings__llm-card {
  padding: 0.75rem 1rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}

.settings__llm-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.375rem;
}

.settings__llm-card-name {
  font-weight: 600;
  font-size: 0.9375rem;
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.settings__llm-default-badge {
  color: #f0b429;
  font-size: 1rem;
}

.settings__llm-card-actions {
  display: flex;
  gap: 0.375rem;
}

.settings__llm-card-meta {
  display: flex;
  gap: 1rem;
  font-size: 0.8125rem;
  color: var(--color-text-secondary);
  margin-bottom: 0.25rem;
}

.settings__llm-card-url {
  font-size: 0.75rem;
  color: var(--color-text-secondary);
  font-family: var(--font-mono);
}

/* Modal */
.settings__modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.settings__modal {
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  padding: 1.5rem;
  width: 90%;
  max-width: 480px;
  max-height: 80vh;
  overflow-y: auto;
}

.settings__modal-title {
  font-size: 1.125rem;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 1rem;
}

.settings__modal-actions {
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
  margin-top: 1.25rem;
}

.settings select.settings__input {
  appearance: auto;
}
```

- [ ] **Step 3: Remove `x-llm-api-key` header from `frontend/apps/web/src/pages/Market.tsx`**

In `Market.tsx`, around lines 189-197, replace:

```typescript
// Old:
    const llmKey = localStorage.getItem('ytrader_llm_key') || '';
    if (!llmKey) {
      clearTimeout(timeout);
      setState('error', 'Please configure LLM API Key in Settings');
      return;
    }
    const headers = { 'x-llm-api-key': llmKey };
    fetch(`${API_BASE}/signals/generate?symbol=${symbol}`, { signal: controller.signal, headers })

// New:
    fetch(`${API_BASE}/signals/generate?symbol=${symbol}`, { signal: controller.signal })
```

- [ ] **Step 4: Verify frontend compiles**

Run: `cd frontend && pnpm --filter web build 2>&1 | tail -5`
Expected: Build succeeds with no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/apps/web/src/pages/Settings.tsx frontend/apps/web/src/pages/Settings.css frontend/apps/web/src/pages/Market.tsx
git commit -m "feat(llm): replace MiniMax localStorage key with LLM model config UI in Settings"
```

---

## Task 15: Deprecate Old LLM Client

**Files:**
- Modify: `backend/src/llm/client.py` (add deprecation warning)
- Modify: `backend/src/llm/__init__.py` (add deprecation note)

- [ ] **Step 1: Add deprecation warning to `backend/src/llm/client.py`**

Add at the top of the file, after existing docstring:

```python
import warnings
warnings.warn(
    "src.llm.client is deprecated. Use src.infra.llm.manager.LLMManager instead.",
    DeprecationWarning,
    stacklevel=2,
)
```

- [ ] **Step 2: Update `backend/src/llm/__init__.py`**

```python
"""LLM client — DEPRECATED. Use src.infra.llm.manager.LLMManager instead."""
from .client import MiniMaxClient, get_llm_client
__all__ = ["MiniMaxClient", "get_llm_client"]
```

- [ ] **Step 3: Commit**

```bash
git add src/llm/client.py src/llm/__init__.py
git commit -m "chore(llm): deprecate old MiniMaxClient in favor of unified LLMManager"
```

---

## Task 16: Final Verification

- [ ] **Step 1: Run all unit tests**

Run: `cd backend && .venv/bin/python -m pytest tests/domain/llm/ tests/infra/llm/ -v`
Expected: All PASS

- [ ] **Step 2: Run backend integration tests**

Run: `cd backend && .venv/bin/python -m pytest tests/infra/database/test_llm_db.py -v`
Expected: All PASS (requires PostgreSQL)

- [ ] **Step 3: Start backend and verify health**

Run: `cd backend && .venv/bin/python main.py &` then `sleep 3 && curl http://localhost:8001/api/v1/llm/configs`
Expected: `{"code": 0, "msg": "ok", "data": [...]}`

- [ ] **Step 4: Build frontend**

Run: `cd frontend && pnpm --filter web build`
Expected: Build succeeds

- [ ] **Step 5: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix(llm): final integration fixes"
```
