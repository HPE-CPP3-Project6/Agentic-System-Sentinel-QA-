"""
config.py
---------
Centralised application settings loaded from environment variables (or a .env
file). Using pydantic-settings ensures types are validated at startup and
secrets are never hard-coded into source files.

Usage:
    from config import settings
    print(settings.SECRET_KEY)

Security note:
    In production, set all values via real environment variables or a secrets
    manager. Never commit a .env file containing live secrets to version control.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # -----------------------------------------------------------------------
    # JWT Configuration
    # -----------------------------------------------------------------------
    # SECRET_KEY must be a long, random string. Generate one with:
    #   python -c "import secrets; print(secrets.token_hex(64))"
    SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION_use_a_long_random_secret_key_here"
    ALGORITHM: str = "HS256"

    # Access token lifetime in minutes (FR5: configurable inactivity timeout)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # -----------------------------------------------------------------------
    # Soft-delete undo window (US-D22/AC3)
    # -----------------------------------------------------------------------
    # Number of minutes a soft-deleted task is retained before being
    # permanently purged.
    SOFT_DELETE_UNDO_WINDOW_MINUTES: int = 30

    # -----------------------------------------------------------------------
    # CORS origins (add your frontend URL here)
    # -----------------------------------------------------------------------
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # -----------------------------------------------------------------------
    # Pydantic-settings: read values from a .env file if present
    # -----------------------------------------------------------------------
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


# Singleton instance used throughout the application
settings = Settings()
