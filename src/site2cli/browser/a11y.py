"""Accessibility tree extraction for better page representation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page


_INTERACTIVE_ROLES = frozenset({
    "button", "link", "textbox", "checkbox", "combobox",
    "menuitem", "tab", "radio", "switch", "slider",
    "searchbox", "spinbutton", "option", "menuitemcheckbox",
    "menuitemradio",
})


@dataclass
class A11yNode:
    """Represents a node in the accessibility tree."""

    role: str
    name: str
    level: int = 0
    checked: bool | None = None
    disabled: bool = False
    value: str = ""
    index: int | None = None  # Sequential index for interactive elements


async def extract_a11y_tree(page: Page, max_depth: int = 5) -> list[A11yNode]:
    """Extract accessibility tree using Playwright's accessibility API.

    Args:
        page: Playwright page instance.
        max_depth: Maximum tree depth to traverse.

    Returns:
        Flattened list of A11yNode objects with indexed interactive elements.
    """
    snapshot = await page.accessibility.snapshot()
    if not snapshot:
        return []

    nodes: list[A11yNode] = []
    counter = [0]  # mutable counter for index assignment
    _walk_tree(snapshot, nodes, depth=0, max_depth=max_depth, counter=counter)
    return nodes


def _walk_tree(
    node: dict,
    nodes: list[A11yNode],
    depth: int,
    max_depth: int,
    counter: list[int] | None = None,
) -> None:
    """Recursively walk the accessibility tree and flatten to node list."""
    if depth > max_depth:
        return

    role = node.get("role", "")
    name = (node.get("name") or "").strip()

    # Skip generic/structural roles with no useful info
    if role not in ("none", "generic", "") or name:
        # Assign index to interactive elements
        index = None
        if counter is not None and role in _INTERACTIVE_ROLES:
            index = counter[0]
            counter[0] += 1

        nodes.append(
            A11yNode(
                role=role,
                name=name,
                level=depth,
                checked=node.get("checked"),
                disabled=node.get("disabled", False),
                value=node.get("value", ""),
                index=index,
            )
        )

    for child in node.get("children", []):
        _walk_tree(child, nodes, depth + 1, max_depth, counter)


def format_a11y_for_llm(nodes: list[A11yNode], max_items: int = 150) -> str:
    """Format accessibility nodes as concise text for LLM context.

    Interactive elements are prefixed with [@N] for indexed interaction.

    Args:
        nodes: List of A11yNode objects.
        max_items: Maximum number of nodes to include.

    Returns:
        Formatted string representation.
    """
    lines: list[str] = []
    for node in nodes[:max_items]:
        indent = "  " * node.level
        if node.index is not None:
            parts = [f"{indent}[@{node.index}] [{node.role}]"]
        else:
            parts = [f"{indent}[{node.role}]"]
        if node.name:
            parts.append(f'"{node.name}"')
        if node.value:
            parts.append(f"value={node.value}")
        if node.checked is not None:
            parts.append(f"checked={node.checked}")
        if node.disabled:
            parts.append("disabled")
        lines.append(" ".join(parts))

    if len(nodes) > max_items:
        lines.append(f"  ... ({len(nodes) - max_items} more nodes)")

    return "\n".join(lines)


def get_node_by_index(nodes: list[A11yNode], idx: int) -> A11yNode | None:
    """Find an A11yNode by its element index."""
    for node in nodes:
        if node.index == idx:
            return node
    return None


def build_locator_from_node(node: A11yNode) -> str:
    """Build a Playwright locator string from an A11yNode.

    Returns a role-based locator like: role=button[name="Submit"]
    """
    locator = f'role={node.role}[name="{node.name}"]' if node.name else f"role={node.role}"
    return locator


async def get_a11y_hash(page: Page) -> str:
    """Get SHA256 hash of accessibility snapshot for change detection."""
    try:
        snapshot = await page.accessibility.snapshot()
        content = json.dumps(snapshot, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()
    except Exception:
        return ""
