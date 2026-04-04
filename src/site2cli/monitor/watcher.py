"""Change detection watcher for URLs."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

import httpx

from site2cli.models import MonitorDiff, MonitorSnapshot, MonitorWatch
from site2cli.monitor.differ import compute_diff, normalize_for_diff
from site2cli.registry import SiteRegistry


class ChangeWatcher:
    """Watches URLs for content changes."""

    def __init__(self, registry: SiteRegistry) -> None:
        self._registry = registry

    async def check(
        self,
        watch: MonitorWatch,
        proxy: str | None = None,
    ) -> MonitorDiff:
        """Check a URL for changes against the last snapshot.

        Returns a MonitorDiff with change information.
        """
        # Fetch the page
        kwargs: dict = {"follow_redirects": True, "timeout": 15}
        if proxy:
            kwargs["proxy"] = proxy
        async with httpx.AsyncClient(**kwargs) as client:
            resp = await client.get(watch.url)

        # Convert to text for diffing
        html = resp.text
        if watch.main_content_only:
            from site2cli.content.converter import extract_main_content
            html = extract_main_content(html)

        from site2cli.content.converter import html_to_text
        text = html_to_text(html)
        normalized = normalize_for_diff(text)
        content_hash = hashlib.sha256(normalized.encode()).hexdigest()

        # Create new snapshot
        new_snapshot = MonitorSnapshot(
            id=str(uuid.uuid4()),
            watch_id=watch.id,
            url=watch.url,
            content_hash=content_hash,
            content_text=normalized,
            status_code=resp.status_code,
        )

        # Get previous snapshot
        old_snapshot = self._registry.get_latest_snapshot(watch.id)

        # Save the new snapshot
        self._registry.save_monitor_snapshot(new_snapshot)

        # Update watch counters
        watch.check_count += 1
        watch.last_checked = datetime.utcnow()

        if old_snapshot is None:
            # First check — baseline
            self._registry.save_monitor_watch(watch)
            return MonitorDiff(
                watch_id=watch.id,
                url=watch.url,
                changed=False,
                new_snapshot_id=new_snapshot.id,
            )

        if content_hash == old_snapshot.content_hash:
            # No change
            self._registry.save_monitor_watch(watch)
            return MonitorDiff(
                watch_id=watch.id,
                url=watch.url,
                changed=False,
                old_snapshot_id=old_snapshot.id,
                new_snapshot_id=new_snapshot.id,
            )

        # Content changed — compute diff
        diff = compute_diff(
            old_text=old_snapshot.content_text,
            new_text=normalized,
            watch_id=watch.id,
            url=watch.url,
            old_snapshot_id=old_snapshot.id,
            new_snapshot_id=new_snapshot.id,
        )

        watch.change_count += 1
        watch.last_changed = datetime.utcnow()
        self._registry.save_monitor_watch(watch)

        # Send webhook if configured
        if watch.webhook_url and diff.changed:
            await self._send_webhook(watch, diff)

        return diff

    async def check_all_active(self, proxy: str | None = None) -> list[MonitorDiff]:
        """Check all active watches."""
        watches = self._registry.list_monitor_watches(active_only=True)
        results = []
        for watch in watches:
            try:
                diff = await self.check(watch, proxy=proxy)
                results.append(diff)
            except Exception:
                pass
        return results

    async def _send_webhook(self, watch: MonitorWatch, diff: MonitorDiff) -> bool:
        """Send change notification to webhook URL."""
        if not watch.webhook_url:
            return False
        try:
            payload = {
                "url": watch.url,
                "changed": diff.changed,
                "added_lines": diff.added_lines,
                "removed_lines": diff.removed_lines,
                "watch_id": watch.id,
                "timestamp": datetime.utcnow().isoformat(),
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(watch.webhook_url, json=payload)
                return resp.status_code < 400
        except Exception:
            return False
