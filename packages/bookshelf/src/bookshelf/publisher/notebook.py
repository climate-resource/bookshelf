"""Notebook capture for the bookshelf publish flow.

When a recipe declares ``books[].notebook``, the executed notebook and its
rendered HTML are captured as first-class ``DOCUMENT`` resources and attached
as Book Entries alongside the data outputs.

**Requires the** ``[publish]`` **extra** — ``papermill`` and ``nbconvert`` are
*not* installed with the base package.
Install them with::

    pip install bookshelf[publish]

Two resources are produced per notebook:

- The executed ``.ipynb`` (``metadata.kind = "notebook"``).
- An ``nbconvert``-rendered ``.html`` (``metadata.kind = "notebook-html"``).

Both carry ``metadata.notebook_name`` so consumers can pair them.
Both are registered with ``dedupe=False`` (per the dedupe contract in the
team plan): each book edition must produce a *distinct* entry resource,
even if the bytes happen to be identical to a previous edition.

Usage (called by the pipeline wiring in ``publish.py``)::

    from bookshelf.publisher.notebook import execute_notebook, prepare_notebook_items

    executed = execute_notebook(notebook_path, params=book.activity.params, workdir=cwd)
    items, paths = prepare_notebook_items(executed)
    # items: list[RegisterResourceItem] ready for bs.register_outputs()
    # paths: list[Path] — the local files in the same order
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

from bookshelf._core.hashing import sha256_file
from bookshelf.publisher._models import RegisterResourceItem


def _require_publish_extra() -> None:
    """Raise ``RuntimeError`` when the ``[publish]`` extra is not installed.

    Called at the top of every public function so the error surfaces
    immediately rather than on an attribute access deep inside a library.
    """
    missing: list[str] = []
    try:
        import papermill  # noqa: F401
    except ImportError:
        missing.append("papermill")
    try:
        import nbconvert  # noqa: F401
    except ImportError:
        missing.append("nbconvert")

    if missing:
        raise RuntimeError(
            f"Notebook capture requires {', '.join(missing)}, which are not installed.\n"
            "Install the publish extra with:\n\n"
            "    pip install bookshelf[publish]\n"
        )


@dataclass
class ExecutedNotebook:
    """Paths produced by a successful papermill + nbconvert run.

    ``name`` is a short identifier derived from the notebook file stem
    (used as ``metadata.notebook_name`` to pair the two resources).
    ``ipynb_path`` is the *executed* notebook (papermill output).
    ``html_path`` is the ``nbconvert``-rendered HTML.
    """

    name: str
    ipynb_path: Path
    html_path: Path


def execute_notebook(
    notebook_path: Path,
    params: dict[str, Any] | None = None,
    workdir: Path | None = None,
) -> ExecutedNotebook:
    """Execute ``notebook_path`` via papermill and render it to HTML with nbconvert.

    Parameters
    ----------
    notebook_path:
        Path to the source ``.ipynb`` file (before execution).
    params:
        Papermill parameters injected into the notebook
        (corresponds to ``books[].activity.params`` in the recipe).
    workdir:
        Working directory for the notebook kernel.
        Defaults to the directory containing ``notebook_path``.

    Returns
    -------
    ExecutedNotebook
        Paths to the executed ``.ipynb`` and the rendered ``.html``.

    Raises
    ------
    RuntimeError
        If ``bookshelf[publish]`` is not installed,
        or if papermill / nbconvert fail.
    """
    _require_publish_extra()

    import nbformat  # noqa: PLC0415
    import papermill as pm  # noqa: PLC0415
    from nbconvert import HTMLExporter  # noqa: PLC0415

    if workdir is None:
        workdir = notebook_path.parent

    notebook_path = notebook_path.resolve()
    stem = notebook_path.stem
    executed_path = workdir / f"{stem}_executed.ipynb"
    html_path = workdir / f"{stem}_executed.html"

    # Run the notebook via papermill, injecting parameters.
    try:
        pm.execute_notebook(
            str(notebook_path),
            str(executed_path),
            parameters=params or {},
            cwd=str(workdir),
        )
    except Exception as exc:
        raise RuntimeError(f"papermill execution of {notebook_path} failed: {exc}") from exc

    # Render the executed notebook to HTML via the nbconvert Python API.
    try:
        with executed_path.open("r", encoding="utf-8") as fh:
            nb = nbformat.read(fh, as_version=4)  # type: ignore[no-untyped-call]

        exporter = HTMLExporter()  # type: ignore[no-untyped-call]
        html_body, _resources = exporter.from_notebook_node(nb)
        html_path.write_text(html_body, encoding="utf-8")
    except Exception as exc:
        raise RuntimeError(f"nbconvert HTML render of {executed_path} failed: {exc}") from exc

    return ExecutedNotebook(
        name=stem,
        ipynb_path=executed_path,
        html_path=html_path,
    )


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


def prepare_notebook_items(
    executed: ExecutedNotebook,
) -> tuple[list[RegisterResourceItem], list[Path]]:
    """Build :class:`RegisterResourceItem` objects for the two notebook artifacts.

    Returns a ``(items, paths)`` pair where ``items[i]`` corresponds to
    ``paths[i]``.
    The caller passes ``items`` to ``bs.register_outputs()``
    and later calls ``bs.attach_entry()`` for each.

    **Dedupe contract** — both items carry ``dedupe=False``
    so the backend skips alias detection.
    Each book edition must produce a *distinct* entry resource even when
    the notebook bytes are identical to a previous edition.

    Parameters
    ----------
    executed:
        An :class:`ExecutedNotebook` returned by :func:`execute_notebook`.

    Returns
    -------
    tuple[list[RegisterResourceItem], list[Path]]
        ``items`` — two registration items (ipynb first, html second).
        ``paths`` — corresponding local file paths in the same order.
    """
    ipynb_item = RegisterResourceItem(
        type="document",
        hash=sha256_file(executed.ipynb_path),
        visibility="hidden",
        metadata={
            "kind": "notebook",
            "notebook_name": executed.name,
        },
        dedupe=False,
    )
    html_item = RegisterResourceItem(
        type="document",
        hash=sha256_file(executed.html_path),
        visibility="hidden",
        metadata={
            "kind": "notebook-html",
            "notebook_name": executed.name,
        },
        dedupe=False,
    )

    return [ipynb_item, html_item], [executed.ipynb_path, executed.html_path]


__all__ = [
    "ExecutedNotebook",
    "execute_python_build",
    "execute_notebook",
    "prepare_notebook_items",
]
