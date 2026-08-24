"""Notebook capture for a recorded build.

A recorded build executes a standalone Jupytext Python file
and captures the run as an executed ``.ipynb`` plus its ``nbconvert``-rendered HTML.
The recorder attaches both as ``DOCUMENT`` book entries alongside the data outputs.

**Requires the** ``[publish]`` **extra** for the HTML render:
``nbformat`` and ``nbconvert`` are *not* installed with the base package.
Install them with::

    pip install bookshelf[publish]
"""

import ast
import contextlib
import io
import json
import os
import sys
import threading
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ExecutedNotebook:
    """Paths produced by a successful build execution and render.

    ``name`` is a short identifier derived from the build file stem.
    ``ipynb_path`` is the executed notebook.
    ``html_path`` is the ``nbconvert``-rendered HTML.
    """

    name: str
    ipynb_path: Path
    html_path: Path


# Serialises the cwd and sys.path window below, which is process global.
_BUILD_EXECUTION_LOCK = threading.Lock()


def execute_python_build(
    build_path: Path,
    *,
    params: Mapping[str, Any],
    workdir: Path,
    artifacts_dir: Path,
) -> ExecutedNotebook:
    """Execute a standalone Jupytext Python build and capture its outputs."""
    source = build_path.read_text(encoding="utf-8")
    globals_dict: dict[str, Any] = {
        "__file__": str(build_path),
        "__name__": "__main__",
        **params,
    }
    executed_cells: list[dict[str, Any]] = []
    with _BUILD_EXECUTION_LOCK:
        old_cwd = Path.cwd()
        old_path = list(sys.path)
        try:
            os.chdir(workdir)
            sys.path.insert(0, str(workdir))
            for execution_count, cell_source in enumerate(_source_cells(source), start=1):
                outputs = _execute_python_cell(
                    cell_source,
                    globals_dict=globals_dict,
                    filename=f"{build_path}::cell{execution_count}",
                    parameter_names=params.keys(),
                )
                executed_cells.append(
                    _code_cell(cell_source, execution_count=execution_count, outputs=outputs)
                )
        finally:
            os.chdir(old_cwd)
            sys.path[:] = old_path

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    stem = build_path.stem
    ipynb_path = artifacts_dir / f"{stem}_executed.ipynb"
    html_path = artifacts_dir / f"{stem}_executed.html"
    ipynb_path.write_text(_notebook_json(executed_cells, params=params), encoding="utf-8")
    _render_executed_notebook(ipynb_path, html_path)
    return ExecutedNotebook(name=stem, ipynb_path=ipynb_path, html_path=html_path)


def _source_cells(source: str) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    for line in source.splitlines(keepends=True):
        if line.startswith("# %%"):
            if current:
                cells.append("".join(current))
                current = []
            continue
        current.append(line)
    if current or not cells:
        cells.append("".join(current))
    return cells


def _execute_python_cell(
    source: str,
    *,
    globals_dict: dict[str, Any],
    filename: str,
    parameter_names: Collection[str] = (),
) -> list[dict[str, Any]]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    module = ast.parse(source, filename=filename)
    overridden = frozenset(parameter_names)
    module.body = [
        statement
        for statement in module.body
        if not _defines_parameter_default(statement, overridden)
    ]
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        exec(compile(module, filename, "exec"), globals_dict)  # noqa: S102
    outputs: list[dict[str, Any]] = []
    if stdout.getvalue():
        outputs.append({"name": "stdout", "output_type": "stream", "text": stdout.getvalue()})
    if stderr.getvalue():
        outputs.append({"name": "stderr", "output_type": "stream", "text": stderr.getvalue()})
    return outputs


def _defines_parameter_default(statement: ast.stmt, names: frozenset[str]) -> bool:
    """Identify a top-level default superseded by a record parameter."""
    if isinstance(statement, ast.Assign):
        return any(
            isinstance(target, ast.Name) and target.id in names for target in statement.targets
        )
    return (
        isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and statement.target.id in names
    )


def _notebook_json(cells: list[dict[str, Any]], *, params: Mapping[str, Any]) -> str:
    notebook = {
        "cells": cells,
        "metadata": {
            "bookshelf": {"record_parameters": dict(params)},
            "jupytext": {"formats": "py:percent,ipynb"},
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    return json.dumps(notebook, indent=2, sort_keys=True) + "\n"


def _code_cell(
    source: str,
    *,
    execution_count: int,
    outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "cell_type": "code",
        "execution_count": execution_count,
        "id": f"cell-{execution_count}",
        "metadata": {},
        "outputs": outputs,
        "source": source.splitlines(keepends=True),
    }


def _render_executed_notebook(ipynb_path: Path, html_path: Path) -> None:
    try:
        import nbformat  # noqa: PLC0415
        from nbconvert import HTMLExporter  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError(
            "Notebook HTML rendering requires nbformat and nbconvert. "
            "Install the publish extra with 'pip install bookshelf[publish]'."
        ) from exc

    with ipynb_path.open("r", encoding="utf-8") as fh:
        notebook = nbformat.read(fh, as_version=4)  # type: ignore[no-untyped-call]
    exporter = HTMLExporter()  # type: ignore[no-untyped-call]
    html_body, _resources = exporter.from_notebook_node(notebook)
    html_path.write_text(html_body, encoding="utf-8")


__all__ = [
    "ExecutedNotebook",
    "execute_python_build",
]
