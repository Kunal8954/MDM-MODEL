"""
satguard/db/session.py
Database connection manager and session factory for SATGUARD.
Connects to PostgreSQL/PostGIS when available, with automatic SQLite fallback for local developer setups.
"""

import os
import logging
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from satguard.models.entities import Base

logger = logging.getLogger("satguard.db")
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Derive database URL
raw_db_url = os.getenv("DATABASE_URL")

engine = None
SessionLocal = None


def get_engine():
    global engine, SessionLocal
    if engine is not None:
        return engine

    # Try configured database first
    if raw_db_url and raw_db_url.startswith("postgresql"):
        try:
            test_engine = create_engine(
                raw_db_url,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
                pool_recycle=1800,
                connect_args={"connect_timeout": 5},
            )
            with test_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Connected to PostgreSQL database successfully.")
            engine = test_engine
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            return engine
        except Exception as e:
            logger.warning(f"PostgreSQL connection refused or unavailable ({e}). Falling back to local SQLite database.")

    # Local SQLite fallback
    sqlite_path = PROJECT_ROOT / "satguard.db"
    sqlite_url = f"sqlite:///{sqlite_path.as_posix()}"
    engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    logger.info(f"Initialized local database at {sqlite_url}")
    return engine


def init_db():
    eng = get_engine()
    Base.metadata.create_all(bind=eng)
    
    # Ensure critical_locations has Phase 7 continuous monitoring columns
    with eng.connect() as conn:
        try:
            from sqlalchemy import inspect
            insp = inspect(eng)
            existing_cols = {c["name"] for c in insp.get_columns("critical_locations")}
            
            new_columns = [
                ("monitoring_interval_hours", "FLOAT DEFAULT 24.0"),
                ("last_successful_run", "TIMESTAMP"),
                ("last_attempted_run", "TIMESTAMP"),
                ("next_scheduled_run", "TIMESTAMP"),
                ("last_observation_check", "TIMESTAMP"),
                ("monitoring_status", "VARCHAR(30) DEFAULT 'ACTIVE'")
            ]
            
            for col_name, col_type in new_columns:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE critical_locations ADD COLUMN {col_name} {col_type}"))
                    logger.info(f"Added column {col_name} to critical_locations table.")
            
            # Phase 10: Create performance indexes idempotently
            indexes_to_create = [
                "CREATE INDEX IF NOT EXISTS idx_sat_obs_loc_time ON satellite_observations (location_id, acquisition_time)",
                "CREATE INDEX IF NOT EXISTS idx_s1_change_loc_time ON sentinel1_change_detections (location_id, t2_acquisition_time)",
                "CREATE INDEX IF NOT EXISTS idx_risk_loc_time ON risk_assessments (location_id, created_at)",
                "CREATE INDEX IF NOT EXISTS idx_alerts_loc_status ON alerts (location_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_mon_runs_loc_status ON monitoring_runs (location_id, status)",
                "CREATE INDEX IF NOT EXISTS idx_hist_snap_loc_time ON historical_analytics_snapshots (location_id, created_at)",
                "CREATE INDEX IF NOT EXISTS idx_audit_actor_time ON audit_logs (actor, timestamp)",
            ]
            for idx_stmt in indexes_to_create:
                try:
                    conn.execute(text(idx_stmt))
                except Exception:
                    pass

            conn.commit()
        except Exception as e:
            logger.warning(f"Note during schema sync: {e}")

    # Seed default government accounts if empty
    session = get_db_session()
    try:
        from satguard.security.auth import seed_default_users
        seed_default_users(session)
    finally:
        session.close()

    logger.info("Database schema initialized and hardened.")


def get_db_session() -> Session:
    if SessionLocal is None:
        get_engine()
    return SessionLocal()

