"""Database access for PostgreSQL (production) and SQLite (tests, small installs).

SQL is written once with ``?`` placeholders; the PostgreSQL driver gets
``%s``.  Schema tokens {ID} and {BLOB} are replaced per dialect.
"""

import contextlib
import os
import sqlite3
import threading


class Busy(Exception):
    """Every database connection of this worker is in use for too long."""

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id {ID}, email TEXT NOT NULL UNIQUE, name TEXT, pw_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0,
        totp_secret TEXT, totp_enabled INTEGER NOT NULL DEFAULT 0,
        failed_logins INTEGER NOT NULL DEFAULT 0, locked_until BIGINT NOT NULL DEFAULT 0,
        must_change_pw INTEGER NOT NULL DEFAULT 0,
        created_at BIGINT NOT NULL, last_login BIGINT)""",
    """CREATE TABLE IF NOT EXISTS sessions (
        id {ID}, user_id BIGINT NOT NULL, token_hash TEXT NOT NULL UNIQUE, device TEXT, ip TEXT,
        mfa INTEGER NOT NULL DEFAULT 0,
        created_at BIGINT NOT NULL, last_seen BIGINT NOT NULL, expires_at BIGINT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id)",
    """CREATE TABLE IF NOT EXISTS orgs (
        id {ID}, name TEXT NOT NULL, ice TEXT, plan TEXT, plan_until TEXT,
        seq BIGINT NOT NULL DEFAULT 0, device_seq BIGINT NOT NULL DEFAULT 0,
        storage_bytes BIGINT NOT NULL DEFAULT 0, disabled INTEGER NOT NULL DEFAULT 0,
        created_at BIGINT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS members (
        org_id BIGINT NOT NULL, user_id BIGINT NOT NULL, role TEXT NOT NULL, created_at BIGINT NOT NULL,
        PRIMARY KEY (org_id, user_id))""",
    "CREATE INDEX IF NOT EXISTS members_user ON members(user_id)",
    """CREATE TABLE IF NOT EXISTS invites (
        id {ID}, org_id BIGINT NOT NULL, code_hash TEXT NOT NULL UNIQUE, role TEXT NOT NULL,
        created_by BIGINT, expires_at BIGINT NOT NULL, used_by BIGINT, used_at BIGINT)""",
    """CREATE TABLE IF NOT EXISTS devices (
        id {ID}, org_id BIGINT NOT NULL, user_id BIGINT NOT NULL, device_no BIGINT NOT NULL,
        name TEXT, created_at BIGINT NOT NULL, last_sync BIGINT)""",
    """CREATE TABLE IF NOT EXISTS records (
        org_id BIGINT NOT NULL, tbl TEXT NOT NULL, rid TEXT NOT NULL, seq BIGINT NOT NULL,
        deleted INTEGER NOT NULL DEFAULT 0, payload TEXT, updated_at BIGINT NOT NULL,
        updated_by BIGINT, device_no BIGINT,
        PRIMARY KEY (org_id, tbl, rid))""",
    "CREATE INDEX IF NOT EXISTS records_seq ON records(org_id, seq)",
    """CREATE TABLE IF NOT EXISTS files (
        org_id BIGINT NOT NULL, sha TEXT NOT NULL, size BIGINT NOT NULL, data {BLOB} NOT NULL,
        created_at BIGINT NOT NULL, PRIMARY KEY (org_id, sha))""",
    """CREATE TABLE IF NOT EXISTS ai_usage (
        org_id BIGINT NOT NULL, month TEXT NOT NULL, kind TEXT NOT NULL, n BIGINT NOT NULL DEFAULT 0,
        PRIMARY KEY (org_id, month, kind))""",
    """CREATE TABLE IF NOT EXISTS reset_codes (
        id {ID}, user_id BIGINT NOT NULL, code_hash TEXT NOT NULL, expires_at BIGINT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS audit (
        id {ID}, ts BIGINT NOT NULL, user_id BIGINT, org_id BIGINT, action TEXT NOT NULL,
        ip TEXT, detail TEXT)""",
    "CREATE INDEX IF NOT EXISTS audit_ts ON audit(ts)",
]

DIALECT = {
    "sqlite": {"{ID}": "INTEGER PRIMARY KEY AUTOINCREMENT", "{BLOB}": "BLOB"},
    "postgres": {"{ID}": "BIGSERIAL PRIMARY KEY", "{BLOB}": "BYTEA"},
}


class DB:
    def __init__(self, url, pool_size=None):
        self.url = url
        self.kind = "postgres" if url.startswith(("postgres://", "postgresql://")) else "sqlite"
        self._lock = threading.Lock()
        self._pool = []
        # Hard cap on open connections per worker process: PostgreSQL refuses
        # clients beyond max_connections (100 by default), so requests wait
        # for a free connection instead of failing.
        self.pool_size = int(pool_size or os.environ.get("SAFQA_DB_POOL", "15"))
        self._slots = threading.BoundedSemaphore(self.pool_size)
        self._local = threading.local()
        if self.kind == "postgres":
            import importlib
            importlib.import_module("psycopg")      # fail early if the driver is missing
        self.init()

    # ------------------------------------------------------------ connections
    def _connect(self):
        if self.kind == "postgres":
            import psycopg
            from psycopg.rows import dict_row
            url = self.url.replace("postgres://", "postgresql://", 1)
            return psycopg.connect(url, row_factory=dict_row, autocommit=False)
        path = self.url[len("sqlite:///"):] if self.url.startswith("sqlite:///") else self.url
        conn = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _get(self):
        if self.kind == "sqlite":
            conn = getattr(self._local, "conn", None)
            if conn is None:
                conn = self._local.conn = self._connect()
            return conn
        if not self._slots.acquire(timeout=30):
            raise Busy()
        try:
            with self._lock:
                while self._pool:
                    conn = self._pool.pop()
                    if not conn.closed:
                        return conn
            return self._connect()
        except BaseException:
            self._slots.release()
            raise

    def _put(self, conn, broken=False):
        if self.kind == "sqlite":
            return
        try:
            if broken or conn.closed:
                with contextlib.suppress(Exception):
                    conn.close()
                return
            with self._lock:
                self._pool.append(conn)
        finally:
            self._slots.release()

    def close(self):
        with self._lock:
            pool, self._pool = self._pool, []
        for conn in pool:
            with contextlib.suppress(Exception):
                conn.close()
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.close()
            self._local.conn = None

    @contextlib.contextmanager
    def tx(self):
        """One transaction: commit on success, rollback on error."""
        conn = self._get()
        cur = Cursor(self, conn)
        broken = False
        try:
            if self.kind == "sqlite":
                conn.execute("BEGIN IMMEDIATE")
            yield cur
            conn.commit() if self.kind == "postgres" else conn.execute("COMMIT")
        except BaseException:
            try:
                conn.rollback() if self.kind == "postgres" else conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                broken = True
            raise
        finally:
            self._put(conn, broken)

    def init(self):
        with self.tx() as c:
            for stmt in SCHEMA:
                for token, value in DIALECT[self.kind].items():
                    stmt = stmt.replace(token, value)
                c.execute(stmt)


class Cursor:
    def __init__(self, db, conn):
        self.db, self.conn = db, conn

    def _sql(self, sql):
        return sql.replace("?", "%s") if self.db.kind == "postgres" else sql

    def execute(self, sql, args=()):
        if self.db.kind == "postgres":
            cur = self.conn.cursor()
            cur.execute(self._sql(sql), tuple(args))
            return cur
        return self.conn.execute(sql, tuple(args))

    def all(self, sql, args=()):
        return [dict(r) for r in self.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        row = self.execute(sql, args).fetchone()
        return dict(row) if row is not None else None

    def value(self, sql, args=()):
        row = self.one(sql, args)
        return next(iter(row.values())) if row else None
