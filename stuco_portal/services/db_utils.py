import re

from sqlalchemy import inspect, text

from ..extensions import db


def ensure_schema_updates():
    inspector = inspect(db.engine)
    table_names = set(inspector.get_table_names())
    schema_updates = {
        "users": [
            ("password_hash", "VARCHAR(255)"),
            ("created_at", "DATETIME"),
            ("last_login_at", "DATETIME"),
            ("is_active", "BOOLEAN"),
        ],
        "feedback": [
            ("created_at", "DATETIME"),
        ],
        "teachers": [
            ("is_active", "BOOLEAN"),
        ],
    }
    with db.engine.begin() as connection:
        for table, columns in schema_updates.items():
            if table not in table_names:
                continue
            existing_columns = {col["name"] for col in inspector.get_columns(table)}
            for column_name, column_type in columns:
                if column_name in existing_columns:
                    continue
                try:
                    connection.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}")
                    )
                    print(f"INFO: Added column '{column_name}' to '{table}'.")
                except Exception as exc:
                    print(
                        f"WARNING: Could not add column '{column_name}' to '{table}': {exc}"
                    )


def normalize_slug(value):
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9\\s-]", "", value)
    value = re.sub(r"\\s+", "-", value)
    return value[:50]
