from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONTEXA_", extra="ignore")

    app_name: str = "Contexta"
    # Explicit opt-in: this identity has full owner privileges and is local-only.
    development_owner: bool = False
    metadata_url: SecretStr | None = None
    # Entries are exact host:port pairs controlled by the operator.
    allowed_destinations: list[str] = []
    allow_insecure_local_sources: bool = False
    source_sslrootcert: str | None = None
    # Deployment-wide calendar for the local prototype; not yet per metric.
    reporting_timezone: str = 'UTC'
    # Explicit opt-in to send bounded catalog metadata to the local model.
    local_ai_onboarding: bool = False
    local_ai_chat: bool = False

    @field_validator('reporting_timezone')
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('reporting_timezone must be an IANA time zone') from None
        return value
