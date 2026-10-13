from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://workstation:workstation@localhost:5432/workstation_lab"
    dashboard_origin: str = "http://localhost:5173"
    max_ingestion_bytes: int = 5 * 1024 * 1024
    rerun_artifacts_root: Path = Path("artifacts/reruns")


@lru_cache
def get_settings() -> Settings:
    return Settings()

