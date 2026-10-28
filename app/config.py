from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_KEY: str
    EVOLUTION_API_URL: str = "http://localhost:8080"
    EVOLUTION_API_KEY: str
    EVOLUTION_INSTANCE: str = "bot-avance-checklist"

    class Config:
        env_file = ".env"

settings = Settings()