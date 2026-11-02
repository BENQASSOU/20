"""SQLite persistence (stored in the app's private data directory)."""

import json
import os
import sqlite3
import threading
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref TEXT, title TEXT, owner TEXT, location TEXT,
    amount_ttc REAL, approval_notif_date TEXT,
    delay_days INTEGER, delay_months INTEGER,
    terms_json TEXT, archived INTEGER DEFAULT 0,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER, filename TEXT, path TEXT, doc_type TEXT,
    pages INTEGER, char_count INTEGER, scanned INTEGER DEFAULT 0,
    articles_json TEXT, analysis_json TEXT, ai_status TEXT,
    uploaded_at TEXT
);
CREATE TABLE IF NOT EXISTS checklist (
    project_id INTEGER, code TEXT, present INTEGER DEFAULT 0, date TEXT, note TEXT,
    PRIMARY KEY (project_id, code)
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER, number TEXT, kind TEXT, date TEXT, effective_date TEXT,
    days INTEGER, note TEXT
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER, number TEXT, designation TEXT, unit TEXT,
    qty_contract REAL, unit_price_ht REAL, qty_executed REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS decomptes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER, number INTEGER, date TEXT, final INTEGER DEFAULT 0,
    works_ht REAL, revision_ht REAL, total_ht REAL, tva REAL, total_ttc REAL,
    retenue REAL, penalties REAL, advance_recovery REAL,
    net_cumul_ttc REAL, previous_ttc REAL, net_ttc REAL,
    submitted_date TEXT, paid_date TEXT, paid_amount REAL,
    status TEXT, detail_json TEXT
);
CREATE TABLE IF NOT EXISTS receptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER, kind TEXT, date TEXT, works_end_date TEXT,
    with_reserves INTEGER DEFAULT 0, reserves_lifted_date TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER, role TEXT, content TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS usage (month TEXT, kind TEXT, count INTEGER DEFAULT 0,
                                  PRIMARY KEY (month, kind));

CREATE TABLE IF NOT EXISTS tiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT, name TEXT, ice TEXT, rc TEXT, if_number TEXT, cnss TEXT,
    phone TEXT, email TEXT, address TEXT, city TEXT, contact TEXT, notes TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS tenders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref TEXT, title TEXT, client_id INTEGER, owner TEXT, category TEXT, location TEXT,
    estimate_ttc REAL, deposit_date TEXT, opening_date TEXT, caution_amount REAL,
    qualification TEXT, status TEXT, bid_ttc REAL, winner TEXT, winning_bid_ttc REAL,
    notes TEXT, project_id INTEGER, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER, date TEXT, category TEXT, label TEXT, supplier_id INTEGER,
    ref TEXT, amount_ht REAL, tva_pct REAL DEFAULT 20, status TEXT,
    due_date TEXT, paid_date TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS budget_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER, category TEXT, amount_ht REAL
);
CREATE TABLE IF NOT EXISTS guarantees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER, tender_id INTEGER, kind TEXT, bank_id INTEGER, ref TEXT,
    amount REAL, issue_date TEXT, expiry_date TEXT, status TEXT,
    commission_pct REAL, notes TEXT
);
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER, date TEXT, weather TEXT, workforce INTEGER, equipment TEXT,
    work_done TEXT, incidents TEXT, visitors TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER, name TEXT, start TEXT, end TEXT, progress REAL DEFAULT 0,
    responsible TEXT, notes TEXT, sort INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER, item_id INTEGER, date TEXT, qty REAL, ref TEXT, notes TEXT
);

-- Safqa Cloud: rows changed on this device and not yet sent.
CREATE TABLE IF NOT EXISTS sync_dirty (tbl TEXT, rid TEXT, v INTEGER DEFAULT 1, PRIMARY KEY (tbl, rid));
CREATE TABLE IF NOT EXISTS sync_flags (k TEXT PRIMARY KEY, v INTEGER);
INSERT OR IGNORE INTO sync_flags(k, v) VALUES ('applying', 0);
"""

# Tables shared through Safqa Cloud (parents first) and their key columns.
SYNC_TABLES = ["settings", "tiers", "projects", "tenders", "documents", "checklist", "orders", "items",
               "decomptes", "receptions", "chat", "expenses", "budget_lines", "guarantees", "journal", "tasks",
               "measurements"]
SYNC_KEYS = {"checklist": ("project_id", "code"), "settings": ("key",)}
SYNCED_SETTINGS = ("company",)          # never API keys, tokens or licence
LOCAL_COLUMNS = {"documents": ("path",)}  # device-specific, not shared
ID_RANGE = 10 ** 9


def _key_expr(table, ref):
    cols = SYNC_KEYS.get(table, ("id",))
    return " || '|' || ".join("CAST(%s.%s AS TEXT)" % (ref, c) for c in cols)


def _triggers():
    out = []
    for t in SYNC_TABLES:
        for ev, ref in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
            cond = "(SELECT v FROM sync_flags WHERE k='applying') = 0"
            if t == "settings":
                cond += " AND %s.key IN (%s)" % (ref, ",".join("'%s'" % k for k in SYNCED_SETTINGS))
            out.append("CREATE TRIGGER IF NOT EXISTS sync_%s_%s AFTER %s ON %s WHEN %s BEGIN "
                       "INSERT INTO sync_dirty(tbl, rid, v) VALUES ('%s', %s, 1) "
                       "ON CONFLICT(tbl, rid) DO UPDATE SET v = v + 1; END;"
                       % (t, ev.lower(), ev, t, cond, t, _key_expr(t, ref)))
    return "\n".join(out)

# Columns added after the first release: (table, column, declaration)
MIGRATIONS = [
    ("projects", "status", "TEXT DEFAULT 'en_cours'"),
    ("projects", "client_id", "INTEGER"),
    ("projects", "tender_id", "INTEGER"),
    ("projects", "category", "TEXT"),
    ("projects", "manager", "TEXT"),
    ("projects", "start_planned", "TEXT"),
    ("documents", "file_sha", "TEXT"),
]

JSON_FIELDS = {"terms_json": "terms", "articles_json": "articles",
               "analysis_json": "analysis", "detail_json": "detail"}

CHILD_TABLES = ("documents", "checklist", "orders", "items", "decomptes", "receptions", "chat",
                "expenses", "budget_lines", "journal", "tasks", "measurements")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.executescript(_triggers())
        self.conn.execute("UPDATE sync_flags SET v=0 WHERE k='applying'")
        self.conn.commit()
        self._cols = {}
        try:
            self.id_base = int(self.get("sync_id_base") or 0)
        except ValueError:
            self.id_base = 0

    def _migrate(self):
        for table, col, decl in MIGRATIONS:
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(%s)" % table)}
            if col not in cols:
                self.conn.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, decl))

    def close(self):
        with self._lock:
            self.conn.close()

    # ------------------------------------------------------------ helpers
    def _row(self, row):
        if row is None:
            return None
        d = dict(row)
        for col, key in JSON_FIELDS.items():
            if col in d:
                raw = d.pop(col)
                try:
                    d[key] = json.loads(raw) if raw else None
                except ValueError:
                    d[key] = None
        return d

    def _rows(self, cur):
        return [self._row(r) for r in cur.fetchall()]

    def q(self, sql, args=()):
        with self._lock:
            return self._rows(self.conn.execute(sql, args))

    def q1(self, sql, args=()):
        with self._lock:
            return self._row(self.conn.execute(sql, args).fetchone())

    def scalar(self, sql, args=()):
        with self._lock:
            row = self.conn.execute(sql, args).fetchone()
            return row[0] if row else None

    def x(self, sql, args=()):
        with self._lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    @staticmethod
    def _prep(data):
        out = {}
        for k, v in data.items():
            if k in JSON_FIELDS.values():
                col = [c for c, key in JSON_FIELDS.items() if key == k][0]
                out[col] = json.dumps(v, ensure_ascii=False) if v is not None else None
            else:
                out[k] = v
        return out

    def insert(self, table, data):
        data = self._prep(data)
        if self.id_base and "id" not in data and table not in SYNC_KEYS and table in SYNC_TABLES:
            # Each synced device writes ids in its own range: no collision across phones.
            with self._lock:
                top = self.conn.execute("SELECT MAX(id) FROM %s WHERE id > ? AND id < ?" % table,
                                        (self.id_base, self.id_base + ID_RANGE)).fetchone()[0]
            data["id"] = (top or self.id_base) + 1
        cols = ",".join(data)
        marks = ",".join("?" * len(data))
        return self.x("INSERT INTO %s (%s) VALUES (%s)" % (table, cols, marks), tuple(data.values()))

    def update(self, table, row_id, data):
        data = self._prep(data)
        if not data:
            return
        sets = ",".join("%s=?" % k for k in data)
        self.x("UPDATE %s SET %s WHERE id=?" % (table, sets), tuple(data.values()) + (row_id,))

    def save(self, table, data, row_id=None):
        if row_id:
            self.update(table, row_id, data)
            return row_id
        return self.insert(table, data)

    def get_row(self, table, row_id):
        return self.q1("SELECT * FROM %s WHERE id=?" % table, (row_id,))

    def delete(self, table, row_id):
        self.x("DELETE FROM %s WHERE id=?" % table, (row_id,))

    def all(self, table, order="id"):
        return self.q("SELECT * FROM %s ORDER BY %s" % (table, order))

    # ------------------------------------------------------------ projects
    def projects(self, include_archived=False):
        sql = "SELECT * FROM projects"
        if not include_archived:
            sql += " WHERE archived=0"
        return self.q(sql + " ORDER BY updated_at DESC, id DESC")

    def project(self, pid):
        return self.q1("SELECT * FROM projects WHERE id=?", (pid,))

    def save_project(self, data, pid=None):
        data = dict(data)
        data["updated_at"] = now()
        if pid:
            self.update("projects", pid, data)
            return pid
        data.setdefault("created_at", now())
        data.setdefault("status", "en_cours")
        return self.insert("projects", data)

    def delete_project(self, pid):
        for t in CHILD_TABLES:
            self.x("DELETE FROM %s WHERE project_id=?" % t, (pid,))
        self.x("DELETE FROM guarantees WHERE project_id=?", (pid,))
        self.x("UPDATE tenders SET project_id=NULL WHERE project_id=?", (pid,))
        self.x("DELETE FROM projects WHERE id=?", (pid,))

    def touch(self, pid):
        self.x("UPDATE projects SET updated_at=? WHERE id=?", (now(), pid))

    # ------------------------------------------------------------ children
    def children(self, table, pid, order="id"):
        return self.q("SELECT * FROM %s WHERE project_id=? ORDER BY %s" % (table, order), (pid,))

    def documents(self, pid):
        return self.children("documents", pid)

    def checklist(self, pid):
        return self.q("SELECT * FROM checklist WHERE project_id=?", (pid,))

    def set_check(self, pid, code, present, date=None, note=None):
        self.x("INSERT INTO checklist(project_id, code, present, date, note) VALUES (?,?,?,?,?) "
               "ON CONFLICT(project_id, code) DO UPDATE SET present=excluded.present, "
               "date=COALESCE(excluded.date, checklist.date), note=COALESCE(excluded.note, checklist.note)",
               (pid, code, 1 if present else 0, date, note))

    def bundle(self, pid):
        """Everything the risk engine and screens need for a project."""
        return {
            "project": self.project(pid),
            "documents": self.documents(pid),
            "checklist": self.checklist(pid),
            "orders": self.children("orders", pid, "date, id"),
            "items": self.children("items", pid, "id"),
            "decomptes": self.children("decomptes", pid, "number"),
            "receptions": self.children("receptions", pid, "date"),
            "expenses": self.children("expenses", pid, "date DESC, id DESC"),
            "budget": self.children("budget_lines", pid, "id"),
            "journal": self.children("journal", pid, "date DESC, id DESC"),
            "tasks": self.children("tasks", pid, "sort, start, id"),
            "measurements": self.children("measurements", pid, "date DESC, id DESC"),
            "guarantees": self.q("SELECT * FROM guarantees WHERE project_id=? ORDER BY issue_date", (pid,)),
        }

    def recompute_item(self, item_id):
        """Executed quantity of a price item = sum of its measurements."""
        total = self.scalar("SELECT COALESCE(SUM(qty), 0) FROM measurements WHERE item_id=?", (item_id,))
        self.x("UPDATE items SET qty_executed=? WHERE id=?", (total or 0, item_id))
        return total

    # ------------------------------------------------------------ tiers
    def tiers(self, kind=None):
        if kind:
            return self.q("SELECT * FROM tiers WHERE kind=? ORDER BY name COLLATE NOCASE", (kind,))
        return self.q("SELECT * FROM tiers ORDER BY kind, name COLLATE NOCASE")

    def tier_name(self, tier_id):
        if not tier_id:
            return ""
        return self.scalar("SELECT name FROM tiers WHERE id=?", (tier_id,)) or ""

    # ------------------------------------------------------------ chat
    def chat_history(self, pid, limit=40):
        rows = self.q("SELECT * FROM chat WHERE project_id=? ORDER BY id DESC LIMIT ?", (pid, limit))
        return list(reversed(rows))

    def add_chat(self, pid, role, content):
        return self.insert("chat", {"project_id": pid, "role": role, "content": content,
                                    "created_at": now()})

    # ------------------------------------------------------------ settings / usage
    def get(self, key, default=None):
        row = self.q1("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set(self, key, value):
        self.x("INSERT INTO settings(key, value) VALUES (?, ?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def get_json(self, key, default=None):
        raw = self.get(key)
        if not raw:
            return default
        try:
            return json.loads(raw)
        except ValueError:
            return default

    def set_json(self, key, value):
        self.set(key, json.dumps(value, ensure_ascii=False))

    def usage(self, kind, month=None):
        month = month or datetime.now().strftime("%Y-%m")
        row = self.q1("SELECT count FROM usage WHERE month=? AND kind=?", (month, kind))
        return row["count"] if row else 0

    def bump_usage(self, kind, month=None):
        month = month or datetime.now().strftime("%Y-%m")
        self.x("INSERT INTO usage(month, kind, count) VALUES (?, ?, 1) "
               "ON CONFLICT(month, kind) DO UPDATE SET count=count+1", (month, kind))

    # ------------------------------------------------------------ backup
    def backup_bytes(self):
        """Consistent copy of the database file (for export)."""
        import tempfile
        with self._lock:
            fd, tmp = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            try:
                dst = sqlite3.connect(tmp)
                with dst:
                    self.conn.backup(dst)
                dst.close()
                with open(tmp, "rb") as fh:
                    return fh.read()
            finally:
                os.remove(tmp)

    # ------------------------------------------------------------ Safqa Cloud sync
    def columns(self, table):
        if table not in self._cols:
            with self._lock:
                self._cols[table] = [r[1] for r in self.conn.execute("PRAGMA table_info(%s)" % table)]
        return self._cols[table]

    def set_id_base(self, device_no):
        self.id_base = int(device_no or 0) * ID_RANGE
        self.set("sync_id_base", str(self.id_base))

    def sync_pending(self):
        return self.scalar("SELECT COUNT(*) FROM sync_dirty") or 0

    def _where_key(self, table, rid):
        cols = SYNC_KEYS.get(table, ("id",))
        parts = rid.split("|", len(cols) - 1)
        if len(parts) != len(cols):
            return None, None
        return " AND ".join("CAST(%s AS TEXT)=?" % c for c in cols), parts

    def sync_take(self, limit=500):
        """Pending local changes, as sent to the server."""
        out = []
        with self._lock:
            dirty = self.conn.execute("SELECT tbl, rid, v FROM sync_dirty LIMIT ?", (limit,)).fetchall()
            for tbl, rid, v in dirty:
                where, args = self._where_key(tbl, rid)
                row = self.conn.execute("SELECT * FROM %s WHERE %s" % (tbl, where), args).fetchone() if where else None
                item = {"t": tbl, "id": rid, "v": v}
                if row is None:
                    item["deleted"] = True
                else:
                    d = dict(row)
                    for c in LOCAL_COLUMNS.get(tbl, ()):
                        d.pop(c, None)
                    item["d"] = d
                out.append(item)
        return out

    def sync_done(self, items):
        with self._lock:
            for it in items:
                self.conn.execute("DELETE FROM sync_dirty WHERE tbl=? AND rid=? AND v=?", (it["t"], it["id"], it["v"]))
            self.conn.commit()

    def sync_apply(self, changes):
        """Write rows received from the server without marking them dirty."""
        order = {t: i for i, t in enumerate(SYNC_TABLES)}
        changes = sorted(changes, key=lambda c: (bool(c.get("deleted")), order.get(c.get("t"), 99)))
        with self._lock:
            try:
                self.conn.execute("UPDATE sync_flags SET v=1 WHERE k='applying'")
                for ch in changes:
                    t = ch.get("t")
                    if t not in order:
                        continue
                    if t == "settings" and str(ch.get("id")) not in SYNCED_SETTINGS:
                        continue
                    where, args = self._where_key(t, str(ch.get("id")))
                    if not where:
                        continue
                    if ch.get("deleted"):
                        self.conn.execute("DELETE FROM %s WHERE %s" % (t, where), args)
                        continue
                    cols = self.columns(t)
                    d = {k: v for k, v in (ch.get("d") or {}).items() if k in cols and k not in LOCAL_COLUMNS.get(t, ())}
                    if not d:
                        continue
                    keep = LOCAL_COLUMNS.get(t, ())
                    if keep:
                        old = self.conn.execute("SELECT %s FROM %s WHERE %s" % (",".join(keep), t, where), args).fetchone()
                        if old:
                            d.update(dict(zip(keep, old)))
                    self.conn.execute("INSERT OR REPLACE INTO %s (%s) VALUES (%s)" % (
                        t, ",".join(d), ",".join("?" * len(d))), tuple(d.values()))
                self.conn.execute("UPDATE sync_flags SET v=0 WHERE k='applying'")
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    def sync_local_write(self, sql, args=()):
        """Device-only bookkeeping (e.g. a downloaded file path): not sent."""
        with self._lock:
            try:
                self.conn.execute("UPDATE sync_flags SET v=1 WHERE k='applying'")
                self.conn.execute(sql, args)
                self.conn.execute("UPDATE sync_flags SET v=0 WHERE k='applying'")
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    def sync_mark_all(self):
        """Queue every shared row (first device of a new company space)."""
        with self._lock:
            for t in SYNC_TABLES:
                # (an INSERT ... SELECT needs a WHERE before ON CONFLICT in SQLite)
                where = " WHERE key IN (%s)" % ",".join("'%s'" % k for k in SYNCED_SETTINGS) if t == "settings" else " WHERE 1"
                self.conn.execute("INSERT INTO sync_dirty(tbl, rid, v) SELECT '%s', %s, 1 FROM %s%s "
                                  "ON CONFLICT(tbl, rid) DO UPDATE SET v = v + 1"
                                  % (t, _key_expr(t, t), t, where))
            self.conn.commit()

    def sync_wipe(self):
        """Remove shared data from this device (before loading a company space)."""
        with self._lock:
            try:
                self.conn.execute("UPDATE sync_flags SET v=1 WHERE k='applying'")
                for t in SYNC_TABLES:
                    if t == "settings":
                        self.conn.execute("DELETE FROM settings WHERE key IN (%s)" %
                                          ",".join("'%s'" % k for k in SYNCED_SETTINGS))
                    else:
                        self.conn.execute("DELETE FROM %s" % t)
                self.conn.execute("DELETE FROM sync_dirty")
                self.conn.execute("UPDATE sync_flags SET v=0 WHERE k='applying'")
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    def is_empty(self):
        return not self.scalar("SELECT COUNT(*) FROM projects") and not self.scalar("SELECT COUNT(*) FROM tenders")


def restore_backup(path, data):
    """Validate a database file and write it to `path` (caller reopens)."""
    import tempfile
    if not data.startswith(b"SQLite format 3\x00"):
        raise ValueError("Ce fichier n'est pas une sauvegarde Safqa valide.")
    fd, tmp = tempfile.mkstemp(suffix=".db")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    try:
        conn = sqlite3.connect(tmp)
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        if "projects" not in tables or "settings" not in tables:
            raise ValueError("Ce fichier n'est pas une sauvegarde Safqa valide.")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
