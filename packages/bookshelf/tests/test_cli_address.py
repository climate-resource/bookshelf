"""Tests for the CLI address grammar."""

import pytest
from typer.testing import CliRunner

from bookshelf._cli import app
from bookshelf._cli._address import Address, parse_address
from bookshelf._cli._runtime import CliError

runner = CliRunner()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("primap-hist", Address("primap-hist")),
        ("primap-hist@v2.8", Address("primap-hist", "v2.8")),
        ("primap-hist@v2.8_e001", Address("primap-hist", "v2.8", 1)),
        ("primap-hist@v2.8_e003/by_country", Address("primap-hist", "v2.8", 3, "by_country")),
        ("primap-hist/by_country", Address("primap-hist", entry="by_country")),
        ("ngfs@v4_scenario_e011", Address("ngfs", "v4_scenario", 11)),
        ("ngfs@v1_e1000", Address("ngfs", "v1", 1000)),
        ("ngfs@v1_ebola", Address("ngfs", "v1_ebola")),
    ],
)
def test_a_well_formed_address_parses(text: str, expected: Address) -> None:
    assert parse_address(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "bad address",
        ".",
        "..",
        "primap-hist/..",
        "primap-hist@./by_country",
        "primap-hist@..",
        "vol@1_e",
        "vol@1_e0001",
        "vol@1_e000",
        "primap-hist@v2.8_e1",
        "primap-hist@_e001",
        "primap-hist@v2.8@x",
        "hadcrut@@v1",
        "primap-hist@v2.8_e٠٠١",
        "primap-hist@v2.8_e００１",
        "primap-hist@",
        "primap-hist/",
        "primap-hist@v2.8/a/b",
        "primap-hist@v2.8/x?y",
    ],
)
def test_a_malformed_address_is_a_usage_error(text: str) -> None:
    with pytest.raises(CliError) as caught:
        parse_address(text)

    assert caught.value.exit_code == 2


@pytest.mark.parametrize("text", [".", "..", "primap-hist@v2.8_e1", "primap-hist@v2.8@x"])
def test_show_refuses_a_malformed_address_before_the_api(
    monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    monkeypatch.setenv("BOOKSHELF_URL", "http://127.0.0.1:9")

    result = runner.invoke(app, ["show", text])

    assert result.exit_code == 2
    assert "malformed address" in result.stderr
