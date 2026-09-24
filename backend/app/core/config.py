from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Thinker"
    environment: str = "development"
    debug: bool = True

    llm_provider: str = "gemini"

    llm_provider_chain: str | None = None

    llm_provider_simple: str | None = None
    llm_provider_simple_chain: str | None = None
    llm_provider_planner: str | None = None
    llm_provider_planner_chain: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-120b"

    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-chat"

    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_site_url: str | None = None
    openrouter_app_name: str | None = None

    database_url: str = "postgresql+asyncpg://thinker:thinker@localhost:5432/thinker"

    telegram_bot_token: str | None = None

    # Origin frontend yang boleh memanggil API ini (dipisah koma untuk lebih dari satu,
    # sama seperti pola LLM_PROVIDER_CHAIN). Default: Vite dev server lokal.
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]  # pydantic-settings mengisi field wajib dari .env saat runtime