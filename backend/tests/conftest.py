from __future__ import annotations

import base64
import os
import tempfile

TEST_DB = os.environ.get("ANM_TEST_DATABASE_URL", "postgresql+psycopg://anm:devpass@localhost:5432/anm_test")
os.environ.update({
    "ANM_ENVIRONMENT": "test",
    "ANM_DATABASE_URL": TEST_DB,
    "ANM_ENCRYPTION_KEYS": "k1:" + base64.urlsafe_b64encode(b"0" * 32).decode().rstrip("="),
    "ANM_SESSION_SECRET": "test-session-secret-which-is-long-enough-123",
    "ANM_STORAGE_BACKEND": "filesystem",
    "ANM_STORAGE_PATH": tempfile.mkdtemp(prefix="anm-test-backups-"),
    "ANM_SIMULATOR_ENABLED": "true",
    "ANM_API_DOCS_ENABLED": "true",
    "ANM_COOKIE_SECURE": "true",
    "ANM_LOGIN_RATE_PER_MINUTE": "1000",
    "ANM_POLL_CONCURRENCY": "8",
})

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.session import get_engine, session_factory  # noqa: E402

PASSWORD = "Correct-Horse-Battery-9"


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    get_settings.cache_clear()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(os.path.dirname(__file__), "..", "alembic"))
    with get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(cfg, "head")
    yield


TABLES_TO_KEEP = {"alembic_version"}


@pytest.fixture(autouse=True)
def clean_db(migrated_db):
    from app.drivers.simulator import state as st
    from app.services.bootstrap import sync_reference_data

    eng = get_engine()
    with eng.begin() as conn:
        tables = [r[0] for r in conn.execute(text(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'")) if r[0] not in TABLES_TO_KEEP]
        conn.execute(text("SET LOCAL anm.audit_retention = 'on'"))
        conn.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
    st.store.clear()
    with session_factory()() as db:
        sync_reference_data(db)
        db.commit()
    yield


@pytest.fixture
def db():
    s = session_factory()()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app, base_url="https://testserver") as c:
        yield c


def make_user(db, role: str, username: str | None = None, password: str = PASSWORD, **kw):
    from app.services.users import create_user

    u = create_user(db, None, username=username or f"{role}-user", full_name=role.title(), email=None, role=role,
                    password=password, must_change_password=kw.get("must_change_password", False))
    db.commit()
    return u


def login(client: TestClient, username: str, password: str = PASSWORD) -> dict:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return r.json()


@pytest.fixture
def as_role(client, db):
    def _as(role: str, username: str | None = None) -> TestClient:
        u = make_user(db, role, username)
        login(client, u.username)
        return client

    return _as


@pytest.fixture
def sim_switches(db):
    from app.services.simulator import seed

    def _seed(n: int = 3) -> list[int]:
        res = seed(db, n)
        db.commit()
        return res["switch_ids"]

    return _seed
