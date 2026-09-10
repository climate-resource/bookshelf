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


def human_bytes(count: int) -> str:
    """Render a byte count for the human summaries."""
    size = float(count)
    for unit in ("B", "kB", "MB", "GB"):
        if size < 1000 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1000
    return f"{int(size)} B"  # pragma: no cover - unreachable


def _text_lines(section: Section) -> list[str]:
    """Lay a section out as indented text, aligning a mapping into two columns."""
    if not isinstance(section, Mapping):
        joined = "  ".join(str(item) for item in section)
        return wrap(joined, width=_TEXT_WIDTH - len(_INDENT))
    width = max(len(label) for label in section)
    return [f"{label.ljust(width)}  {value}" for label, value in section.items()]


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
    if not isinstance(section, Mapping):
        return f"<div>{escape('  '.join(str(item) for item in section))}</div>"
    body = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in section.items()
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


class Describable:
    """Renders a handle as a header line over named sections, in text and in HTML."""

    def _summary(self) -> tuple[str, Sections]:
        """Return the header and sections both reprs render."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return summary_text(*self._summary())

    def _repr_html_(self) -> str:
        return summary_table(*self._summary())


__all__ = [
    "Describable",
    "Section",
    "Sections",
    "human_bytes",
    "summary_table",
    "summary_text",
]
