"""Tests for change detection monitor — diff, watcher, webhook, CRUD."""

from datetime import datetime

import pytest

from site2cli.models import DiffLine, MonitorDiff, MonitorSnapshot, MonitorWatch
from site2cli.monitor.differ import compute_diff, format_diff, normalize_for_diff

# --- Diff Computation Tests ---


class TestNormalizeForDiff:
    def test_collapses_whitespace(self):
        assert normalize_for_diff("hello   world") == "hello world"

    def test_strips_lines(self):
        assert normalize_for_diff("  hello  \n  world  ") == "hello\nworld"

    def test_removes_blank_lines(self):
        assert normalize_for_diff("hello\n\n\nworld") == "hello\nworld"

    def test_empty_input(self):
        assert normalize_for_diff("") == ""

    def test_only_whitespace(self):
        assert normalize_for_diff("   \n   \n   ") == ""


class TestComputeDiff:
    def test_identical_texts(self):
        diff = compute_diff("hello\nworld", "hello\nworld")
        assert diff.changed is False
        assert diff.added_lines == 0
        assert diff.removed_lines == 0

    def test_added_lines(self):
        diff = compute_diff("hello", "hello\nworld")
        assert diff.changed is True
        assert diff.added_lines == 1

    def test_removed_lines(self):
        diff = compute_diff("hello\nworld", "hello")
        assert diff.changed is True
        assert diff.removed_lines == 1

    def test_mixed_changes(self):
        diff = compute_diff("a\nb\nc", "a\nx\nc")
        assert diff.changed is True
        assert diff.added_lines >= 1
        assert diff.removed_lines >= 1

    def test_empty_to_content(self):
        diff = compute_diff("", "hello\nworld")
        assert diff.changed is True
        assert diff.added_lines == 2

    def test_content_to_empty(self):
        diff = compute_diff("hello\nworld", "")
        assert diff.changed is True
        assert diff.removed_lines == 2

    def test_both_empty(self):
        diff = compute_diff("", "")
        assert diff.changed is False

    def test_diff_has_metadata(self):
        diff = compute_diff("a", "b", watch_id="w1", url="https://example.com")
        assert diff.watch_id == "w1"
        assert diff.url == "https://example.com"

    def test_diff_lines_populated(self):
        diff = compute_diff("hello", "hello\nworld")
        ops = [dl.operation for dl in diff.diff_lines]
        assert "add" in ops
        assert "unchanged" in ops


class TestFormatDiff:
    def test_format_diff_no_change(self):
        diff = MonitorDiff(watch_id="w1", url="https://example.com", changed=False)
        result = format_diff(diff, "diff")
        assert "No changes" in result

    def test_format_diff_unified(self):
        diff = compute_diff("hello", "world")
        result = format_diff(diff, "diff")
        assert "-hello" in result or "+world" in result

    def test_format_json(self):
        diff = MonitorDiff(watch_id="w1", url="https://example.com", changed=False)
        result = format_diff(diff, "json")
        assert '"changed": false' in result

    def test_format_markdown(self):
        diff = compute_diff("hello", "world", url="https://example.com")
        result = format_diff(diff, "markdown")
        assert "## Changes" in result


# --- Monitor Models Tests ---


class TestMonitorModels:
    def test_watch_defaults(self):
        w = MonitorWatch(id="test", url="https://example.com")
        assert w.interval_seconds == 3600
        assert w.active is True
        assert w.check_count == 0
        assert w.change_count == 0

    def test_watch_with_webhook(self):
        w = MonitorWatch(
            id="test", url="https://example.com",
            webhook_url="https://hooks.slack.com/xxx",
        )
        assert w.webhook_url == "https://hooks.slack.com/xxx"

    def test_snapshot_defaults(self):
        s = MonitorSnapshot(
            id="s1", watch_id="w1", url="https://example.com",
            content_hash="abc123",
        )
        assert s.status_code == 0
        assert isinstance(s.captured_at, datetime)

    def test_diff_line_model(self):
        dl = DiffLine(operation="add", line_number=5, content="new line")
        assert dl.operation == "add"
        assert dl.line_number == 5

    def test_monitor_diff_defaults(self):
        d = MonitorDiff(watch_id="w1", url="https://example.com", changed=False)
        assert d.added_lines == 0
        assert d.removed_lines == 0
        assert d.diff_lines == []


# --- Registry CRUD Tests ---


class TestMonitorRegistry:
    @pytest.fixture
    def registry(self, tmp_path):
        from site2cli.registry import SiteRegistry

        return SiteRegistry(tmp_path / "test.db")

    def test_save_and_get_watch(self, registry):
        w = MonitorWatch(id="w1", url="https://example.com")
        registry.save_monitor_watch(w)
        got = registry.get_monitor_watch("w1")
        assert got is not None
        assert got.url == "https://example.com"

    def test_list_active_watches(self, registry):
        w1 = MonitorWatch(id="w1", url="https://a.com", active=True)
        w2 = MonitorWatch(id="w2", url="https://b.com", active=False)
        registry.save_monitor_watch(w1)
        registry.save_monitor_watch(w2)
        active = registry.list_monitor_watches(active_only=True)
        assert len(active) == 1
        assert active[0].id == "w1"

    def test_list_all_watches(self, registry):
        w1 = MonitorWatch(id="w1", url="https://a.com", active=True)
        w2 = MonitorWatch(id="w2", url="https://b.com", active=False)
        registry.save_monitor_watch(w1)
        registry.save_monitor_watch(w2)
        all_watches = registry.list_monitor_watches(active_only=False)
        assert len(all_watches) == 2

    def test_delete_watch(self, registry):
        w = MonitorWatch(id="w1", url="https://example.com")
        registry.save_monitor_watch(w)
        assert registry.delete_monitor_watch("w1") is True
        assert registry.get_monitor_watch("w1") is None

    def test_delete_nonexistent(self, registry):
        assert registry.delete_monitor_watch("nope") is False

    def test_save_and_get_snapshot(self, registry):
        s = MonitorSnapshot(
            id="s1", watch_id="w1", url="https://example.com",
            content_hash="abc123", content_text="hello",
        )
        registry.save_monitor_snapshot(s)
        latest = registry.get_latest_snapshot("w1")
        assert latest is not None
        assert latest.content_hash == "abc123"

    def test_snapshot_history(self, registry):
        for i in range(5):
            s = MonitorSnapshot(
                id=f"s{i}", watch_id="w1", url="https://example.com",
                content_hash=f"hash{i}",
            )
            registry.save_monitor_snapshot(s)
        history = registry.get_snapshot_history("w1", limit=3)
        assert len(history) == 3

    def test_snapshot_history_empty(self, registry):
        history = registry.get_snapshot_history("nonexistent")
        assert history == []


# --- Crawl Registry CRUD Tests ---


class TestCrawlRegistry:
    @pytest.fixture
    def registry(self, tmp_path):
        from site2cli.registry import SiteRegistry

        return SiteRegistry(tmp_path / "test.db")

    def test_save_and_get_crawl_job(self, registry):
        from site2cli.models import CrawlJob

        j = CrawlJob(id="j1", start_url="https://example.com", domain="example.com")
        registry.save_crawl_job(j)
        got = registry.get_crawl_job("j1")
        assert got is not None
        assert got.domain == "example.com"

    def test_crawl_job_not_found(self, registry):
        assert registry.get_crawl_job("nope") is None

    def test_save_crawl_page(self, registry):
        from site2cli.models import CrawlJob, CrawlPage

        j = CrawlJob(id="j1", start_url="https://example.com", domain="example.com")
        registry.save_crawl_job(j)
        p = CrawlPage(url="https://example.com/page1", depth=1, status_code=200)
        registry.save_crawl_page("j1", p)
        urls = registry.get_crawled_urls("j1")
        assert "https://example.com/page1" in urls

    def test_get_crawled_urls_empty(self, registry):
        urls = registry.get_crawled_urls("nonexistent")
        assert urls == set()

    def test_list_crawl_jobs(self, registry):
        from site2cli.models import CrawlJob

        j1 = CrawlJob(id="j1", start_url="https://a.com", domain="a.com")
        j2 = CrawlJob(id="j2", start_url="https://b.com", domain="b.com")
        registry.save_crawl_job(j1)
        registry.save_crawl_job(j2)
        jobs = registry.list_crawl_jobs()
        assert len(jobs) == 2

    def test_list_crawl_jobs_by_domain(self, registry):
        from site2cli.models import CrawlJob

        j1 = CrawlJob(id="j1", start_url="https://a.com", domain="a.com")
        j2 = CrawlJob(id="j2", start_url="https://b.com", domain="b.com")
        registry.save_crawl_job(j1)
        registry.save_crawl_job(j2)
        jobs = registry.list_crawl_jobs(domain="a.com")
        assert len(jobs) == 1
        assert jobs[0].domain == "a.com"


# --- CLI Tests ---


class TestMonitorCLI:
    def test_cli_help(self):
        from typer.testing import CliRunner

        from site2cli.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["monitor", "--help"])
        assert result.exit_code == 0
        assert "monitor" in result.output.lower()
