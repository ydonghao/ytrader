"""
pytest fixtures for ytrader tests
"""
import os
import sys
import pytest
from typing import Generator

# Ensure backend root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Force test environment variables before any imports
os.environ.setdefault('YTRADER_ENV', 'test')
os.environ.setdefault('LOG_LEVEL', 'error')


@pytest.fixture(scope='session')
def backend_root() -> str:
    return os.path.join(os.path.dirname(__file__), '..')


@pytest.fixture(scope='session')
def db_dsn() -> str:
    """Use the real local dev DB for integration tests."""
    env_dsn = os.environ.get('YTRADER_DB_DSN')
    if env_dsn:
        return env_dsn
    sys.path.insert(
        0, os.path.join(os.path.dirname(__file__), '..', 'src')
    )
    from pkg.utils.db_dsn import load_db_dsn
    return load_db_dsn()


@pytest.fixture(scope='session')
def db_connection(db_dsn):
    """Session-scoped raw psycopg2 connection for direct DB queries."""
    import psycopg2
    conn = psycopg2.connect(db_dsn)
    yield conn
    conn.close()


@pytest.fixture
def db_cursor(db_connection):
    """Function-scoped cursor that rolls back after each test."""
    cursor = db_connection.cursor()
    yield cursor
    db_connection.rollback()
    cursor.close()


@pytest.fixture(scope='session')
def api_base_url() -> str:
    return os.environ.get('YTRADER_API_BASE', 'http://localhost:8001/api/v1')


@pytest.fixture(scope='session')
def http_session(api_base_url) -> Generator:
    """requests.Session for HTTP API calls."""
    import requests
    session = requests.Session()
    session.headers.update({'Content-Type': 'application/json'})
    session.headers.update({'Accept': 'application/json'})
    session.base_url = api_base_url
    yield session
    session.close()


@pytest.fixture
def api_client(api_base_url):
    """Lightweight helper: makes get/post/delete calls against the real API."""
    import requests
    class Client:
        def __init__(self, base_url):
            self.base = base_url
            self.session = requests.Session()
            self.session.headers['Content-Type'] = 'application/json'
            self.session.headers['Accept'] = 'application/json'

        def get(self, path, **kwargs) -> requests.Response:
            return self.session.get(f'{self.base}{path}', timeout=10, **kwargs)

        def post(self, path, json=None, **kwargs) -> requests.Response:
            return self.session.post(f'{self.base}{path}', json=json, timeout=10, **kwargs)

        def delete(self, path, **kwargs) -> requests.Response:
            return self.session.delete(f'{self.base}{path}', timeout=10, **kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.session.close()

    with Client(api_base_url) as client:
        yield client
