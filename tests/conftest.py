"""
Shared pytest fixtures.

The suite depends on a materialized database schema. Previously each module relied on
whichever test happened to call init_db() first, which made the suite order-dependent
and broke whenever an individual test was deselected. Schema creation is now an
explicit, idempotent, session-scoped concern.

The database is also isolated from the developer's working copy. Tests used to run against
`satguard.db` itself, so rows survived between runs: a stale `RUNNING` monitoring run made
later runs report a phantom "concurrent run in progress", and a leftover risk assessment
made a test that asserts "no assessment exists" fail on a machine that had run the suite
before. Every session now gets a throwaway database.
"""

import os

import pytest

from satguard.db import session as db_session_module
from satguard.db.session import init_db


@pytest.fixture(scope="session", autouse=True)
def isolated_database(tmp_path_factory):
    """
    Point the session at a temporary database for the whole test run.

    Runs before anything can call `get_engine()`, so the cached engine is discarded and any
    previously imported value of `raw_db_url` is ignored.
    """
    db_path = tmp_path_factory.mktemp("satguard-db") / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"

    db_session_module.raw_db_url = os.environ["DATABASE_URL"]
    db_session_module.engine = None
    db_session_module.SessionLocal = None

    yield

    os.environ.pop("DATABASE_URL", None)
    db_session_module.raw_db_url = None
    db_session_module.engine = None
    db_session_module.SessionLocal = None


@pytest.fixture(scope="session", autouse=True)
def initialized_database(isolated_database):
    """Create and seed the database schema once for the whole test session."""
    init_db()
    yield