from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./smart_dispatch.db"
    team_name: str = "Smart Dispatch"
    app_version: str = "1.0.0"
    api_prefix: str = "/api/v1"
    max_body_bytes: int = 104_857_600  # 100 MB
    default_tz_offset_hours: int = 5  # Yekaterinburg UTC+5
    solver_max_time_sec: int = 300
    replan_time_budget_sec: float = 2.5  # fast margin well under 10s event limit


settings = Settings()
