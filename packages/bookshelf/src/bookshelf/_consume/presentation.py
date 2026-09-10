"""Notebook and terminal presentation helpers for consumed handles.

A handle describes itself as a header line plus named sections,
following the shape xarray and scmdata already use,
because those are the reprs a bookshelf user reads all day.
Both renderers take the same structure, so the two can never drift apart.
"""

from collections.abc import Mapping, Sequence
from html import escape
from textwrap import wrap

type Section = Mapping[str, object] | Sequence[str]
type Sections = Mapping[str, Section]

_INDENT = "    "
_TEXT_WIDTH = 88


def _rows(section: Section) -> Mapping[str, object] | None:
    """Return the section's label/value pairs, or None when it is a bare list of lines."""
    return section if isinstance(section, Mapping) else None


def _text_lines(section: Section) -> list[str]:
    """Lay a section out as indented text, aligning a mapping into two columns."""
    rows = _rows(section)
    if rows is None:
        joined = "  ".join(str(item) for item in section)
        return wrap(joined, width=_TEXT_WIDTH - len(_INDENT)) or []
    width = max(len(label) for label in rows)
    return [f"{label.ljust(width)}  {value}" for label, value in rows.items()]


def summary_text(header: str, sections: Sections) -> str:
    """Render a handle as an angle-bracketed header over indented named sections."""
    lines = [f"<{header}>"]
    for name, section in sections.items():
        if not section:
            continue
        lines.append(f"{name}:")
        lines.extend(f"{_INDENT}{line}" for line in _text_lines(section))
    return "\n".join(lines)


def _html_section(section: Section) -> str:
    rows = _rows(section)
    if rows is None:
        return f"<div>{escape('  '.join(str(item) for item in section))}</div>"
    body = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in rows.items()
    )
    return f"<table>{body}</table>"


def summary_table(header: str, sections: Sections) -> str:
    """Render the same structure as escaped HTML for a notebook."""
    body = "".join(
        f"<div><em>{escape(name)}</em>{_html_section(section)}</div>"
        for name, section in sections.items()
        if section
    )
    return f"<div><strong>{escape(header)}</strong>{body}</div>"


__all__ = ["Section", "Sections", "summary_table", "summary_text"]
