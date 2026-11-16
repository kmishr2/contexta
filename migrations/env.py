from alembic import context
from sqlalchemy import create_engine, pool

from app.catalog.models import Base
from app.core.settings import Settings

config = context.config
settings = Settings()
if settings.metadata_url is None:
    raise RuntimeError("CONTEXA_METADATA_URL is required for migrations")
url = settings.metadata_url.get_secret_value()
if not url.startswith("postgresql+psycopg://"):
    raise RuntimeError("Metadata URL must use postgresql+psycopg")

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
