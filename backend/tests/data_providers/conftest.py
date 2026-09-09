"""
conftest.py - pytest configuration for data_providers tests

Both test files use 'from src.domain.market.X' imports.
We must prevent src/__init__.py from executing its 'from . import api' side effect.

Solution:
  Add backend/src/domain/ FIRST → 'market' resolves here ✓
                    backend/ SECOND → 'src' falls back to backend/src/ ✓
  Python searches for 'src' in backend/src/domain/src/ first (not found),
  then falls back to backend/src/ for 'src'.
  'market' is found in backend/src/domain/market/ ✓
"""
import sys
import os

backend_dir = os.path.join(os.path.dirname(__file__), "..", "..")  # backend/
backend_domain = os.path.join(backend_dir, "src", "domain")  # backend/src/domain/

for p in [backend_domain, backend_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)
