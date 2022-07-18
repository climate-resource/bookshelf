import pytest

from bookshelf.constants import DEFAULT_BOOKSHELF
from bookshelf.utils import build_url, get_remote_bookshelf


@pytest.mark.parametrize(
    "root,paths,exp",
    (
        ("https://test.com", ["example"], "https://test.com/example"),
        ("https://test.com", ["example", "part2"], "https://test.com/example/part2"),
        ("https://test.com/sub", ["example"], "https://test.com/sub/example"),
        (
            "https://test:user@test.com",
            ["example"],
            "https://test:user@test.com/example",
        ),
    ),
)
def test_build_url(root, paths, exp):
    res = build_url(root, *paths)

    assert res == exp


def test_remote_bookshelf(monkeypatch):
    env_var = "BOOKSHELF_REMOTE"
    monkeypatch.delenv(env_var)
    assert get_remote_bookshelf(None) == DEFAULT_BOOKSHELF

    monkeypatch.setenv(env_var, "https://test.local")
    assert get_remote_bookshelf(None) == "https://test.local"

    assert get_remote_bookshelf("test") == "test"
