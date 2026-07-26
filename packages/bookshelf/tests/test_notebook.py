"""Tests for bookshelf.publisher.notebook: papermill + nbconvert capture.

papermill and nbconvert are *not* installed in the base test environment
(they live behind the ``[publish]`` extra), so all tests that exercise the
public functions mock the boundary rather than calling the real libraries.

Test plan
---------
1. ``_require_publish_extra`` raises ``RuntimeError`` with the install hint
   when either dependency is absent.
2. ``prepare_notebook_items`` returns two items with the correct shape:
   - type ``"document"``
   - ``metadata.kind`` values ``"notebook"`` / ``"notebook-html"``
   - ``metadata.notebook_name`` is the notebook stem on both
   - ``dedupe=False`` on both (per-book dedupe contract)
   - ``hash`` matches ``sha256:<hex>`` of the file bytes
   - returned ``paths`` list matches order: ipynb first, html second
3. ``execute_notebook`` happy path: papermill and nbconvert are mocked,
   verify the right calls are made and an ``ExecutedNotebook`` is returned.
4. ``execute_notebook`` raises ``RuntimeError`` with actionable message when
   ``[publish]`` extra is missing (simulated via ``ImportError`` patch).
5. ``execute_notebook`` wraps a papermill failure as ``RuntimeError``.
6. ``execute_notebook`` wraps an nbconvert failure as ``RuntimeError``.
"""

import hashlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from bookshelf._core.hashing import sha256_file
from bookshelf.publisher.notebook import (
    ExecutedNotebook,
    _require_publish_extra,
    execute_notebook,
    prepare_notebook_items,
)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_executed(tmp_path: Path, name: str = "my_notebook") -> ExecutedNotebook:
    """Write real files and return an ``ExecutedNotebook`` pointing at them."""
    ipynb = tmp_path / f"{name}_executed.ipynb"
    html = tmp_path / f"{name}_executed.html"
    ipynb.write_bytes(b'{"cells": [], "nbformat": 4, "nbformat_minor": 5}')
    html.write_bytes(b"<html><body>rendered</body></html>")
    return ExecutedNotebook(name=name, ipynb_path=ipynb, html_path=html)


class TestRequirePublishExtra:
    """``_require_publish_extra`` raises with a helpful pip command."""

    def test_raises_when_papermill_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing papermill triggers RuntimeError naming bookshelf[publish]."""
        # Remove papermill from sys.modules so the import inside the function fails.
        monkeypatch.setitem(sys.modules, "papermill", None)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="pip install bookshelf\\[publish\\]"):
            _require_publish_extra()

    def test_raises_when_nbconvert_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing nbconvert triggers RuntimeError naming bookshelf[publish]."""
        monkeypatch.setitem(sys.modules, "nbconvert", None)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="pip install bookshelf\\[publish\\]"):
            _require_publish_extra()

    def test_names_missing_packages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Error message lists the specific missing package names."""
        monkeypatch.setitem(sys.modules, "papermill", None)  # type: ignore[arg-type]
        monkeypatch.setitem(sys.modules, "nbconvert", None)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="papermill"):
            _require_publish_extra()

    def test_passes_when_both_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No error when both libraries can be imported."""
        # Stub both with dummy modules so the import check passes.
        monkeypatch.setitem(sys.modules, "papermill", ModuleType("papermill"))
        monkeypatch.setitem(sys.modules, "nbconvert", ModuleType("nbconvert"))
        # Should not raise.
        _require_publish_extra()


class TestPrepareNotebookItems:
    """``prepare_notebook_items`` returns correctly-shaped registration items."""

    def test_returns_two_items_and_two_paths(self, tmp_path: Path) -> None:
        """Exactly two items and two paths are returned."""
        executed = _make_executed(tmp_path)
        items, paths = prepare_notebook_items(executed)
        assert len(items) == 2
        assert len(paths) == 2

    def test_ipynb_item_first(self, tmp_path: Path) -> None:
        """First item is the ``.ipynb`` (``kind=notebook``)."""
        executed = _make_executed(tmp_path)
        items, paths = prepare_notebook_items(executed)
        assert items[0].metadata["kind"] == "notebook"
        assert paths[0] == executed.ipynb_path

    def test_html_item_second(self, tmp_path: Path) -> None:
        """Second item is the HTML render (``kind=notebook-html``)."""
        executed = _make_executed(tmp_path)
        items, paths = prepare_notebook_items(executed)
        assert items[1].metadata["kind"] == "notebook-html"
        assert paths[1] == executed.html_path

    def test_both_items_are_document_type(self, tmp_path: Path) -> None:
        """Both items carry ``type='document'``."""
        executed = _make_executed(tmp_path)
        items, _ = prepare_notebook_items(executed)
        assert items[0].type == "document"
        assert items[1].type == "document"

    def test_notebook_name_present_on_both(self, tmp_path: Path) -> None:
        """``metadata.notebook_name`` equals the notebook stem on both items."""
        executed = _make_executed(tmp_path, name="cool_analysis")
        items, _ = prepare_notebook_items(executed)
        assert items[0].metadata["notebook_name"] == "cool_analysis"
        assert items[1].metadata["notebook_name"] == "cool_analysis"

    def test_dedupe_false_on_both(self, tmp_path: Path) -> None:
        """``dedupe=False`` on both items: per-book dedupe contract."""
        executed = _make_executed(tmp_path)
        items, _ = prepare_notebook_items(executed)
        assert items[0].dedupe is False
        assert items[1].dedupe is False

    def test_hashes_match_file_bytes(self, tmp_path: Path) -> None:
        """``hash`` values match ``sha256:<hex>`` of the actual file bytes."""
        executed = _make_executed(tmp_path)
        items, _ = prepare_notebook_items(executed)

        expected_ipynb = "sha256:" + _sha256_hex(executed.ipynb_path.read_bytes())
        expected_html = "sha256:" + _sha256_hex(executed.html_path.read_bytes())

        assert items[0].hash == expected_ipynb
        assert items[1].hash == expected_html

    def test_visibility_hidden(self, tmp_path: Path) -> None:
        """Both items default to ``visibility='hidden'``."""
        executed = _make_executed(tmp_path)
        items, _ = prepare_notebook_items(executed)
        assert items[0].visibility == "hidden"
        assert items[1].visibility == "hidden"

    def test_different_notebook_bytes_produce_different_hashes(self, tmp_path: Path) -> None:
        """Two notebooks with different content produce different ``hash`` values."""
        nb1 = tmp_path / "nb1_executed.ipynb"
        nb2 = tmp_path / "nb2_executed.ipynb"
        html1 = tmp_path / "nb1_executed.html"
        html2 = tmp_path / "nb2_executed.html"
        nb1.write_bytes(b"notebook-content-a")
        nb2.write_bytes(b"notebook-content-b")
        html1.write_bytes(b"<html>a</html>")
        html2.write_bytes(b"<html>b</html>")

        ex1 = ExecutedNotebook(name="nb1", ipynb_path=nb1, html_path=html1)
        ex2 = ExecutedNotebook(name="nb2", ipynb_path=nb2, html_path=html2)

        items1, _ = prepare_notebook_items(ex1)
        items2, _ = prepare_notebook_items(ex2)

        assert items1[0].hash != items2[0].hash
        assert items1[1].hash != items2[1].hash


def _build_publish_stubs(
    tmp_path: Path,
    nb_stem: str = "analysis",
) -> tuple[MagicMock, MagicMock, MagicMock, Path]:
    """Return (mock_pm, mock_nbformat, mock_exporter_cls, source_nb_path).

    Sets up a fake executed notebook file on disk so the function can open it.
    """
    # The executed file that papermill would write.
    executed_ipynb = tmp_path / f"{nb_stem}_executed.ipynb"
    executed_ipynb.write_bytes(b'{"cells":[],"nbformat":4,"nbformat_minor":5}')

    # Source notebook that the caller references.
    source_nb = tmp_path / f"{nb_stem}.ipynb"
    source_nb.write_bytes(b'{"cells":[],"nbformat":4,"nbformat_minor":5}')

    mock_pm = MagicMock()
    mock_pm.execute_notebook.return_value = None

    mock_nb_node = MagicMock()
    mock_nbformat = MagicMock()
    mock_nbformat.read.return_value = mock_nb_node

    mock_exporter = MagicMock()
    mock_exporter.from_notebook_node.return_value = ("<html>rendered</html>", {})
    mock_exporter_cls = MagicMock(return_value=mock_exporter)

    return mock_pm, mock_nbformat, mock_exporter_cls, source_nb


class TestExecuteNotebook:
    """``execute_notebook`` happy path and error cases (mocked boundaries)."""

    def _patch_imports(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        nb_stem: str = "analysis",
    ) -> tuple[MagicMock, Path]:
        """Patch papermill / nbconvert / nbformat in sys.modules.

        Returns ``(mock_pm, source_nb_path)``.
        """
        mock_pm, mock_nbformat, mock_exporter_cls, source_nb = _build_publish_stubs(
            tmp_path, nb_stem
        )

        # Stub papermill module.
        pm_mod = ModuleType("papermill")
        pm_mod.execute_notebook = mock_pm.execute_notebook  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "papermill", pm_mod)

        # Stub nbformat module.
        nbformat_mod = ModuleType("nbformat")
        nbformat_mod.read = mock_nbformat.read  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "nbformat", nbformat_mod)

        # Stub nbconvert module + HTMLExporter.
        nbconvert_mod = ModuleType("nbconvert")
        nbconvert_mod.HTMLExporter = mock_exporter_cls  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "nbconvert", nbconvert_mod)

        # Stub nbconvert.preprocessors (imported by execute_notebook for type annotation).
        preprocessors_mod = ModuleType("nbconvert.preprocessors")
        preprocessors_mod.ExecutePreprocessor = MagicMock()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "nbconvert.preprocessors", preprocessors_mod)

        return mock_pm, source_nb

    def test_returns_executed_notebook(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Happy path returns an ``ExecutedNotebook`` with correct paths."""
        mock_pm, source_nb = self._patch_imports(monkeypatch, tmp_path)

        result = execute_notebook(source_nb, params={"alpha": 1.0}, workdir=tmp_path)

        assert isinstance(result, ExecutedNotebook)
        assert result.name == "analysis"
        assert result.ipynb_path.name == "analysis_executed.ipynb"
        assert result.html_path.name == "analysis_executed.html"

    def test_papermill_called_with_params(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Papermill ``execute_notebook`` is called with the supplied parameters."""
        mock_pm, source_nb = self._patch_imports(monkeypatch, tmp_path)

        execute_notebook(source_nb, params={"var": "Emissions|*"}, workdir=tmp_path)

        import sys as _sys

        pm = _sys.modules["papermill"]
        pm.execute_notebook.assert_called_once()
        call_kwargs = pm.execute_notebook.call_args
        # parameters kwarg should carry our params dict.
        assert call_kwargs.kwargs.get("parameters") == {"var": "Emissions|*"}

    def test_html_file_written(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """The rendered HTML file is written to disk."""
        self._patch_imports(monkeypatch, tmp_path)
        source_nb = tmp_path / "analysis.ipynb"

        result = execute_notebook(source_nb, workdir=tmp_path)

        assert result.html_path.exists()
        assert "<html>" in result.html_path.read_text()

    def test_empty_params_default(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """``params=None`` passes an empty dict to papermill."""
        mock_pm, source_nb = self._patch_imports(monkeypatch, tmp_path)

        execute_notebook(source_nb, params=None, workdir=tmp_path)

        import sys as _sys

        pm = _sys.modules["papermill"]
        call_kwargs = pm.execute_notebook.call_args
        assert call_kwargs.kwargs.get("parameters") == {}

    def test_raises_runtime_error_on_missing_extra(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """``execute_notebook`` raises ``RuntimeError`` with install hint when extra missing."""
        monkeypatch.setitem(sys.modules, "papermill", None)  # type: ignore[arg-type]
        source_nb = tmp_path / "nb.ipynb"
        source_nb.write_bytes(b"{}")

        with pytest.raises(RuntimeError, match="pip install bookshelf\\[publish\\]"):
            execute_notebook(source_nb, workdir=tmp_path)

    def test_wraps_papermill_failure_as_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A papermill execution error is wrapped in ``RuntimeError``."""
        mock_pm, source_nb = self._patch_imports(monkeypatch, tmp_path)

        import sys as _sys

        _sys.modules["papermill"].execute_notebook.side_effect = Exception("kernel died")

        with pytest.raises(RuntimeError, match="papermill execution"):
            execute_notebook(source_nb, workdir=tmp_path)

    def test_wraps_nbconvert_failure_as_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """An nbconvert render error is wrapped in ``RuntimeError``."""
        mock_pm, source_nb = self._patch_imports(monkeypatch, tmp_path)

        import sys as _sys

        nbformat_mod = _sys.modules["nbformat"]
        nbformat_mod.read.side_effect = Exception("bad notebook format")

        with pytest.raises(RuntimeError, match="nbconvert HTML render"):
            execute_notebook(source_nb, workdir=tmp_path)


def test_hash_file_format(tmp_path: Path) -> None:
    """``sha256_file`` returns a ``sha256:<hex>`` string for a file."""
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello world")
    result = sha256_file(f)
    expected_hex = _sha256_hex(b"hello world")
    assert result == f"sha256:{expected_hex}"
