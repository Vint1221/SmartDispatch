from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def client(tmp_path):
    db_file = tmp_path / "test_dispatch.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.database.session as db_sess
    import app.models.db_models  # noqa: F401
    from app.main import app
    from app.services.dispatch_service import dispatch_service

    test_engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    db_sess.engine = test_engine
    db_sess.SessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    db_sess.Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = db_sess.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[db_sess.get_db] = override_get_db
    dispatch_service.clear_cache()

    with TestClient(app) as tc:
        yield tc

    app.dependency_overrides.clear()
    dispatch_service.clear_cache()
    test_engine.dispose()
