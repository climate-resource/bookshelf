"""The CLI exit-code table and the one renderer every command's output goes through."""

import json

import pytest
import typer

from bookshelf._cli._runtime import command_errors, emit_document, emit_payload
from bookshelf._core import errors


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (errors.AuthenticationError("no", status_code=401), 3),
        (errors.ForbiddenError("not yours", status_code=403), 4),
        (errors.NotFoundError("gone", status_code=404), 5),
        (errors.ValidationError("bad", status_code=422), 2),
        (errors.ServerError("boom", status_code=502), 6),
        (errors.TransportError("refused"), 6),
        (errors.ConflictError("clash", status_code=409), 1),
        (errors.UnexpectedResponseError("odd", status_code=418), 1),
    ],
)
def test_exit_code_table(exc: errors.BookshelfError, expected: int) -> None:
    with pytest.raises(typer.Exit) as excinfo, command_errors():
        raise exc
    assert excinfo.value.exit_code == expected


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ({"name": "example", "id": "v_1"}, "Name example\nId   v_1"),
        ({"missing": None}, "Missing -"),
        ({"dedupe": False, "converged": True}, "Dedupe    no\nConverged yes"),
        ({"topics": ["a", "b"]}, "Topics a, b"),
        ({"topics": []}, "Topics -"),
        ({"size_bytes": 2048}, "Size 2.0 kB"),
        ({"bytes_freed": 2048}, "Freed 2.0 kB"),
        ({"bytes": 2048}, "Bytes 2.0 kB"),
        ({"total_versions": 2}, "Total versions 2"),
    ],
)
def test_emit_document_renders_one_row_per_entry(
    document: dict[str, object], expected: str, capsys: pytest.CaptureFixture[str]
) -> None:
    emit_document(document)
    assert capsys.readouterr().out.rstrip("\n") == expected


def test_emit_document_indents_nested_blocks(capsys: pytest.CaptureFixture[str]) -> None:
    """A nested mapping aligns to its own widest label, not the parent's."""
    emit_document({"id": "bk_1", "stats": {"total_versions": 2, "editions": 3}})

    assert capsys.readouterr().out.rstrip("\n") == (
        "Id    bk_1\nStats\n  Total versions 2\n  Editions       3"
    )


def test_emit_document_repeats_a_block_per_item(capsys: pytest.CaptureFixture[str]) -> None:
    emit_document({"books": [{"volume": "a"}, {"volume": "b"}]})

    assert capsys.readouterr().out.rstrip("\n") == "Books\n  Volume a\n  Volume b"


def test_emit_document_keeps_every_item_of_a_mixed_list(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Arbitrary volume metadata can hold one, so dropping the odd item would lose data."""
    emit_document({"metadata": [{"name": "a"}, "legacy"]})

    assert "legacy" in capsys.readouterr().out


def test_emit_payload_writes_the_same_keys_either_way(capsys: pytest.CaptureFixture[str]) -> None:
    """The two outputs read one document, so they cannot describe different things."""
    document = {"outcome": "created", "size_bytes": 2048}

    emit_payload(document, json_output=True)
    assert json.loads(capsys.readouterr().out) == document

    emit_payload(document, json_output=False)
    assert capsys.readouterr().out.rstrip("\n") == "Outcome created\nSize    2.0 kB"
