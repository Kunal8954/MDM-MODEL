"""
satguard/config.py
Configuration loader for SATGUARD platform.
Integrates environment variables with config/data_sources.yaml.
"""

import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml
from dotenv import load_dotenv

# Load .env file from project root if it exists
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def load_yaml_config() -> Dict[str, Any]:
    yaml_path = PROJECT_ROOT / "config" / "data_sources.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"Configuration file not found at {yaml_path}")
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


class Settings:
    def __init__(self):
        self.yaml_config = load_yaml_config()

        # CDSE Credentials
        self.CDSE_CLIENT_ID: Optional[str] = os.getenv("CDSE_CLIENT_ID")
        self.CDSE_CLIENT_SECRET: Optional[str] = os.getenv("CDSE_CLIENT_SECRET")
        self.CDSE_S3_ACCESS_KEY: Optional[str] = os.getenv("CDSE_S3_ACCESS_KEY")
        self.CDSE_S3_SECRET_KEY: Optional[str] = os.getenv("CDSE_S3_SECRET_KEY")
        self.CDSE_S3_ENDPOINT: str = os.getenv(
            "CDSE_S3_ENDPOINT_URL", "https://eodata.dataspace.copernicus.eu"
        )

        # NASA Earthdata (GPM)
        self.EARTHDATA_USERNAME: Optional[str] = os.getenv("EARTHDATA_USERNAME")
        self.EARTHDATA_PASSWORD: Optional[str] = os.getenv("EARTHDATA_PASSWORD")

        # NASA FIRMS
        self.FIRMS_MAP_KEY: Optional[str] = os.getenv("FIRMS_MAP_KEY")

        # Groq API
        self.GROQ_API_KEY: Optional[str] = os.getenv("GROQ_API_KEY")
        self.GROQ_PRIMARY_MODEL: str = os.getenv("GROQ_PRIMARY_MODEL", "llama-3.3-70b-versatile")
        self.GROQ_FALLBACK_MODEL: str = os.getenv("GROQ_FALLBACK_MODEL", "mixtral-8x7b-32768")

        # OpenStreetMap
        self.OSM_USER_AGENT: str = os.getenv(
            "OSM_USER_AGENT", "SATGUARD-GeoIntelligence/1.0 (satguard-monitoring@domain.gov)"
        )
        self.OSM_OVERPASS_URL: str = os.getenv(
            "OSM_OVERPASS_URL", "https://overpass-api.de/api/interpreter"
        )

        # Database
        self.DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")

        # Phase 7: Continuous Monitoring & Automated Reassessment
        self.MONITORING_ENABLED: bool = os.getenv("MONITORING_ENABLED", "true").lower() in ("true", "1", "yes")
        self.DEFAULT_MONITORING_INTERVAL_HOURS: float = float(os.getenv("DEFAULT_MONITORING_INTERVAL_HOURS", "24.0"))
        self.MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
        self.RETRY_BACKOFF_SECONDS: float = float(os.getenv("RETRY_BACKOFF_SECONDS", "2.0"))
        self.OBSERVATION_LOOKBACK_DAYS: int = int(os.getenv("OBSERVATION_LOOKBACK_DAYS", "15"))
        self.CATALOG_QUERY_WINDOW_DAYS: int = int(os.getenv("CATALOG_QUERY_WINDOW_DAYS", "40"))
        self.LOCK_TIMEOUT_MINUTES: float = float(os.getenv("LOCK_TIMEOUT_MINUTES", "30.0"))

        # Phase 10: Production Hardening, Security, Deployment & Scale
        self.SATGUARD_ENV: str = os.getenv("SATGUARD_ENV", "development").lower()
        self.JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "satguard-default-dev-secret-key-change-in-production-32chars")
        self.JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
        self.ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
        
        # CORS
        raw_cors = os.getenv("CORS_ALLOWED_ORIGINS", "")
        if raw_cors:
            self.CORS_ALLOWED_ORIGINS: List[str] = [orig.strip() for orig in raw_cors.split(",") if orig.strip()]
        else:
            self.CORS_ALLOWED_ORIGINS: List[str] = [
                "http://localhost:5173",
                "http://localhost:3000",
                "http://127.0.0.1:5173",
                "http://127.0.0.1:3000",
            ] if self.SATGUARD_ENV != "production" else []

        # API & Security Middleware
        self.SECURITY_HEADERS_ENABLED: bool = os.getenv("SECURITY_HEADERS_ENABLED", "true").lower() in ("true", "1", "yes")
        self.RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() in ("true", "1", "yes")
        self.RATE_LIMIT_REQUESTS_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "120"))
        self.AUDIT_LOGGING_ENABLED: bool = os.getenv("AUDIT_LOGGING_ENABLED", "true").lower() in ("true", "1", "yes")
        self.EXTERNAL_TIMEOUT_SECONDS: float = float(os.getenv("EXTERNAL_TIMEOUT_SECONDS", "30.0"))

    def get_critical_locations(self) -> List[Dict[str, Any]]:
        return self.yaml_config.get("critical_locations", [])


settings = Settings()
