import pytest

from bookshelf.utils import build_url


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
