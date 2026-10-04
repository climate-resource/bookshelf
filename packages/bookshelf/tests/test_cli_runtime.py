"""The CLI exit-code table and the one renderer every command's output goes through."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from bookshelf._cli import app
from bookshelf._cli._runtime import (
    EXIT_CODES,
    command_errors,
    emit_document,
    emit_payload,
    iso,
)
from bookshelf._core import errors
from bookshelf._produce.provenance import _CodeRefError


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (errors.AuthenticationError("no", status_code=401), 3),
        (errors.ForbiddenError("not yours", status_code=403), 4),
        (errors.NotFoundError("gone", status_code=404), 5),
        (errors.RequestValidationError("bad", status_code=422), 2),
        (errors.ServerError("boom", status_code=502), 6),
        (errors.TransportError("refused"), 6),
        (errors.ConflictError("clash", status_code=409), 8),
        (errors.UnexpectedResponseError("odd", status_code=418), 9),
        (errors.ContractError("wrong shape", status_code=200), 9),
        (errors.VersionNotFoundError("no such version", status_code=404), 5),
        (errors.AuthenticationRequiredError("log in"), 3),
        (errors.AuthConfigurationError("half a client pair"), 2),
        (errors.SelectionError("no such column"), 2),
        (_CodeRefError("not inside a git repository"), 2),
        (errors.BookshelfError("anything else"), 1),
        (errors.RateLimitError("slow down", status_code=429), 6),
        (errors.GatewayError("blocked", status_code=403), 6),
        (errors.ConfigurationError("bad url"), 2),
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
        ({"size_bytes": 2048}, "Size 2.0 KiB"),
        ({"bytes_freed": 2048}, "Freed 2.0 KiB"),
        ({"bytes": 2048}, "Bytes 2.0 KiB"),
        ({"bytes": 512}, "Bytes 512 B"),
        ({"max_bytes": 5 * 1024**3}, "Max 5.0 GiB"),
        ({"max_bytes": 3 * 1024**4}, "Max 3.0 TiB"),
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

    assert capsys.readouterr().out.rstrip("\n") == "Books\n  Volume a\n\n  Volume b"


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
    assert capsys.readouterr().out.rstrip("\n") == "Outcome created\nSize    2.0 KiB"


def test_iso_drops_microseconds() -> None:
    assert iso(datetime(2026, 10, 1, 4, 22, 25, 123456, tzinfo=UTC)) == "2026-10-01T04:22:25Z"


def test_an_env_token_refusal_names_the_env_token_remedy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A stored login cannot help while $BOOKSHELF_TOKEN shadows it."""
    monkeypatch.setenv("BOOKSHELF_TOKEN", "garbage")
    monkeypatch.setenv("BOOKSHELF_URL", "https://bookshelf.test")

    with pytest.raises(typer.Exit), command_errors():
        raise errors.AuthenticationError("no", status_code=401)

    err = capsys.readouterr().err
    assert "$BOOKSHELF_TOKEN" in err
    assert "auth login" not in err


def test_an_error_without_a_problem_names_the_request(capsys: pytest.CaptureFixture[str]) -> None:
    exc = errors.ServerError(
        "HTTP 502 Bad Gateway with a text/html body",
        status_code=502,
        request_method="GET",
        request_url="https://bookshelf.test/v1/books",
    )
    with pytest.raises(typer.Exit), command_errors():
        raise exc
    assert "GET https://bookshelf.test/v1/books" in capsys.readouterr().err


@pytest.mark.parametrize("command", [["search"], ["auth", "login", "--agent"]])
@pytest.mark.parametrize("url", ["not-a-url", "ftp://x"])
def test_a_malformed_api_url_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, command: list[str], url: str
) -> None:
    monkeypatch.setenv("BOOKSHELF_URL", url)

    result = CliRunner().invoke(app, command)

    assert result.exit_code == 2
    assert "BOOKSHELF_URL" in result.stderr
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_root_help_lists_every_exit_code() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    for code, meaning in EXIT_CODES:
        assert f"{code}  {meaning}" in result.stdout


def test_every_exit_code_is_documented() -> None:
    page = (Path(__file__).parents[3] / "docs" / "cli.md").read_text()

    for code, meaning in EXIT_CODES:
        assert f"| {code} | {meaning} |" in page
