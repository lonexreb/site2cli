"""Line-level diff computation for change detection."""

from __future__ import annotations

import difflib
import re

from site2cli.models import DiffLine, MonitorDiff


def normalize_for_diff(text: str) -> str:
    """Normalize text before diffing to prevent false positives.

    - Collapse multiple whitespace into single space
    - Strip leading/trailing whitespace per line
    - Remove blank lines
    """
    lines = []
    for line in text.splitlines():
        stripped = re.sub(r"\s+", " ", line).strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)


def compute_diff(
    old_text: str,
    new_text: str,
    watch_id: str = "",
    url: str = "",
    old_snapshot_id: str | None = None,
    new_snapshot_id: str | None = None,
) -> MonitorDiff:
    """Compute line-level diff between two text snapshots."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    diff_lines: list[DiffLine] = []
    added = 0
    removed = 0

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, old_lines, new_lines
    ).get_opcodes():
        if tag == "equal":
            for idx in range(i1, i2):
                diff_lines.append(
                    DiffLine(operation="unchanged", line_number=idx + 1, content=old_lines[idx])
                )
        elif tag == "delete":
            for idx in range(i1, i2):
                diff_lines.append(
                    DiffLine(operation="remove", line_number=idx + 1, content=old_lines[idx])
                )
                removed += 1
        elif tag == "insert":
            for idx in range(j1, j2):
                diff_lines.append(
                    DiffLine(operation="add", line_number=idx + 1, content=new_lines[idx])
                )
                added += 1
        elif tag == "replace":
            for idx in range(i1, i2):
                diff_lines.append(
                    DiffLine(operation="remove", line_number=idx + 1, content=old_lines[idx])
                )
                removed += 1
            for idx in range(j1, j2):
                diff_lines.append(
                    DiffLine(operation="add", line_number=idx + 1, content=new_lines[idx])
                )
                added += 1

    return MonitorDiff(
        watch_id=watch_id,
        url=url,
        changed=added > 0 or removed > 0,
        old_snapshot_id=old_snapshot_id,
        new_snapshot_id=new_snapshot_id,
        added_lines=added,
        removed_lines=removed,
        diff_lines=diff_lines,
    )


def format_diff(diff: MonitorDiff, fmt: str = "diff") -> str:
    """Format a diff for display."""
    if fmt == "json":
        return diff.model_dump_json(indent=2)

    if fmt == "markdown":
        lines = [f"## Changes for {diff.url}\n"]
        if not diff.changed:
            lines.append("No changes detected.\n")
            return "\n".join(lines)
        lines.append(f"**+{diff.added_lines} added, -{diff.removed_lines} removed**\n")
        for dl in diff.diff_lines:
            if dl.operation == "add":
                lines.append(f"+ {dl.content}")
            elif dl.operation == "remove":
                lines.append(f"- {dl.content}")
        return "\n".join(lines)

    # Default: unified diff format
    lines = []
    if not diff.changed:
        lines.append("No changes detected.")
        return "\n".join(lines)
    lines.append("--- old")
    lines.append("+++ new")
    for dl in diff.diff_lines:
        if dl.operation == "add":
            lines.append(f"+{dl.content}")
        elif dl.operation == "remove":
            lines.append(f"-{dl.content}")
        elif dl.operation == "unchanged":
            lines.append(f" {dl.content}")
    return "\n".join(lines)
