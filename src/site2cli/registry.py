"""Site registry backed by SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from site2cli.models import (
    AuthType,
    HealthStatus,
    SiteAction,
    SiteEntry,
    Tier,
)


class SiteRegistry:
    """SQLite-backed registry of discovered sites and their capabilities."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._create_tables()
        return self._conn

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sites (
                domain TEXT PRIMARY KEY,
                base_url TEXT NOT NULL,
                description TEXT DEFAULT '',
                auth_type TEXT DEFAULT 'none',
                openapi_spec_path TEXT,
                client_module_path TEXT,
                discovered_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                health TEXT DEFAULT 'unknown'
            );

            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_domain TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                tier TEXT DEFAULT 'browser',
                endpoint_json TEXT,
                workflow_id TEXT,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                last_used TEXT,
                last_checked TEXT,
                health TEXT DEFAULT 'unknown',
                FOREIGN KEY (site_domain) REFERENCES sites(domain),
                UNIQUE(site_domain, name)
            );

            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,
                site_domain TEXT NOT NULL,
                action_name TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                parameters_json TEXT DEFAULT '[]',
                recorded_at TEXT NOT NULL,
                replay_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                FOREIGN KEY (site_domain) REFERENCES sites(domain)
            );
        """)

    def add_site(self, site: SiteEntry) -> None:
        now = datetime.utcnow().isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO sites
               (domain, base_url, description, auth_type, openapi_spec_path,
                client_module_path, discovered_at, updated_at, health)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                site.domain,
                site.base_url,
                site.description,
                site.auth_type.value,
                site.openapi_spec_path,
                site.client_module_path,
                site.discovered_at.isoformat(),
                now,
                site.health.value,
            ),
        )
        for action in site.actions:
            self._add_action(site.domain, action)
        self.conn.commit()

    def _add_action(self, domain: str, action: SiteAction) -> None:
        endpoint_json = action.endpoint.model_dump_json() if action.endpoint else None
        self.conn.execute(
            """INSERT OR REPLACE INTO actions
               (site_domain, name, description, tier, endpoint_json, workflow_id,
                success_count, failure_count, last_used, last_checked, health)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                domain,
                action.name,
                action.description,
                action.tier.value,
                endpoint_json,
                action.workflow_id,
                action.success_count,
                action.failure_count,
                action.last_used.isoformat() if action.last_used else None,
                action.last_checked.isoformat() if action.last_checked else None,
                action.health.value,
            ),
        )

    def get_site(self, domain: str) -> SiteEntry | None:
        row = self.conn.execute(
            "SELECT * FROM sites WHERE domain = ?", (domain,)
        ).fetchone()
        if not row:
            return None
        actions = self._get_actions(domain)
        return SiteEntry(
            domain=row["domain"],
            base_url=row["base_url"],
            description=row["description"],
            auth_type=AuthType(row["auth_type"]),
            openapi_spec_path=row["openapi_spec_path"],
            client_module_path=row["client_module_path"],
            discovered_at=datetime.fromisoformat(row["discovered_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            health=HealthStatus(row["health"]),
            actions=actions,
        )

    def _get_actions(self, domain: str) -> list[SiteAction]:
        rows = self.conn.execute(
            "SELECT * FROM actions WHERE site_domain = ?", (domain,)
        ).fetchall()
        actions = []
        for row in rows:
            from site2cli.models import EndpointInfo

            endpoint = None
            if row["endpoint_json"]:
                endpoint = EndpointInfo.model_validate_json(row["endpoint_json"])
            actions.append(
                SiteAction(
                    name=row["name"],
                    description=row["description"],
                    tier=Tier(row["tier"]),
                    endpoint=endpoint,
                    workflow_id=row["workflow_id"],
                    success_count=row["success_count"],
                    failure_count=row["failure_count"],
                    last_used=(
                        datetime.fromisoformat(row["last_used"]) if row["last_used"] else None
                    ),
                    last_checked=(
                        datetime.fromisoformat(row["last_checked"])
                        if row["last_checked"]
                        else None
                    ),
                    health=HealthStatus(row["health"]),
                )
            )
        return actions

    def list_sites(self) -> list[SiteEntry]:
        rows = self.conn.execute("SELECT domain FROM sites ORDER BY domain").fetchall()
        return [self.get_site(row["domain"]) for row in rows]  # type: ignore

    def remove_site(self, domain: str) -> bool:
        self.conn.execute("DELETE FROM actions WHERE site_domain = ?", (domain,))
        cursor = self.conn.execute("DELETE FROM sites WHERE domain = ?", (domain,))
        self.conn.commit()
        return cursor.rowcount > 0

    def update_action_tier(self, domain: str, action_name: str, tier: Tier) -> None:
        self.conn.execute(
            "UPDATE actions SET tier = ? WHERE site_domain = ? AND name = ?",
            (tier.value, domain, action_name),
        )
        self.conn.commit()

    def record_action_result(self, domain: str, action_name: str, success: bool) -> None:
        col = "success_count" if success else "failure_count"
        self.conn.execute(
            f"UPDATE actions SET {col} = {col} + 1, last_used = ?"
            " WHERE site_domain = ? AND name = ?",
            (datetime.utcnow().isoformat(), domain, action_name),
        )
        self.conn.commit()

    def update_health(self, domain: str, action_name: str, health: HealthStatus) -> None:
        self.conn.execute(
            "UPDATE actions SET health = ?, last_checked = ? WHERE site_domain = ? AND name = ?",
            (health.value, datetime.utcnow().isoformat(), domain, action_name),
        )
        self.conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
