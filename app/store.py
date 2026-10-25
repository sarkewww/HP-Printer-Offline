"""SQLite 持久化层（``app/data/hp_offline.db``，自动创建）。

线程安全策略
------------
* 每个线程持有自己的连接（``threading.local``），避免 sqlite3 的跨线程限制；
* WAL + ``busy_timeout=15000`` 让并发读写自动排队，不需要全局大锁；
* 只有「首次建表」用进程级锁保护。

表结构
------
printers  已保存打印机（含缓存的能力 JSON）
jobs      打印 / 扫描任务
scans     扫描结果文件
uploads   打印上传的临时文件（token 映射）
settings  键值设置
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, Iterable, List, Optional

from . import DATA_DIR, get_logger

log = get_logger("store")

DB_PATH = os.path.join(DATA_DIR, "hp_offline.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS printers (
    id            TEXT PRIMARY KEY,
    name          TEXT,
    queue_name    TEXT,
    model         TEXT,
    host          TEXT NOT NULL,
    serial        TEXT,
    firmware      TEXT,
    uuid          TEXT,
    hostname      TEXT,
    is_default    INTEGER NOT NULL DEFAULT 0,
    last_seen     INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL DEFAULT 0,
    capabilities  TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL,
    printer_id    TEXT,
    title         TEXT,
    state         TEXT NOT NULL DEFAULT 'queued',
    progress      REAL NOT NULL DEFAULT 0,
    pages_total   INTEGER NOT NULL DEFAULT 0,
    pages_sent    INTEGER NOT NULL DEFAULT 0,
    message       TEXT DEFAULT '',
    error         TEXT,
    options       TEXT,
    ipp_job_id    INTEGER,
    created_at    INTEGER NOT NULL DEFAULT 0,
    updated_at    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        INTEGER,
    printer_id    TEXT,
    format        TEXT,
    path          TEXT NOT NULL,
    width         INTEGER NOT NULL DEFAULT 0,
    height        INTEGER NOT NULL DEFAULT 0,
    size          INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS uploads (
    token         TEXT PRIMARY KEY,
    name          TEXT,
    kind          TEXT,
    pages         INTEGER NOT NULL DEFAULT 1,
    size          INTEGER NOT NULL DEFAULT 0,
    path          TEXT NOT NULL,
    created_at    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key           TEXT PRIMARY KEY,
    value         TEXT
);

CREATE TABLE IF NOT EXISTS shortcuts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    icon          TEXT NOT NULL DEFAULT 'scan',
    steps         TEXT NOT NULL DEFAULT '[]',
    scan_options  TEXT NOT NULL DEFAULT '{}',
    created_at    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_scans_created ON scans(created_at DESC);
"""

DEFAULT_SETTINGS: Dict[str, Any] = {
    "theme": "light",
    "accent": "#0096D6",
    "language": "zh-CN",
    "save_dir": os.path.join(os.path.expanduser("~"), "Pictures", "HP Offline"),
    "auto_discover": True,
    "poll_interval": 10,
    "default_printer": "",
    "offline_mode": True,
    # --- 本地邮件（不经 HP 服务器）---
    "smtp_host": "",
    "smtp_port": 465,
    "smtp_tls": True,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "",
    "mail_to": "",
}

PRINTER_FIELDS = (
    "id",
    "name",
    "queue_name",
    "model",
    "host",
    "serial",
    "firmware",
    "uuid",
    "hostname",
    "is_default",
    "last_seen",
    "created_at",
    "capabilities",
)


class Store:
    """SQLite 封装。所有方法都可以从任意线程调用。"""

    def __init__(self, path: str = DB_PATH):
        self.path = path
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        self._local = threading.local()
        self._schema_lock = threading.Lock()
        self._ensure_schema()

    # -- 连接 -------------------------------------------------------------
    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=15.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=15000")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            self._local.conn = None

    def _ensure_schema(self) -> None:
        with self._schema_lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # -- 通用 -------------------------------------------------------------
    def _execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        cursor = self.conn.execute(sql, tuple(params))
        self.conn.commit()
        return cursor

    def _query(self, sql: str, params: Iterable[Any] = ()) -> List[sqlite3.Row]:
        return list(self.conn.execute(sql, tuple(params)).fetchall())

    # =====================================================================
    # 打印机
    # =====================================================================
    @staticmethod
    def _printer_row(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        raw_caps = data.get("capabilities")
        try:
            data["capabilities"] = json.loads(raw_caps) if raw_caps else {}
        except (TypeError, ValueError):
            data["capabilities"] = {}
        data["is_default"] = bool(data.get("is_default"))
        return data

    def list_printers(self) -> List[Dict[str, Any]]:
        rows = self._query(
            "SELECT * FROM printers ORDER BY is_default DESC, created_at ASC"
        )
        return [self._printer_row(row) for row in rows]

    def get_printer(self, printer_id: str) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM printers WHERE id = ?", (printer_id,))
        return self._printer_row(rows[0]) if rows else None

    def find_printer_by_host(self, host: str) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM printers WHERE host = ?", (host,))
        return self._printer_row(rows[0]) if rows else None

    def find_printer_by_uuid(self, uuid_value: str) -> Optional[Dict[str, Any]]:
        rows = self._query(
            "SELECT * FROM printers WHERE lower(uuid) = lower(?)", (uuid_value,)
        )
        return self._printer_row(rows[0]) if rows else None

    def default_printer(self) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM printers WHERE is_default = 1 LIMIT 1")
        if rows:
            return self._printer_row(rows[0])
        printers = self.list_printers()
        return printers[0] if printers else None

    def upsert_printer(self, data: Dict[str, Any]) -> Dict[str, Any]:
        now = int(time.time())
        printer_id = data.get("id") or data.get("uuid") or data.get("host")
        if not printer_id:
            raise ValueError("打印机缺少 id/uuid/host")
        existing = self.get_printer(printer_id)
        capabilities = data.get("capabilities")
        caps_json = json.dumps(capabilities, ensure_ascii=False) if capabilities is not None else None

        if existing is None:
            self._execute(
                """INSERT INTO printers
                   (id, name, queue_name, model, host, serial, firmware, uuid, hostname,
                    is_default, last_seen, created_at, capabilities)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    printer_id,
                    data.get("name") or data.get("model") or "HP 打印机",
                    data.get("queue_name"),
                    data.get("model"),
                    data.get("host"),
                    data.get("serial"),
                    data.get("firmware"),
                    (data.get("uuid") or "").lower() or None,
                    data.get("hostname"),
                    1 if data.get("is_default") else (0 if self.list_printers() else 1),
                    int(data.get("last_seen") or now),
                    now,
                    caps_json,
                ),
            )
        else:
            merged = {
                "name": data.get("name") or existing.get("name"),
                "queue_name": data.get("queue_name") or existing.get("queue_name"),
                "model": data.get("model") or existing.get("model"),
                "host": data.get("host") or existing.get("host"),
                "serial": data.get("serial") or existing.get("serial"),
                "firmware": data.get("firmware") or existing.get("firmware"),
                "uuid": (data.get("uuid") or existing.get("uuid") or "").lower() or None,
                "hostname": data.get("hostname") or existing.get("hostname"),
                "last_seen": int(data.get("last_seen") or now),
            }
            self._execute(
                """UPDATE printers SET name=?, queue_name=?, model=?, host=?, serial=?,
                   firmware=?, uuid=?, hostname=?, last_seen=?, capabilities=?
                   WHERE id=?""",
                (
                    merged["name"],
                    merged["queue_name"],
                    merged["model"],
                    merged["host"],
                    merged["serial"],
                    merged["firmware"],
                    merged["uuid"],
                    merged["hostname"],
                    merged["last_seen"],
                    caps_json if caps_json is not None else existing.get("capabilities") and
                    json.dumps(existing["capabilities"], ensure_ascii=False),
                    printer_id,
                ),
            )
        return self.get_printer(printer_id)  # type: ignore[return-value]

    def update_printer_host(self, printer_id: str, host: str) -> None:
        self._execute("UPDATE printers SET host = ? WHERE id = ?", (host, printer_id))

    def touch_printer(self, printer_id: str) -> None:
        self._execute(
            "UPDATE printers SET last_seen = ? WHERE id = ?", (int(time.time()), printer_id)
        )

    def delete_printer(self, printer_id: str) -> bool:
        cursor = self._execute("DELETE FROM printers WHERE id = ?", (printer_id,))
        return cursor.rowcount > 0

    def set_default_printer(self, printer_id: str) -> None:
        self._execute("UPDATE printers SET is_default = 0", ())
        self._execute("UPDATE printers SET is_default = 1 WHERE id = ?", (printer_id,))

    # =====================================================================
    # 任务
    # =====================================================================
    @staticmethod
    def _job_row(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        try:
            data["options"] = json.loads(data["options"]) if data.get("options") else {}
        except (TypeError, ValueError):
            data["options"] = {}
        return data

    def create_job(
        self,
        kind: str,
        printer_id: str,
        title: str,
        pages_total: int = 0,
        options: Optional[Dict[str, Any]] = None,
        state: str = "queued",
        message: str = "任务已创建",
    ) -> int:
        now = int(time.time())
        cursor = self._execute(
            """INSERT INTO jobs (kind, printer_id, title, state, progress, pages_total,
                                 pages_sent, message, error, options, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                kind,
                printer_id,
                title,
                state,
                0.0,
                int(pages_total),
                0,
                message,
                None,
                json.dumps(options or {}, ensure_ascii=False),
                now,
                now,
            ),
        )
        return int(cursor.lastrowid)

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return self._job_row(rows[0]) if rows else None

    def list_jobs(self, limit: int = 50, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 50), 500))
        if kind:
            rows = self._query(
                "SELECT * FROM jobs WHERE kind = ? ORDER BY id DESC LIMIT ?", (kind, limit)
            )
        else:
            rows = self._query("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
        return [self._job_row(row) for row in rows]

    def update_job(self, job_id: int, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "state",
            "progress",
            "pages_total",
            "pages_sent",
            "message",
            "error",
            "ipp_job_id",
            "printer_id",
            "title",
        }
        pairs = [(key, value) for key, value in fields.items() if key in allowed]
        if not pairs:
            return
        assignments = ", ".join("%s = ?" % key for key, _ in pairs)
        params = [value for _, value in pairs] + [int(time.time()), job_id]
        self._execute(
            "UPDATE jobs SET %s, updated_at = ? WHERE id = ?" % assignments, params
        )

    # =====================================================================
    # 扫描结果
    # =====================================================================
    def add_scan(
        self,
        job_id: int,
        printer_id: str,
        fmt: str,
        path: str,
        width: int,
        height: int,
        size: int,
    ) -> int:
        cursor = self._execute(
            """INSERT INTO scans (job_id, printer_id, format, path, width, height, size, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (job_id, printer_id, fmt, path, int(width), int(height), int(size), int(time.time())),
        )
        return int(cursor.lastrowid)

    def get_scan(self, scan_id: int) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM scans WHERE id = ?", (scan_id,))
        return dict(rows[0]) if rows else None

    def list_scans(self, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 50), 500))
        rows = self._query("SELECT * FROM scans ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in rows]

    def delete_scan(self, scan_id: int) -> Optional[Dict[str, Any]]:
        scan = self.get_scan(scan_id)
        if scan is None:
            return None
        self._execute("DELETE FROM scans WHERE id = ?", (scan_id,))
        return scan

    # =====================================================================
    # 上传
    # =====================================================================
    def add_upload(
        self, token: str, name: str, kind: str, pages: int, size: int, path: str
    ) -> None:
        self._execute(
            """INSERT OR REPLACE INTO uploads (token, name, kind, pages, size, path, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (token, name, kind, int(pages), int(size), path, int(time.time())),
        )

    def get_upload(self, token: str) -> Optional[Dict[str, Any]]:
        rows = self._query("SELECT * FROM uploads WHERE token = ?", (token,))
        return dict(rows[0]) if rows else None

    def list_uploads(self) -> List[Dict[str, Any]]:
        rows = self._query("SELECT * FROM uploads ORDER BY created_at DESC")
        return [dict(row) for row in rows]

    def prune_uploads(self, max_age_seconds: int = 24 * 3600) -> List[str]:
        """删除过期上传记录，返回被删除的文件路径。"""
        cutoff = int(time.time()) - max_age_seconds
        rows = self._query("SELECT * FROM uploads WHERE created_at < ?", (cutoff,))
        paths = [row["path"] for row in rows]
        self._execute("DELETE FROM uploads WHERE created_at < ?", (cutoff,))
        return paths

    # =====================================================================
    # 设置
    # =====================================================================
    # ------------------------------------------------------------------
    # 快捷方式（本地替代官方云端 Smart Tasks）
    # ------------------------------------------------------------------
    def list_shortcuts(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM shortcuts ORDER BY id"
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["steps"] = json.loads(item.get("steps") or "[]")
            except (TypeError, ValueError):
                item["steps"] = []
            try:
                item["scan_options"] = json.loads(item.get("scan_options") or "{}")
            except (TypeError, ValueError):
                item["scan_options"] = {}
            result.append(item)
        return result

    def get_shortcut(self, shortcut_id: int) -> Optional[Dict[str, Any]]:
        for item in self.list_shortcuts():
            if item["id"] == shortcut_id:
                return item
        return None

    def add_shortcut(self, name: str, icon: str, steps: List[str],
                     scan_options: Dict[str, Any]) -> int:
        cursor = self.conn.execute(
            "INSERT INTO shortcuts (name, icon, steps, scan_options, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (name, icon or "scan", json.dumps(steps, ensure_ascii=False),
             json.dumps(scan_options or {}, ensure_ascii=False), int(time.time())),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def delete_shortcut(self, shortcut_id: int) -> None:
        self.conn.execute("DELETE FROM shortcuts WHERE id = ?", (shortcut_id,))
        self.conn.commit()

    def get_settings(self) -> Dict[str, Any]:
        result = dict(DEFAULT_SETTINGS)
        for row in self._query("SELECT key, value FROM settings"):
            try:
                result[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                result[row["key"]] = row["value"]
        return result

    def patch_settings(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in patch.items():
            if key not in DEFAULT_SETTINGS:
                continue
            self._execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )
        return self.get_settings()

    # =====================================================================
    # 维护
    # =====================================================================
    def stats(self) -> Dict[str, int]:
        def _count(sql: str) -> int:
            rows = self._query(sql)
            return int(rows[0][0]) if rows else 0

        return {
            "printers": _count("SELECT COUNT(*) FROM printers"),
            "jobs": _count("SELECT COUNT(*) FROM jobs"),
            "scans": _count("SELECT COUNT(*) FROM scans"),
        }
