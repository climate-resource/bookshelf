"""Notebook presentation helpers for consumed handles."""

from collections.abc import Mapping
from html import escape


def summary_table(title: str, rows: Mapping[str, object]) -> str:
    """Render a compact escaped HTML summary table."""
    body = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in rows.items()
    )
    return f"<div><strong>{escape(title)}</strong><table>{body}</table></div>"


__all__ = ["summary_table"]
