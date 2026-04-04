"""Site registry backed by SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from site2cli.models import (
    AuthType,
    CrawlJob,
    CrawlPage,
    CrawlStatus,
    HealthStatus,
    MonitorSnapshot,
    MonitorWatch,
    OrchestrationPipeline,
    RecordedWorkflow,
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

            CREATE TABLE IF NOT EXISTS orchestrations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                steps_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                run_count INTEGER DEFAULT 0,
                last_run TEXT
            );

            CREATE TABLE IF NOT EXISTS crawl_jobs (
                id TEXT PRIMARY KEY,
                start_url TEXT NOT NULL,
                domain TEXT NOT NULL,
                max_depth INTEGER DEFAULT 3,
                max_pages INTEGER DEFAULT 100,
                status TEXT DEFAULT 'pending',
                pages_crawled INTEGER DEFAULT 0,
                pages_total INTEGER DEFAULT 0,
                output_format TEXT DEFAULT 'markdown',
                main_content_only INTEGER DEFAULT 1,
                respect_robots INTEGER DEFAULT 1,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS crawl_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                url TEXT NOT NULL,
                depth INTEGER DEFAULT 0,
                status_code INTEGER DEFAULT 0,
                content_type TEXT DEFAULT '',
                title TEXT DEFAULT '',
                content_hash TEXT DEFAULT '',
                links_found INTEGER DEFAULT 0,
                crawled_at TEXT NOT NULL,
                error TEXT,
                FOREIGN KEY (job_id) REFERENCES crawl_jobs(id),
                UNIQUE(job_id, url)
            );

            CREATE TABLE IF NOT EXISTS monitor_watches (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                interval_seconds INTEGER DEFAULT 3600,
                webhook_url TEXT,
                output_format TEXT DEFAULT 'diff',
                main_content_only INTEGER DEFAULT 1,
                active INTEGER DEFAULT 1,
                last_checked TEXT,
                last_changed TEXT,
                check_count INTEGER DEFAULT 0,
                change_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS monitor_snapshots (
                id TEXT PRIMARY KEY,
                watch_id TEXT NOT NULL,
                url TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                content_text TEXT DEFAULT '',
                status_code INTEGER DEFAULT 0,
                captured_at TEXT NOT NULL,
                FOREIGN KEY (watch_id) REFERENCES monitor_watches(id)
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

    # --- Workflow CRUD ---

    def save_workflow(self, workflow: RecordedWorkflow) -> None:
        """Save a recorded workflow to the database."""

        steps_json = "[" + ",".join(s.model_dump_json() for s in workflow.steps) + "]"
        params_json = (
            "[" + ",".join(p.model_dump_json() for p in workflow.parameters) + "]"
        )
        self.conn.execute(
            """INSERT OR REPLACE INTO workflows
               (id, site_domain, action_name, steps_json, parameters_json,
                recorded_at, replay_count, success_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                workflow.id,
                workflow.site_domain,
                workflow.action_name,
                steps_json,
                params_json,
                workflow.recorded_at.isoformat(),
                workflow.replay_count,
                workflow.success_count,
            ),
        )
        self.conn.commit()

    def get_workflow(self, workflow_id: str) -> RecordedWorkflow | None:
        """Get a workflow by ID."""
        import json as _json

        from site2cli.models import ParameterInfo, RecordedWorkflow, WorkflowStep

        row = self.conn.execute(
            "SELECT * FROM workflows WHERE id = ?", (workflow_id,)
        ).fetchone()
        if not row:
            return None
        steps = [WorkflowStep.model_validate(s) for s in _json.loads(row["steps_json"])]
        params = [ParameterInfo.model_validate(p) for p in _json.loads(row["parameters_json"])]
        return RecordedWorkflow(
            id=row["id"],
            site_domain=row["site_domain"],
            action_name=row["action_name"],
            steps=steps,
            parameters=params,
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
            replay_count=row["replay_count"],
            success_count=row["success_count"],
        )

    def list_workflows(self) -> list[RecordedWorkflow]:
        """List all recorded workflows."""
        rows = self.conn.execute(
            "SELECT id FROM workflows ORDER BY recorded_at DESC"
        ).fetchall()
        workflows = []
        for row in rows:
            wf = self.get_workflow(row["id"])
            if wf:
                workflows.append(wf)
        return workflows

    def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow by ID."""
        cursor = self.conn.execute(
            "DELETE FROM workflows WHERE id = ?", (workflow_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    # --- Orchestration CRUD ---

    def save_orchestration(self, pipeline: OrchestrationPipeline) -> None:
        """Save an orchestration pipeline."""
        import json as _json

        steps_json = _json.dumps(
            [s.model_dump(mode="json") for s in pipeline.steps]
        )
        self.conn.execute(
            """INSERT OR REPLACE INTO orchestrations
               (id, name, description, steps_json, created_at, updated_at,
                run_count, last_run)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pipeline.id,
                pipeline.name,
                pipeline.description,
                steps_json,
                pipeline.created_at.isoformat(),
                pipeline.updated_at.isoformat(),
                pipeline.run_count,
                pipeline.last_run.isoformat() if pipeline.last_run else None,
            ),
        )
        self.conn.commit()

    def get_orchestration(self, pipeline_id: str) -> OrchestrationPipeline | None:
        """Get an orchestration by ID."""
        import json as _json

        from site2cli.models import OrchestrationStep

        row = self.conn.execute(
            "SELECT * FROM orchestrations WHERE id = ?", (pipeline_id,)
        ).fetchone()
        if not row:
            return None
        steps = [
            OrchestrationStep.model_validate(s)
            for s in _json.loads(row["steps_json"])
        ]
        return OrchestrationPipeline(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            steps=steps,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            run_count=row["run_count"],
            last_run=(
                datetime.fromisoformat(row["last_run"]) if row["last_run"] else None
            ),
        )

    def list_orchestrations(self) -> list[OrchestrationPipeline]:
        """List all orchestration pipelines."""
        rows = self.conn.execute(
            "SELECT id FROM orchestrations ORDER BY name"
        ).fetchall()
        pipelines = []
        for row in rows:
            p = self.get_orchestration(row["id"])
            if p:
                pipelines.append(p)
        return pipelines

    def delete_orchestration(self, pipeline_id: str) -> bool:
        """Delete an orchestration by ID."""
        cursor = self.conn.execute(
            "DELETE FROM orchestrations WHERE id = ?", (pipeline_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def record_orchestration_run(self, pipeline_id: str) -> None:
        """Increment the run count and update last_run timestamp."""
        self.conn.execute(
            "UPDATE orchestrations SET run_count = run_count + 1, last_run = ?"
            " WHERE id = ?",
            (datetime.utcnow().isoformat(), pipeline_id),
        )
        self.conn.commit()

    # --- Crawl CRUD ---

    def save_crawl_job(self, job: CrawlJob) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO crawl_jobs
               (id, start_url, domain, max_depth, max_pages, status,
                pages_crawled, pages_total, output_format, main_content_only,
                respect_robots, started_at, completed_at, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job.id,
                job.start_url,
                job.domain,
                job.max_depth,
                job.max_pages,
                job.status.value,
                job.pages_crawled,
                job.pages_total,
                job.output_format,
                1 if job.main_content_only else 0,
                1 if job.respect_robots else 0,
                job.started_at.isoformat(),
                job.completed_at.isoformat() if job.completed_at else None,
                job.error,
            ),
        )
        self.conn.commit()

    def get_crawl_job(self, job_id: str) -> CrawlJob | None:
        row = self.conn.execute(
            "SELECT * FROM crawl_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if not row:
            return None
        return CrawlJob(
            id=row["id"],
            start_url=row["start_url"],
            domain=row["domain"],
            max_depth=row["max_depth"],
            max_pages=row["max_pages"],
            status=CrawlStatus(row["status"]),
            pages_crawled=row["pages_crawled"],
            pages_total=row["pages_total"],
            output_format=row["output_format"],
            main_content_only=bool(row["main_content_only"]),
            respect_robots=bool(row["respect_robots"]),
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=(
                datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None
            ),
            error=row["error"],
        )

    def save_crawl_page(self, job_id: str, page: CrawlPage) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO crawl_pages
               (job_id, url, depth, status_code, content_type, title,
                content_hash, links_found, crawled_at, error)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                page.url,
                page.depth,
                page.status_code,
                page.content_type,
                page.title,
                page.content_hash,
                page.links_found,
                page.crawled_at.isoformat(),
                page.error,
            ),
        )
        self.conn.commit()

    def get_crawled_urls(self, job_id: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT url FROM crawl_pages WHERE job_id = ?", (job_id,)
        ).fetchall()
        return {row["url"] for row in rows}

    def list_crawl_jobs(self, domain: str | None = None) -> list[CrawlJob]:
        if domain:
            rows = self.conn.execute(
                "SELECT id FROM crawl_jobs WHERE domain = ? ORDER BY started_at DESC",
                (domain,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id FROM crawl_jobs ORDER BY started_at DESC"
            ).fetchall()
        return [self.get_crawl_job(row["id"]) for row in rows if self.get_crawl_job(row["id"])]

    # --- Monitor CRUD ---

    def save_monitor_watch(self, watch: MonitorWatch) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO monitor_watches
               (id, url, interval_seconds, webhook_url, output_format,
                main_content_only, active, last_checked, last_changed,
                check_count, change_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                watch.id,
                watch.url,
                watch.interval_seconds,
                watch.webhook_url,
                watch.output_format,
                1 if watch.main_content_only else 0,
                1 if watch.active else 0,
                watch.last_checked.isoformat() if watch.last_checked else None,
                watch.last_changed.isoformat() if watch.last_changed else None,
                watch.check_count,
                watch.change_count,
                watch.created_at.isoformat(),
            ),
        )
        self.conn.commit()

    def get_monitor_watch(self, watch_id: str) -> MonitorWatch | None:
        row = self.conn.execute(
            "SELECT * FROM monitor_watches WHERE id = ?", (watch_id,)
        ).fetchone()
        if not row:
            return None
        return MonitorWatch(
            id=row["id"],
            url=row["url"],
            interval_seconds=row["interval_seconds"],
            webhook_url=row["webhook_url"],
            output_format=row["output_format"],
            main_content_only=bool(row["main_content_only"]),
            active=bool(row["active"]),
            last_checked=(
                datetime.fromisoformat(row["last_checked"]) if row["last_checked"] else None
            ),
            last_changed=(
                datetime.fromisoformat(row["last_changed"]) if row["last_changed"] else None
            ),
            check_count=row["check_count"],
            change_count=row["change_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_monitor_watches(self, active_only: bool = True) -> list[MonitorWatch]:
        if active_only:
            rows = self.conn.execute(
                "SELECT id FROM monitor_watches WHERE active = 1 ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT id FROM monitor_watches ORDER BY created_at DESC"
            ).fetchall()
        watches = [self.get_monitor_watch(row["id"]) for row in rows]
        return [w for w in watches if w is not None]

    def delete_monitor_watch(self, watch_id: str) -> bool:
        self.conn.execute(
            "DELETE FROM monitor_snapshots WHERE watch_id = ?", (watch_id,)
        )
        cursor = self.conn.execute(
            "DELETE FROM monitor_watches WHERE id = ?", (watch_id,)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def save_monitor_snapshot(self, snapshot: MonitorSnapshot) -> None:
        self.conn.execute(
            """INSERT INTO monitor_snapshots
               (id, watch_id, url, content_hash, content_text, status_code, captured_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot.id,
                snapshot.watch_id,
                snapshot.url,
                snapshot.content_hash,
                snapshot.content_text,
                snapshot.status_code,
                snapshot.captured_at.isoformat(),
            ),
        )
        self.conn.commit()

    def get_latest_snapshot(self, watch_id: str) -> MonitorSnapshot | None:
        row = self.conn.execute(
            "SELECT * FROM monitor_snapshots WHERE watch_id = ? ORDER BY captured_at DESC LIMIT 1",
            (watch_id,),
        ).fetchone()
        if not row:
            return None
        return MonitorSnapshot(
            id=row["id"],
            watch_id=row["watch_id"],
            url=row["url"],
            content_hash=row["content_hash"],
            content_text=row["content_text"],
            status_code=row["status_code"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
        )

    def get_snapshot_history(self, watch_id: str, limit: int = 10) -> list[MonitorSnapshot]:
        rows = self.conn.execute(
            "SELECT * FROM monitor_snapshots WHERE watch_id = ? ORDER BY captured_at DESC LIMIT ?",
            (watch_id, limit),
        ).fetchall()
        return [
            MonitorSnapshot(
                id=row["id"],
                watch_id=row["watch_id"],
                url=row["url"],
                content_hash=row["content_hash"],
                content_text=row["content_text"],
                status_code=row["status_code"],
                captured_at=datetime.fromisoformat(row["captured_at"]),
            )
            for row in rows
        ]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
