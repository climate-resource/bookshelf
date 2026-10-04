"""Public tracking ID generation."""

from uuid import RFC_4122, UUID


def test_uuid7_is_public_from_the_publisher() -> None:
    from bookshelf.publisher import uuid7

    first, second = uuid7(), uuid7()
    assert isinstance(first, UUID)
    assert first.version == 7
    assert first.variant == RFC_4122
    assert first != second
