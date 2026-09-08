from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Thinker"
    environment: str = "development"
    debug: bool = True

    gemini_api_key: str
    gemini_model: str = "gemini-3.5-flash"
    database_url: str = "postgresql+asyncpg://thinker:thinker@localhost:5433/thinker"

    telegram_bot_token: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings mengisi field wajib dari .env saat runtime
