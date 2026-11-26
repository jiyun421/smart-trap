import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from flask import current_app, g

from .validation import ApiError

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
BUSY_TIMEOUT_MS = 5000


def connect(path, *, create=False):
    path = Path(path).resolve()
    mode = "rwc" if create else "rw"
    connection = sqlite3.connect(
        f"{path.as_uri()}?mode={mode}", uri=True, isolation_level=None,
        timeout=BUSY_TIMEOUT_MS / 1000,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return connection


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def detach_db():
    return g.pop("db")


@contextmanager
def transaction(connection, *, write=False):
    connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
    try:
        yield
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def apply_migrations(path):
    Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
    files = sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
    if not files:
        raise RuntimeError("No schema migrations were found")
    with closing(connect(path, create=True)) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )}
        if tables and "schema_migrations" not in tables:
            raise RuntimeError("The existing database is not managed by these migrations")
        mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if mode.lower() != "wal":
            raise RuntimeError("The database could not enable WAL mode")
        with transaction(connection, write=True):
            connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY)")
            applied = {row[0] for row in connection.execute("SELECT name FROM schema_migrations")}
            names = [file.name for file in files]
            if set(names[:len(applied)]) != applied:
                raise RuntimeError("The applied schema migrations do not match this version")
            for file in files[len(applied):]:
                statement = ""
                for line in file.read_text(encoding="utf-8").splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        connection.execute(statement)
                        statement = ""
                if statement.strip():
                    raise RuntimeError(f"Incomplete SQL in {file.name}")
                connection.execute("INSERT INTO schema_migrations (name) VALUES (?)", (file.name,))


def require_id(connection, table, field, value):
    # Table and column names come from application code. The ID is bound separately.
    row = connection.execute(f"SELECT * FROM {table} WHERE {field} = ?", (value,)).fetchone()
    if row is None:
        raise ApiError(404, "not_found", f"Unknown {field}")
    return row


def init_app(app):
    from .cli import setup_cli

    @app.teardown_appcontext
    def close_db(error):
        connection = g.pop("db", None)
        if connection is not None:
            connection.close()

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        code = getattr(error, "sqlite_errorcode", 0) & 0xFF
        name = "database_busy" if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) else "database_unavailable"
        if name == "database_unavailable":
            app.logger.error("SQLite error: %s", error)
        return {"error": {"code": name, "message": "Database temporarily unavailable"}}, 503, {
            "Retry-After": "5"
        }

    setup_cli(app)
