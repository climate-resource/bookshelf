#!/usr/bin/env python3
"""Write the command reference in docs/cli.md from the Typer app, or check it with --check."""

import inspect
import sys
from pathlib import Path
from typing import Any

import typer
from typer.core import TyperGroup

from bookshelf._cli import app

PAGE = Path(__file__).resolve().parents[3] / "docs" / "cli.md"
BEGIN = "<!-- BEGIN GENERATED REFERENCE: make cli-reference -->"
END = "<!-- END GENERATED REFERENCE -->"
# Typer adds these to the root, and they describe the shell rather than the CLI.
_SKIPPED_OPTIONS = {"--install-completion", "--show-completion", "--help"}


def _escaped(text: str) -> str:
    """Keep ``<hex>`` from reading as an HTML tag, and ``[/entry]`` as a cross-reference."""
    return text.replace("<", "&lt;").replace("[", "\\[")


def _section(command: Any, ctx: typer.Context, path: str) -> list[str]:  # noqa: ANN401
    lines = [f"### `{path}`", ""]
    if command.help:
        lines += [_escaped(inspect.cleandoc(command.help)), ""]
    lines += ["```console", f"$ {path} {' '.join(command.collect_usage_pieces(ctx))}", "```", ""]
    arguments: list[str] = []
    options: list[str] = []
    for param in command.get_params(ctx):
        record = param.get_help_record(ctx)
        if record is None or set(param.opts) & _SKIPPED_OPTIONS:
            continue
        target = arguments if param.param_type_name == "argument" else options
        name, text = record
        target.append(f"- `{name}`" + (f": {_escaped(text)}" if text else ""))
    if arguments:
        lines += ["Arguments:", "", *arguments, ""]
    if options:
        lines += ["Options:", "", *options, ""]
    return lines


def _walk(command: Any, ctx: typer.Context, path: str) -> list[str]:  # noqa: ANN401
    if not isinstance(command, TyperGroup):
        return _section(command, ctx, path)
    lines = _section(command, ctx, path)
    for name in command.list_commands(ctx):
        child = command.get_command(ctx, name)
        if child is None or child.hidden:
            continue
        lines += _walk(child, typer.Context(child, info_name=name, parent=ctx), f"{path} {name}")
    return lines


def render() -> str:
    """Return the generated reference, one section per visible command."""
    root = typer.main.get_command(app)
    ctx = typer.Context(root, info_name="bookshelf")
    lines = _walk(root, ctx, "bookshelf")
    return "\n".join(lines).rstrip() + "\n"


def rewritten(page: str) -> str:
    """Return ``page`` with the generated region replaced by a fresh render."""
    head, _, rest = page.partition(BEGIN)
    _, _, tail = rest.partition(END)
    return f"{head}{BEGIN}\n\n{render()}\n{END}{tail}"


def main(argv: list[str]) -> int:
    page = PAGE.read_text()
    fresh = rewritten(page)
    if "--check" in argv:
        if fresh != page:
            print(f"{PAGE} is stale. Run 'make cli-reference'.", file=sys.stderr)
            return 1
        return 0
    PAGE.write_text(fresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
