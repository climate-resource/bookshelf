"""What ``run_record`` refuses, and what it records, when a build or its caller misbehaves."""

import subprocess
import textwrap
from pathlib import Path

import pytest

from bookshelf._core.errors import BookshelfError
from bookshelf.publisher import recording as recording_module
from bookshelf.publisher.bundle import MANIFEST_NAME, Bundle
from bookshelf.publisher.record import RecordRefusedError, parse_parameters, run_record

_VERSION = "v1.0.0"
_ORIGIN = "https://github.com/example/feedstock"

_RECIPE = f"""\
volume:
  name: my-dataset
build:
  notebook: build.py
books:
  - version: "{_VERSION}"
    license: MIT
"""

_WRITES_ONE = """\
import bookshelf

bs, book = bookshelf.setup()
book.write("data", b"payload", type="document")
book.publish()
"""

_NO_HOOKS = ("-c", "core.hooksPath=/dev/null")


@pytest.fixture
def pinned_code_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """A scratch directory is no clone to read a code ref from."""
    monkeypatch.setattr(
        recording_module, "derive_code_ref", lambda: "https://example.invalid/test@0"
    )


def _feedstock(root: Path, build: str = _WRITES_ONE) -> Path:
    """Write a recipe and build file into ``root`` and return the recipe."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "build.py").write_text(textwrap.dedent(build), encoding="utf-8")
    recipe = root / "bookshelf.yaml"
    recipe.write_text(_RECIPE, encoding="utf-8")
    return recipe


def _record(root: Path, bundle: Path, **kwargs: object) -> dict[str, object]:
    return run_record(
        build_path=None,
        recipe_path=root / "bookshelf.yaml",
        bundle_path=bundle,
        version=_VERSION,
        cwd=root,
        **kwargs,  # type: ignore[arg-type]
    )


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *_NO_HOOKS, *args], cwd=cwd, check=True, capture_output=True)


_USES_AN_INPUT = """\
import bookshelf

bs, book = bookshelf.setup()
raw = bs.use("raw")
book.write("data", raw.path.read_bytes(), type="document", used=[raw])
book.publish()
"""


def _committed_feedstock(root: Path, build: str = _USES_AN_INPUT) -> Path:
    """A clean clone with an origin, ignoring its bundle the way the template does.

    The build reads a checked-in input first, which lands bytes before any activity opens.
    """
    _feedstock(root, build)
    (root / "bookshelf.yaml").write_text(
        _RECIPE + "    resources:\n      raw:\n        type: tabular\n        path: raw.csv\n",
        encoding="utf-8",
    )
    (root / "raw.csv").write_text("a,b\n", encoding="utf-8")
    (root / ".gitignore").write_text("bundle/\n", encoding="utf-8")
    _git(root, "init")
    _git(root, "remote", "add", "origin", _ORIGIN)
    _git(root, "add", ".")
    _git(root, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-m", "one")
    return root


def _code_ref(bundle: Path) -> str:
    activity = Bundle.read(bundle).manifest.activity
    assert activity is not None
    return activity.code_ref


@pytest.mark.usefixtures("pinned_code_ref")
class TestTheBundleTarget:
    """Replacing a bundle deletes the target, so only a bundle may be replaced."""

    def test_a_directory_that_is_not_a_bundle_is_left_alone(self, tmp_path: Path) -> None:
        _feedstock(tmp_path)
        inputs = tmp_path / "inputs"
        inputs.mkdir()
        (inputs / "raw.csv").write_text("a,b\n", encoding="utf-8")

        with pytest.raises(RecordRefusedError, match="not a bundle"):
            _record(tmp_path, inputs)

        assert (inputs / "raw.csv").read_text(encoding="utf-8") == "a,b\n"

    def test_the_feedstock_itself_is_never_replaced(self, tmp_path: Path) -> None:
        """Even holding a manifest, a directory with the recipe in it is the feedstock."""
        _feedstock(tmp_path)
        (tmp_path / MANIFEST_NAME).write_text("schema_version: 1.0.0\n", encoding="utf-8")

        with pytest.raises(RecordRefusedError, match="holds the recipe"):
            _record(tmp_path, tmp_path)

        assert (tmp_path / "build.py").is_file()

    def test_a_regular_file_is_refused_before_the_build_runs(self, tmp_path: Path) -> None:
        _feedstock(tmp_path, _WRITES_ONE + "open('ran', 'w').close()\n")
        target = tmp_path / "afile"
        target.write_text("keep", encoding="utf-8")

        with pytest.raises(RecordRefusedError, match="not a directory"):
            _record(tmp_path, target)

        assert target.read_text(encoding="utf-8") == "keep"
        assert not (tmp_path / "ran").exists()
        assert not list(tmp_path.glob(".afile-*"))

    def test_an_earlier_bundle_is_replaced(self, tmp_path: Path) -> None:
        _feedstock(tmp_path)
        _record(tmp_path, tmp_path / "bundle")

        _record(tmp_path, tmp_path / "bundle")

        assert Bundle.read(tmp_path / "bundle").manifest.book is not None

    def test_the_feedstock_is_found_through_a_differently_cased_path(self, tmp_path: Path) -> None:
        root = tmp_path / "force3"
        _feedstock(root)
        (root / MANIFEST_NAME).write_text("schema_version: '3.10'\n", encoding="utf-8")
        cased = tmp_path / "FORCE3"
        if not cased.exists():
            pytest.skip("the filesystem is case sensitive")

        with pytest.raises(RecordRefusedError, match="holds the recipe"):
            _record(root, cased)

        assert (root / "build.py").is_file()

    @pytest.mark.parametrize(
        "manifest",
        ["garbage\n", "schema_version: '3.10'\nunknown: 1\n- x\n", ""],
        ids=["scalar", "invalid-yaml", "empty"],
    )
    def test_a_manifest_that_is_not_a_bundle_manifest_is_left_alone(
        self, tmp_path: Path, manifest: str
    ) -> None:
        _feedstock(tmp_path)
        builds = tmp_path / "builds"
        builds.mkdir()
        (builds / MANIFEST_NAME).write_text(manifest, encoding="utf-8")

        with pytest.raises(RecordRefusedError, match="not a bundle"):
            _record(tmp_path, builds)

        assert (builds / MANIFEST_NAME).read_text(encoding="utf-8") == manifest

    def test_a_bundle_manifest_beside_other_files_is_left_alone(self, tmp_path: Path) -> None:
        _feedstock(tmp_path)
        _record(tmp_path, tmp_path / "bundle")
        (tmp_path / "bundle" / "notes.md").write_text("keep", encoding="utf-8")

        with pytest.raises(RecordRefusedError, match=r"notes\.md"):
            _record(tmp_path, tmp_path / "bundle")

        assert (tmp_path / "bundle" / "notes.md").read_text(encoding="utf-8") == "keep"

    def test_a_stray_file_under_resources_is_left_alone(self, tmp_path: Path) -> None:
        _feedstock(tmp_path)
        _record(tmp_path, tmp_path / "bundle")
        (tmp_path / "bundle" / "resources" / "keep.txt").write_text("keep", encoding="utf-8")

        with pytest.raises(RecordRefusedError, match=r"keep\.txt"):
            _record(tmp_path, tmp_path / "bundle")

    def test_a_directory_named_like_finder_metadata_is_left_alone(self, tmp_path: Path) -> None:
        _feedstock(tmp_path)
        _record(tmp_path, tmp_path / "bundle")
        (tmp_path / "bundle" / ".DS_Store").mkdir()
        (tmp_path / "bundle" / ".DS_Store" / "keep.txt").write_text("keep", encoding="utf-8")

        with pytest.raises(RecordRefusedError, match=r"\.DS_Store"):
            _record(tmp_path, tmp_path / "bundle")

        assert (tmp_path / "bundle" / ".DS_Store" / "keep.txt").is_file()

    def test_a_symlinked_bundle_is_refused_and_its_target_kept(self, tmp_path: Path) -> None:
        root = tmp_path / "feedstock"
        _feedstock(root)
        outside = tmp_path / "outside"
        _record(root, outside)
        (root / "bundle").symlink_to(outside, target_is_directory=True)
        before = sorted(path.name for path in outside.iterdir())

        with pytest.raises(RecordRefusedError, match="symbolic link"):
            _record(root, root / "bundle")

        assert sorted(path.name for path in outside.iterdir()) == before
        assert (root / "bundle").is_symlink()

    def test_what_the_build_writes_into_the_target_is_kept(self, tmp_path: Path) -> None:
        build = "import os\n\nos.makedirs('bundle')\nopen('bundle/out.csv', 'w').close()\n"
        _feedstock(tmp_path, build + _WRITES_ONE)

        with pytest.raises(RecordRefusedError, match="not a bundle"):
            _record(tmp_path, tmp_path / "bundle")

        assert (tmp_path / "bundle" / "out.csv").is_file()

    def test_an_empty_directory_is_replaced(self, tmp_path: Path) -> None:
        _feedstock(tmp_path)
        (tmp_path / "bundle").mkdir()

        _record(tmp_path, tmp_path / "bundle")

        assert (tmp_path / "bundle" / MANIFEST_NAME).is_file()


@pytest.mark.usefixtures("pinned_code_ref")
class TestABuildThatStopsItself:
    @pytest.mark.parametrize("code", [0, 3])
    def test_sys_exit_fails_the_record_and_keeps_the_earlier_bundle(
        self, tmp_path: Path, code: int
    ) -> None:
        """An exit in the build is never a recorded build, whatever code it exits with."""
        _feedstock(tmp_path)
        _record(tmp_path, tmp_path / "bundle")
        before = (tmp_path / "bundle" / MANIFEST_NAME).read_bytes()
        (tmp_path / "build.py").write_text(f"import sys\nsys.exit({code})\n", encoding="utf-8")

        with pytest.raises(BookshelfError, match=rf"sys\.exit\({code}\)"):
            _record(tmp_path, tmp_path / "bundle")

        assert (tmp_path / "bundle" / MANIFEST_NAME).read_bytes() == before

    def test_a_build_that_writes_nothing_says_so(self, tmp_path: Path) -> None:
        _feedstock(tmp_path, "import bookshelf\n\nbookshelf.setup()\n")

        with pytest.raises(BookshelfError, match="recorded no outputs"):
            _record(tmp_path, tmp_path / "bundle")


@pytest.mark.usefixtures("pinned_code_ref")
class TestWhatTheBuildRecords:
    def test_an_invalid_resource_name_is_a_bookshelf_error(self, tmp_path: Path) -> None:
        build = 'import bookshelf\n\nbs, book = bookshelf.setup()\nbook.write("Bad Name", b"x", type="document")\n'
        _feedstock(tmp_path, build)

        with pytest.raises(BookshelfError, match="Bad Name"):
            _record(tmp_path, tmp_path / "bundle")

    def test_a_name_the_evidence_documents_take_is_named_as_reserved(self, tmp_path: Path) -> None:
        build = 'import bookshelf\n\nbs, book = bookshelf.setup()\nbook.write("build.ipynb", b"x", type="document")\n'
        _feedstock(tmp_path, build)

        with pytest.raises(BookshelfError, match="'build.ipynb' is reserved"):
            _record(tmp_path, tmp_path / "bundle")

    @pytest.mark.parametrize(
        "uri",
        ["http://example.com/x", "https://10.0.0.1/x", "file:///etc/passwd", "https://127.1/x"],
        ids=["http", "private", "file", "short-loopback"],
    )
    def test_a_pointer_validate_would_refuse_is_never_recorded(
        self, tmp_path: Path, uri: str
    ) -> None:
        build = (
            "import bookshelf\n\nbs, book = bookshelf.setup()\n"
            f"ptr = bs.register_external(type='tabular', name='ptr', uri={uri!r})\n"
            "book.attach(ptr)\nbook.publish()\n"
        )
        _feedstock(tmp_path, build)

        with pytest.raises(BookshelfError, match="private or reserved|neither an https"):
            _record(tmp_path, tmp_path / "bundle")

        assert not (tmp_path / "bundle").exists()

    def test_a_duplicate_resource_name_is_a_bookshelf_error(self, tmp_path: Path) -> None:
        _feedstock(
            tmp_path,
            _WRITES_ONE.replace(
                "book.publish()", 'book.write("data", b"again", type="document")\nbook.publish()'
            ),
        )

        with pytest.raises(BookshelfError, match="'data' is already recorded"):
            _record(tmp_path, tmp_path / "bundle")

    def test_a_lone_surrogate_in_the_output_still_renders(self, tmp_path: Path) -> None:
        _feedstock(tmp_path, _WRITES_ONE + "print('\\udcff')\n")

        _record(tmp_path, tmp_path / "bundle")

        assert (tmp_path / "bundle" / MANIFEST_NAME).is_file()


class TestTheCodeRef:
    def test_a_clean_clone_records_a_clean_code_ref(self, tmp_path: Path) -> None:
        """The staging directory sits in the clone, and must not make it read as dirty."""
        root = _committed_feedstock(tmp_path / "feedstock")

        _record(root, root / "bundle")

        assert not _code_ref(root / "bundle").endswith("+dirty")

    def test_a_build_that_changes_directory_still_records_its_clone(self, tmp_path: Path) -> None:
        root = _committed_feedstock(
            tmp_path / "feedstock", "import os\n\nos.chdir('/')\n" + _USES_AN_INPUT
        )

        _record(root, root / "bundle")

        assert _code_ref(root / "bundle").startswith(f"{_ORIGIN}@")


class TestParameters:
    @pytest.mark.parametrize(
        "value",
        ["X=2024-01-01", "X=!!binary aGVsbG8=", "X=.nan", "X=.inf", "X=[1, .nan]"],
        ids=["date", "binary", "nan", "inf", "nested-nan"],
    )
    def test_a_value_json_cannot_carry_is_refused(self, value: str) -> None:
        with pytest.raises(RecordRefusedError, match="cannot be recorded"):
            parse_parameters([value])

    @pytest.mark.parametrize(
        "value", ["X={1: a, b: c}", "X={1: 2}"], ids=["mixed-keys", "int-keys"]
    )
    def test_a_mapping_json_would_record_differently_is_refused(self, value: str) -> None:
        with pytest.raises(RecordRefusedError, match="cannot be recorded"):
            parse_parameters([value])

    @pytest.mark.usefixtures("pinned_code_ref")
    def test_a_lone_surrogate_from_python_is_refused_before_the_build_runs(
        self, tmp_path: Path
    ) -> None:
        _feedstock(tmp_path, "X = 'a'\n" + _WRITES_ONE)

        with pytest.raises(RecordRefusedError, match="cannot be recorded"):
            _record(tmp_path, tmp_path / "bundle", parameters={"X": "\udc80"})

    def test_malformed_yaml_is_refused(self) -> None:
        with pytest.raises(RecordRefusedError, match="not valid YAML"):
            parse_parameters(["X=[1,2"])

    @pytest.mark.parametrize("key", ["a-b", "1x", "__name__", "class"])
    def test_a_key_that_is_not_a_build_variable_is_refused(self, key: str) -> None:
        with pytest.raises(RecordRefusedError, match=repr(key)):
            parse_parameters([f"{key}=1"])

    def test_json_values_parse(self) -> None:
        assert parse_parameters(["a=1", "b=x", "c=[1, 2]", "d={k: v}", "e=null"]) == {
            "a": 1,
            "b": "x",
            "c": [1, 2],
            "d": {"k": "v"},
            "e": None,
        }

    @pytest.mark.usefixtures("pinned_code_ref")
    def test_a_parameter_the_build_never_assigns_is_refused_before_it_runs(
        self, tmp_path: Path
    ) -> None:
        _feedstock(tmp_path, "TAG = 'default'\n" + _WRITES_ONE + "open('ran', 'w').close()\n")

        with pytest.raises(RecordRefusedError, match="'TAGG'.*'TAG'"):
            _record(tmp_path, tmp_path / "bundle", parameters={"TAGG": "x"})

        assert not (tmp_path / "ran").exists()

    @pytest.mark.usefixtures("pinned_code_ref")
    def test_a_parameter_from_python_is_checked_before_the_build_runs(self, tmp_path: Path) -> None:
        _feedstock(tmp_path, "X = 1.0\n" + _WRITES_ONE + "open('ran', 'w').close()\n")

        with pytest.raises(RecordRefusedError, match="cannot be recorded"):
            _record(tmp_path, tmp_path / "bundle", parameters={"X": float("nan")})

        assert not (tmp_path / "ran").exists()

    @pytest.mark.usefixtures("pinned_code_ref")
    def test_an_annotated_default_is_a_parameter(self, tmp_path: Path) -> None:
        _feedstock(tmp_path, "X: int = 1\nassert X == 2\n" + _WRITES_ONE)

        _record(tmp_path, tmp_path / "bundle", parameters={"X": 2})

    @pytest.mark.usefixtures("pinned_code_ref")
    @pytest.mark.parametrize("key", ["M", "K"])
    def test_a_chained_assignment_is_refused_before_the_build_runs(
        self, tmp_path: Path, key: str
    ) -> None:
        _feedstock(tmp_path, "M = K = 2\n" + _WRITES_ONE + "open('ran', 'w').close()\n")

        with pytest.raises(
            RecordRefusedError, match=f"'{key}' is assigned in a chained assignment"
        ):
            _record(tmp_path, tmp_path / "bundle", parameters={key: 3})

        assert not (tmp_path / "ran").exists()
