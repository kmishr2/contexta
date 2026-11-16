from pydantic import SecretStr
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
