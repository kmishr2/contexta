import hashlib
import json
import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from app.catalog.models import ConnectionRecord
from app.core.settings import Settings


class SourcePolicyError(Exception):
    pass


class ScopeAccessError(SourcePolicyError):
    def __init__(self, schema: str):
        self.schema = schema
        super().__init__('A scoped schema is unavailable to the source role')


def source_engine(record: ConnectionRecord, settings: Settings):
    if f"{record.host}:{record.port}" not in settings.allowed_destinations:
        raise SourcePolicyError("Destination is not approved")
    password = os.environ.get(record.credential_ref)
    if not password:
        raise SourcePolicyError("Source credential is unavailable")
    local = record.host in {"127.0.0.1", "localhost", "::1"}
    if settings.allow_insecure_local_sources and local:
        options = {"sslmode": "disable"}
    else:
        if not settings.source_sslrootcert:
            raise SourcePolicyError("A TLS trust root is required")
        options = {"sslmode": "verify-full", "sslrootcert": settings.source_sslrootcert}
    options["connect_timeout"] = "5"
    url = URL.create("postgresql+psycopg", username=record.username, password=password,
                     host=record.host, port=record.port, database=record.database, query=options)
    return create_engine(url, poolclass=NullPool, hide_parameters=True)


def inspect_source(record: ConnectionRecord, settings: Settings, *, discover: bool):
    engine = source_engine(record, settings)
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text("SET LOCAL statement_timeout = '5s'"))
                conn.execute(text("SET LOCAL lock_timeout = '1s'"))
                conn.execute(text("SET LOCAL search_path = pg_catalog"))
                identity = conn.execute(text("SELECT current_database(), current_user")).one()
                for schema in record.schemas:
                    allowed = conn.execute(text("SELECT COALESCE(has_schema_privilege(current_user, oid, 'USAGE'), false) FROM pg_namespace WHERE nspname = :schema"), {"schema": schema}).scalar_one_or_none()
                    if not allowed:
                        raise ScopeAccessError(schema)
                if not discover:
                    return {"database": identity[0], "role": identity[1]}
                inspector = inspect(conn)
                objects = []
                for schema in sorted(record.schemas):
                    names = [(n, "table") for n in inspector.get_table_names(schema=schema)]
                    names += [(n, "view") for n in inspector.get_view_names(schema=schema)]
                    for name, kind in sorted(names):
                        readable = conn.execute(text("""SELECT has_table_privilege(current_user, c.oid, 'SELECT')
                            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE n.nspname = :schema AND c.relname = :name"""), {"schema": schema, "name": name}).scalar_one_or_none()
                        if not readable:
                            continue
                        columns = inspector.get_columns(name, schema=schema)
                        pk = inspector.get_pk_constraint(name, schema=schema)
                        uniques = inspector.get_unique_constraints(name, schema=schema)
                        fks = inspector.get_foreign_keys(name, schema=schema)
                        comment = inspector.get_table_comment(name, schema=schema).get("text")
                        definition = inspector.get_view_definition(name, schema=schema) if kind == "view" else None
                        objects.append({"schema": schema, "name": name, "kind": kind, "comment": comment,
                            "columns": [{"name": c["name"], "type": str(c["type"]), "nullable": c["nullable"], "comment": c.get("comment")} for c in columns],
                            "primary_key": pk.get("constrained_columns") or [],
                            "unique_keys": sorted([u["column_names"] for u in uniques]),
                            "foreign_keys": [{"columns": f["constrained_columns"], "referred_schema": f.get("referred_schema") or schema,
                                              "referred_table": f["referred_table"], "referred_columns": f["referred_columns"], "origin": "declared"}
                                             for f in fks if (f.get("referred_schema") or schema) in record.schemas],
                            "view_definition_hash": hashlib.sha256(definition.encode()).hexdigest() if definition else None})
                visible = {(o["schema"], o["name"]) for o in objects}
                for obj in objects:
                    obj["foreign_keys"] = [f for f in obj["foreign_keys"] if (f["referred_schema"], f["referred_table"]) in visible]
                    obj["foreign_keys"].sort(key=lambda f: (f["referred_schema"], f["referred_table"], f["columns"]))
                catalog = {"objects": objects}
                fingerprint = hashlib.sha256(json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                return catalog, fingerprint
    finally:
        engine.dispose()
