"""Tests for base-URL resolution and the explicit ``auth=`` coercion."""

from pathlib import Path

import pytest

from bookshelf._core import config, credentials
from bookshelf._core.auth import ClientCredentials, StaticToken
from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import ConfigurationError
from bookshelf._core.resolution import CredentialSource


@pytest.fixture(autouse=True)
def clean_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BOOKSHELF_TOKEN", "BOOKSHELF_AUTH", "BOOKSHELF_CLIENT_ID", "BOOKSHELF_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("BOOKSHELF_API_URL", raising=False)
    monkeypatch.setattr(credentials, "credentials_path", lambda: tmp_path / "credentials.json")


def test_base_url_argument_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_API_URL", "https://env.test")
    assert config.resolve_base_url("https://arg.test") == "https://arg.test"


def test_base_url_env_beats_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_URL", "https://env.test")
    assert config.resolve_base_url(None) == "https://env.test"


def test_the_api_url_alias_still_works_but_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_API_URL", "https://env.test")
    with pytest.warns(FutureWarning, match="set BOOKSHELF_URL instead"):
        assert config.resolve_base_url(None) == "https://env.test"


def test_base_url_defaults_to_production() -> None:
    assert config.resolve_base_url(None) == config.PRODUCTION_API_URL


def test_bare_string_coerces_to_static_token() -> None:
    assert isinstance(config.resolve_auth("bsat_x"), StaticToken)


def test_provider_instance_passes_through() -> None:
    provider = ClientCredentials("cid", "secret", token_url="https://issuer.test/token")
    assert config.resolve_auth(provider) is provider


def test_explicit_none_stays_unauthenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_TOKEN", "ambient")
    client = BookshelfClient("https://arg.test", auth=None)
    assert client.auth is None
    assert client.credential is None


def test_client_constructor_coerces_and_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOOKSHELF_URL", "https://env.test")
    client = BookshelfClient(auth="bsat_x")
    assert client.base_url == "https://env.test"
    assert isinstance(client.auth, StaticToken)
    assert client.credential is None

    client = BookshelfClient("https://arg.test")
    assert client.base_url == "https://arg.test"
    assert client.auth is None
    assert client.credential is not None
    assert client.credential.source is CredentialSource.NONE


@pytest.mark.filterwarnings("ignore:BOOKSHELF_API_URL is deprecated:FutureWarning")
@pytest.mark.parametrize("variable", ["BOOKSHELF_URL", "BOOKSHELF_API_URL"])
def test_a_bad_url_names_the_variable_that_supplied_it(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    monkeypatch.setenv(variable, "https://api.test?x=1")

    with pytest.raises(ConfigurationError, match=f"^\\${variable} "):
        config.resolve_base_url(None)


def test_a_bad_url_names_the_option_the_caller_passed() -> None:
    with pytest.raises(ConfigurationError, match="^--api-url "):
        config.resolve_base_url("https://api.test#frag", source="--api-url")
