from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.core.auth import IdentityConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONTEXA_", extra="ignore")

    app_name: str = "Contexta"
    # Explicit opt-in: this identity has full owner privileges and is local-only.
    development_owner: bool = False
    identities: list[IdentityConfig] = []
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

    @field_validator('identities')
    @classmethod
    def unique_identities(cls, identities: list[IdentityConfig]) -> list[IdentityConfig]:
        ids = [item.id for item in identities]
        digests = [item.token_sha256.get_secret_value() for item in identities]
        if len(ids) != len(set(ids)) or len(digests) != len(set(digests)) or 'development-owner' in ids:
            raise ValueError('Identity IDs and token digests must be unique and may not use the development identity ID')
        return identities

    @model_validator(mode='after')
    def exclusive_auth_modes(self):
        if self.development_owner and self.identities:
            raise ValueError('Development owner and configured identities cannot be enabled together')
        return self
