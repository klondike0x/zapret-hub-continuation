from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any


KNOWLEDGE_DIR_NAME = "orchestrator_knowledge"
KNOWLEDGE_MAX_BYTES = 500 * 1024 * 1024  # 500 MB hard cap
_MAX_BYTES = KNOWLEDGE_MAX_BYTES


def knowledge_dir(data_dir: Path) -> Path:
    return Path(data_dir) / KNOWLEDGE_DIR_NAME


class KnowledgeStore:
    """SQLite-backed knowledge store with 500MB hard cap and score/LRU eviction.

    Only the orchestrator thread should read/write. GUI never loads the whole store.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db_path = self.root / "knowledge.sqlite"
        self._legacy_migrated = self.root / ".sqlite_migrated"
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        self._migrate_legacy_json_if_needed()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS winners (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    score REAL NOT NULL DEFAULT 1.0,
                    updated_at REAL NOT NULL,
                    accessed_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS situations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conflicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app TEXT NOT NULL,
                    ts REAL NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ranked_generals (
                    general_id TEXT PRIMARY KEY,
                    score REAL NOT NULL DEFAULT 0.0
                );
                CREATE TABLE IF NOT EXISTS dead_hosts (
                    host TEXT PRIMARY KEY,
                    until_ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS cooldowns (
                    key TEXT PRIMARY KEY,
                    until_ts REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS last_known_good (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    saved_at REAL NOT NULL
                );
                """
            )
            self._conn.commit()

    def _migrate_legacy_json_if_needed(self) -> None:
        if self._legacy_migrated.exists():
            return
        winners_path = self.root / "winners.json"
        if winners_path.exists():
            try:
                data = json.loads(winners_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for key, payload in data.items():
                        if isinstance(payload, dict):
                            self.set_winner(str(key), payload)
            except Exception:
                pass
        generals_path = self.root / "ranked_generals.json"
        if generals_path.exists():
            try:
                data = json.loads(generals_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for gid, score in data.items():
                        self.rank_general(str(gid), float(score))
            except Exception:
                pass
        try:
            self._legacy_migrated.write_text("1", encoding="utf-8")
        except Exception:
            pass

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass

    def size_bytes(self) -> int:
        total = 0
        with self._lock:
            for path in self.root.rglob("*"):
                if path.is_file():
                    try:
                        total += path.stat().st_size
                    except OSError:
                        continue
        return total

    def enforce_cap(self) -> None:
        with self._lock:
            size = self.size_bytes()
            if size <= _MAX_BYTES * 0.92:
                return
            # Evict situations first (low value), then low-score winners, then old conflicts.
            self._conn.execute(
                "DELETE FROM situations WHERE id NOT IN (SELECT id FROM situations ORDER BY ts DESC LIMIT 500)"
            )
            self._conn.execute("DELETE FROM dead_hosts WHERE until_ts < ?", (time.time(),))
            self._conn.execute("DELETE FROM cooldowns WHERE until_ts < ?", (time.time(),))
            self._conn.commit()
            size = self.size_bytes()
            if size > _MAX_BYTES * 0.92:
                self._conn.execute(
                    """
                    DELETE FROM winners WHERE key NOT IN (
                        SELECT key FROM winners ORDER BY score DESC, accessed_at DESC LIMIT 400
                    )
                    """
                )
                self._conn.commit()
            size = self.size_bytes()
            if size > _MAX_BYTES:
                self._conn.execute(
                    "DELETE FROM conflicts WHERE id NOT IN (SELECT id FROM conflicts ORDER BY ts DESC LIMIT 200)"
                )
                self._conn.commit()
            size = self.size_bytes()
            if size > _MAX_BYTES:
                # Keep top generals only.
                rows = self._conn.execute(
                    "SELECT general_id, score FROM ranked_generals ORDER BY score DESC"
                ).fetchall()
                for row in rows[40:]:
                    self._conn.execute(
                        "DELETE FROM ranked_generals WHERE general_id = ?", (row["general_id"],)
                    )
                self._conn.commit()
            # VACUUM only when still over hard cap (expensive).
            if self.size_bytes() > _MAX_BYTES:
                try:
                    self._conn.execute("VACUUM")
                except Exception:
                    pass

    def get_winner(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM winners WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            try:
                value = json.loads(row["payload"])
            except Exception:
                return None
            if not isinstance(value, dict):
                return None
            now = time.time()
            value["accessed_at"] = now
            self._conn.execute(
                "UPDATE winners SET payload = ?, accessed_at = ? WHERE key = ?",
                (json.dumps(value, ensure_ascii=False), now, key),
            )
            self._conn.commit()
            return dict(value)

    def set_winner(self, key: str, payload: dict[str, Any]) -> None:
        with self._lock:
            record = dict(payload)
            now = time.time()
            record["updated_at"] = now
            record["accessed_at"] = now
            score = float(payload.get("score", 1.0) or 1.0)
            record["score"] = score
            self._conn.execute(
                """
                INSERT INTO winners(key, payload, score, updated_at, accessed_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    payload=excluded.payload,
                    score=excluded.score,
                    updated_at=excluded.updated_at,
                    accessed_at=excluded.accessed_at
                """,
                (key, json.dumps(record, ensure_ascii=False), score, now, now),
            )
            self._conn.commit()
            self.enforce_cap()

    def winner_for_host(self, host: str) -> dict[str, Any] | None:
        return self.get_winner(f"host:{host.lower()}")

    def winner_for_app(self, app: str) -> dict[str, Any] | None:
        return self.get_winner(f"app:{app.lower()}")

    def set_host_winner(self, host: str, payload: dict[str, Any]) -> None:
        self.set_winner(f"host:{host.lower()}", payload)

    def set_app_winner(self, app: str, payload: dict[str, Any]) -> None:
        self.set_winner(f"app:{app.lower()}", payload)

    def record_situation(self, payload: dict[str, Any]) -> None:
        with self._lock:
            record = dict(payload)
            ts = time.time()
            record["ts"] = ts
            self._conn.execute(
                "INSERT INTO situations(ts, payload) VALUES(?, ?)",
                (ts, json.dumps(record, ensure_ascii=False)),
            )
            self._conn.commit()
            self.enforce_cap()

    def recent_situations(self, limit: int = 40) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM situations ORDER BY ts DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in reversed(rows):
                try:
                    item = json.loads(row["payload"])
                except Exception:
                    continue
                if isinstance(item, dict):
                    out.append(item)
            return out

    def record_conflict(self, payload: dict[str, Any]) -> None:
        with self._lock:
            record = dict(payload)
            ts = time.time()
            record["ts"] = ts
            app = str(record.get("app") or "unknown")
            self._conn.execute(
                "INSERT INTO conflicts(app, ts, payload) VALUES(?, ?, ?)",
                (app, ts, json.dumps(record, ensure_ascii=False)),
            )
            self._conn.commit()
            self.enforce_cap()

    def find_conflict(self, app_key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM conflicts WHERE lower(app) = lower(?) ORDER BY ts DESC LIMIT 1",
                (app_key,),
            ).fetchone()
            if row is None:
                return None
            try:
                item = json.loads(row["payload"])
            except Exception:
                return None
            return item if isinstance(item, dict) else None

    def recent_conflicts(self, limit: int = 80) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM conflicts ORDER BY ts DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                try:
                    item = json.loads(row["payload"])
                except Exception:
                    continue
                if isinstance(item, dict):
                    out.append(item)
            return out

    def rank_general(self, general_id: str, score_delta: float) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT score FROM ranked_generals WHERE general_id = ?",
                (general_id,),
            ).fetchone()
            current = float(row["score"]) if row else 0.0
            self._conn.execute(
                """
                INSERT INTO ranked_generals(general_id, score) VALUES(?, ?)
                ON CONFLICT(general_id) DO UPDATE SET score = excluded.score
                """,
                (general_id, current + float(score_delta)),
            )
            self._conn.commit()

    def ranked_generals(self) -> list[tuple[str, float]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT general_id, score FROM ranked_generals ORDER BY score DESC"
            ).fetchall()
            return [(str(r["general_id"]), float(r["score"])) for r in rows]

    def mark_dead_host(self, host: str, ttl_s: float = 900.0) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO dead_hosts(host, until_ts) VALUES(?, ?)
                ON CONFLICT(host) DO UPDATE SET until_ts = excluded.until_ts
                """,
                (host.lower(), time.time() + ttl_s),
            )
            self._conn.commit()

    def is_dead_host(self, host: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT until_ts FROM dead_hosts WHERE host = ?",
                (host.lower(),),
            ).fetchone()
            if row is None:
                return False
            until = float(row["until_ts"])
            if until < time.time():
                self._conn.execute("DELETE FROM dead_hosts WHERE host = ?", (host.lower(),))
                self._conn.commit()
                return False
            return True

    def set_cooldown(self, key: str, ttl_s: float = 600.0) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO cooldowns(key, until_ts) VALUES(?, ?)
                ON CONFLICT(key) DO UPDATE SET until_ts = excluded.until_ts
                """,
                (key.lower(), time.time() + ttl_s),
            )
            self._conn.commit()

    def on_cooldown(self, key: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT until_ts FROM cooldowns WHERE key = ?",
                (key.lower(),),
            ).fetchone()
            if row is None:
                return False
            until = float(row["until_ts"])
            if until < time.time():
                self._conn.execute("DELETE FROM cooldowns WHERE key = ?", (key.lower(),))
                self._conn.commit()
                return False
            return True

    def save_last_known_good(self, payload: dict[str, Any]) -> None:
        with self._lock:
            record = dict(payload)
            saved_at = time.time()
            record["saved_at"] = saved_at
            self._conn.execute(
                """
                INSERT INTO last_known_good(id, payload, saved_at) VALUES(1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload, saved_at = excluded.saved_at
                """,
                (json.dumps(record, ensure_ascii=False), saved_at),
            )
            self._conn.commit()

    def load_last_known_good(self) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM last_known_good WHERE id = 1").fetchone()
            if row is None:
                return {}
            try:
                item = json.loads(row["payload"])
            except Exception:
                return {}
            return item if isinstance(item, dict) else {}

    def clear(self) -> None:
        with self._lock:
            for table in (
                "winners",
                "situations",
                "conflicts",
                "ranked_generals",
                "dead_hosts",
                "cooldowns",
                "last_known_good",
            ):
                self._conn.execute(f"DELETE FROM {table}")
            self._conn.commit()
