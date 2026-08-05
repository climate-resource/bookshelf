"""Tests for bookshelf.publisher.notebook: standalone build execution and capture.

``nbformat`` and ``nbconvert`` live behind the ``[publish]`` extra,
so the render boundary is stubbed rather than called for real.
"""

import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from bookshelf.publisher.notebook import ExecutedNotebook, execute_python_build


@pytest.fixture
def render_stubs(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stub ``nbformat`` and ``nbconvert`` so the HTML render runs without the extra."""
    nbformat_mod = ModuleType("nbformat")
    nbformat_mod.read = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "nbformat", nbformat_mod)

    exporter = MagicMock()
    exporter.from_notebook_node.return_value = ("<html>rendered</html>", {})
    nbconvert_mod = ModuleType("nbconvert")
    nbconvert_mod.HTMLExporter = MagicMock(return_value=exporter)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "nbconvert", nbconvert_mod)

    return exporter


def _write_build(tmp_path: Path, source: str, name: str = "build") -> Path:
    build_path = tmp_path / f"{name}.py"
    build_path.write_text(source, encoding="utf-8")
    return build_path


def _executed_cells(executed: ExecutedNotebook) -> list[dict]:
    notebook = json.loads(executed.ipynb_path.read_text(encoding="utf-8"))
    cells: list[dict] = notebook["cells"]
    return cells


class TestExecutePythonBuild:
    """``execute_python_build`` runs a build file and captures the run."""

    def test_returns_executed_notebook_named_for_the_build(
        self, tmp_path: Path, render_stubs: MagicMock
    ) -> None:
        """The capture is named for the build file stem."""
        build_path = _write_build(tmp_path, "value = 1\n", name="primap")
        artifacts = tmp_path / "artifacts"

        executed = execute_python_build(
            build_path, params={}, workdir=tmp_path, artifacts_dir=artifacts
        )

        assert executed.name == "primap"
        assert executed.ipynb_path == artifacts / "primap_executed.ipynb"
        assert executed.html_path == artifacts / "primap_executed.html"

    def test_writes_both_artifacts(self, tmp_path: Path, render_stubs: MagicMock) -> None:
        """Both the executed notebook and its HTML render land in the artifacts directory."""
        build_path = _write_build(tmp_path, "value = 1\n")
        artifacts = tmp_path / "artifacts"

        executed = execute_python_build(
            build_path, params={}, workdir=tmp_path, artifacts_dir=artifacts
        )

        assert executed.ipynb_path.exists()
        assert executed.html_path.read_text(encoding="utf-8") == "<html>rendered</html>"

    def test_splits_the_source_on_cell_markers(
        self, tmp_path: Path, render_stubs: MagicMock
    ) -> None:
        """Each ``# %%`` marker starts a new captured cell."""
        build_path = _write_build(tmp_path, "# %%\nfirst = 1\n\n# %%\nsecond = 2\n")

        executed = execute_python_build(
            build_path, params={}, workdir=tmp_path, artifacts_dir=tmp_path / "artifacts"
        )

        cells = _executed_cells(executed)
        assert len(cells) == 2
        assert [cell["execution_count"] for cell in cells] == [1, 2]

    def test_a_marker_free_build_records_as_one_cell(
        self, tmp_path: Path, render_stubs: MagicMock
    ) -> None:
        """A build with no markers still records, as a single cell."""
        build_path = _write_build(tmp_path, "value = 1\n")

        executed = execute_python_build(
            build_path, params={}, workdir=tmp_path, artifacts_dir=tmp_path / "artifacts"
        )

        assert len(_executed_cells(executed)) == 1

    def test_captures_stdout_and_stderr(self, tmp_path: Path, render_stubs: MagicMock) -> None:
        """Printed output is captured as a stream output on its cell."""
        build_path = _write_build(
            tmp_path,
            "import sys\nprint('to stdout')\nprint('to stderr', file=sys.stderr)\n",
        )

        executed = execute_python_build(
            build_path, params={}, workdir=tmp_path, artifacts_dir=tmp_path / "artifacts"
        )

        outputs = _executed_cells(executed)[0]["outputs"]
        assert [output["name"] for output in outputs] == ["stdout", "stderr"]
        assert outputs[0]["text"] == "to stdout\n"

    def test_a_parameter_supersedes_its_declared_default(
        self, tmp_path: Path, render_stubs: MagicMock
    ) -> None:
        """A top-level default assignment is dropped when a parameter names it."""
        build_path = _write_build(tmp_path, "version = 'default'\nprint(version)\n")

        executed = execute_python_build(
            build_path,
            params={"version": "2.6"},
            workdir=tmp_path,
            artifacts_dir=tmp_path / "artifacts",
        )

        assert _executed_cells(executed)[0]["outputs"][0]["text"] == "2.6\n"

    def test_an_annotated_default_is_superseded_too(
        self, tmp_path: Path, render_stubs: MagicMock
    ) -> None:
        """An annotated top-level default is dropped on the same rule."""
        build_path = _write_build(tmp_path, "version: str = 'default'\nprint(version)\n")

        executed = execute_python_build(
            build_path,
            params={"version": "2.6"},
            workdir=tmp_path,
            artifacts_dir=tmp_path / "artifacts",
        )

        assert _executed_cells(executed)[0]["outputs"][0]["text"] == "2.6\n"

    def test_records_the_parameters_in_the_notebook_metadata(
        self, tmp_path: Path, render_stubs: MagicMock
    ) -> None:
        """The parameters the build ran under are recorded for provenance."""
        build_path = _write_build(tmp_path, "value = 1\n")

        executed = execute_python_build(
            build_path,
            params={"version": "2.6"},
            workdir=tmp_path,
            artifacts_dir=tmp_path / "artifacts",
        )

        notebook = json.loads(executed.ipynb_path.read_text(encoding="utf-8"))
        assert notebook["metadata"]["bookshelf"]["record_parameters"] == {"version": "2.6"}

    def test_runs_the_build_in_the_workdir(self, tmp_path: Path, render_stubs: MagicMock) -> None:
        """The build executes with ``workdir`` as the working directory."""
        workdir = tmp_path / "feedstock"
        workdir.mkdir()
        (workdir / "input.txt").write_text("payload", encoding="utf-8")
        build_path = _write_build(
            tmp_path, "from pathlib import Path\nprint(Path('input.txt').read_text())\n"
        )

        executed = execute_python_build(
            build_path, params={}, workdir=workdir, artifacts_dir=tmp_path / "artifacts"
        )

        assert _executed_cells(executed)[0]["outputs"][0]["text"] == "payload\n"

    def test_restores_the_working_directory_after_a_failure(
        self, tmp_path: Path, render_stubs: MagicMock
    ) -> None:
        """A raising build leaves the process working directory untouched."""
        workdir = tmp_path / "feedstock"
        workdir.mkdir()
        build_path = _write_build(tmp_path, "raise ValueError('build failed')\n")
        before = Path.cwd()

        with pytest.raises(ValueError, match="build failed"):
            execute_python_build(
                build_path, params={}, workdir=workdir, artifacts_dir=tmp_path / "artifacts"
            )

        assert Path.cwd() == before


class TestPublishExtraGating:
    """The HTML render reports the missing ``[publish]`` extra rather than an ImportError."""

    def test_reports_the_install_hint_when_the_extra_is_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing render dependency raises ``RuntimeError`` naming the extra."""
        monkeypatch.setitem(sys.modules, "nbconvert", None)  # type: ignore[arg-type]
        build_path = _write_build(tmp_path, "value = 1\n")

        with pytest.raises(RuntimeError, match=r"pip install bookshelf\[publish\]"):
            execute_python_build(
                build_path, params={}, workdir=tmp_path, artifacts_dir=tmp_path / "artifacts"
            )
