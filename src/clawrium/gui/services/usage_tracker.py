"""Token usage tracking with SQLite.

Provides a lightweight local store for chat token usage events.
Database is stored at ~/.config/clawrium/usage.db.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clawrium.core.config import get_config_dir
from clawrium.gui.services.pricing import estimate_cost

logger = logging.getLogger(__name__)

USAGE_DB = "usage.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    agent_key       TEXT NOT NULL,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_tokens   INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens    INTEGER NOT NULL,
    estimated_cost  REAL,
    session_id      TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_usage_agent ON usage_events(agent_key);
CREATE INDEX IF NOT EXISTS idx_usage_model ON usage_events(model);
"""


class UsageTracker:
    """SQLite-backed token usage tracker."""

    def __init__(self, db_path: Path | None = None):
        self._db_path = db_path or (get_config_dir() / USAGE_DB)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def record_usage(
        self,
        agent_key: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        session_id: str | None = None,
    ) -> int:
        """Record a token usage event.

        Returns the event ID.
        """
        total_tokens = prompt_tokens + completion_tokens
        cost = estimate_cost(model, prompt_tokens, completion_tokens)
        timestamp = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            cursor = conn.execute(
                """INSERT INTO usage_events
                   (timestamp, agent_key, provider, model, prompt_tokens,
                    completion_tokens, total_tokens, estimated_cost, session_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp,
                    agent_key,
                    provider,
                    model,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    cost,
                    session_id,
                ),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def get_summary(self, days: int = 30) -> dict[str, Any]:
        """Get aggregate usage summary for the last N days."""
        cutoff = _days_ago(days)
        with self._connect() as conn:
            row = conn.execute(
                """SELECT
                     COUNT(*) as total_events,
                     COALESCE(SUM(prompt_tokens), 0) as total_prompt,
                     COALESCE(SUM(completion_tokens), 0) as total_completion,
                     COALESCE(SUM(total_tokens), 0) as total_tokens,
                     COALESCE(SUM(estimated_cost), 0) as total_cost
                   FROM usage_events
                   WHERE timestamp >= ?""",
                (cutoff,),
            ).fetchone()

            return {
                "period_days": days,
                "total_events": row["total_events"],
                "total_prompt_tokens": row["total_prompt"],
                "total_completion_tokens": row["total_completion"],
                "total_tokens": row["total_tokens"],
                "total_cost": round(row["total_cost"], 4),
            }

    def get_history(self, days: int = 30, granularity: str = "day") -> list[dict]:
        """Get time-series usage data grouped by time bucket.

        Args:
            days: Number of days to look back
            granularity: 'day' or 'hour'
        """
        cutoff = _days_ago(days)
        if granularity == "hour":
            date_fmt = "%Y-%m-%dT%H:00:00"
        else:
            date_fmt = "%Y-%m-%d"

        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT
                      strftime('{date_fmt}', timestamp) as bucket,
                      SUM(prompt_tokens) as prompt_tokens,
                      SUM(completion_tokens) as completion_tokens,
                      SUM(total_tokens) as total_tokens,
                      SUM(estimated_cost) as cost,
                      COUNT(*) as events
                    FROM usage_events
                    WHERE timestamp >= ?
                    GROUP BY bucket
                    ORDER BY bucket""",
                (cutoff,),
            ).fetchall()

            return [
                {
                    "timestamp": row["bucket"],
                    "prompt_tokens": row["prompt_tokens"],
                    "completion_tokens": row["completion_tokens"],
                    "total_tokens": row["total_tokens"],
                    "cost": round(row["cost"], 4) if row["cost"] else 0,
                    "events": row["events"],
                }
                for row in rows
            ]

    def get_by_agent(self, days: int = 30) -> list[dict]:
        """Get per-agent usage breakdown."""
        cutoff = _days_ago(days)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT
                     agent_key,
                     SUM(total_tokens) as total_tokens,
                     SUM(estimated_cost) as total_cost,
                     COUNT(*) as events,
                     MAX(timestamp) as last_used
                   FROM usage_events
                   WHERE timestamp >= ?
                   GROUP BY agent_key
                   ORDER BY total_tokens DESC""",
                (cutoff,),
            ).fetchall()

            return [
                {
                    "agent_key": row["agent_key"],
                    "total_tokens": row["total_tokens"],
                    "total_cost": round(row["total_cost"], 4)
                    if row["total_cost"]
                    else 0,
                    "events": row["events"],
                    "last_used": row["last_used"],
                }
                for row in rows
            ]

    def clear(self) -> int:
        """Delete all usage data. Returns number of rows deleted."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM usage_events")
            return cursor.rowcount

    def export_all(self, days: int = 365) -> list[tuple]:
        """Export all usage rows as tuples for CSV export."""
        cutoff = _days_ago(days)
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT timestamp, agent_key, provider, model,
                          prompt_tokens, completion_tokens, total_tokens,
                          estimated_cost, session_id
                   FROM usage_events
                   WHERE timestamp >= ?
                   ORDER BY timestamp DESC""",
                (cutoff,),
            ).fetchall()
            return [tuple(row) for row in rows]

    def get_db_path(self) -> str:
        """Return the database file path."""
        return str(self._db_path)


def _days_ago(days: int) -> str:
    """Get ISO timestamp for N days ago."""
    from datetime import timedelta

    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.isoformat()


# Singleton instance (lazy-initialized)
_tracker: UsageTracker | None = None


def get_usage_tracker() -> UsageTracker:
    """Get or create the global usage tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker
