"""Pin the promised Python API, so an accidental change to it fails CI.

The golden file lists every promised name and signature.
A deliberate change regenerates it with ``UPDATE_SURFACE_GOLDEN=1``,
and the diff then shows up in review beside a changelog entry.
"""

import enum
import inspect
import json
import os
import re
from pathlib import Path
from typing import Any

import bookshelf
import bookshelf.auth
import bookshelf.legacy

GOLDEN = Path(__file__).parent / "golden" / "public_surface.json"
UPDATE = os.environ.get("UPDATE_SURFACE_GOLDEN") == "1"

PROVISIONAL = frozenset(
    {
        "Activity",
        "AsyncActivity",
        "AsyncDraftBook",
        "DraftBook",
        "RegisterItem",
        "RegistrationFailure",
        "RegistrationSuccess",
        "Used",
        "setup",
    }
)

CLIENT_METHODS = (
    "__init__",
    "close",
    "aclose",
    "__enter__",
    "__exit__",
    "__aenter__",
    "__aexit__",
    "ensure_authenticated",
    "search_volumes",
    "volume",
    "book",
    "resource",
    "resource_by_hash",
    "correct_book",
)
CACHE_MEMBERS = ("__init__", "get", "summary", "evict_lru", "clear")
# The SDK builds these handles, so their constructors are not part of the promise.
HANDLES = frozenset(
    {
        "AsyncBook",
        "AsyncBookEntry",
        "AsyncResource",
        "AsyncVolume",
        "Book",
        "BookEntry",
        "Resource",
        "Volume",
    }
)
# Promised classes whose members hand back producer types or generated models, which are provisional.
PROVISIONAL_MEMBERS = {
    "PartialRegistrationError": frozenset({"__init__", "successful_outcomes"}),
}
DUNDERS = ("__getitem__", "__iter__", "__len__", "__contains__")


_RAW_ANNOTATIONS: list[str] = []


def _annotation(value: Any) -> str:
    text = value if isinstance(value, str) else inspect.formatannotation(value)
    _RAW_ANNOTATIONS.append(text)
    # Module paths differ between deferred and evaluated annotations, and say nothing about the API.
    return re.sub(r"\b(?:[A-Za-z_]\w*\.)+(?=[A-Za-z_]\w*)", "", text)


def _signature(function: Any) -> str:
    signature = inspect.signature(function)
    parameters = []
    for parameter in signature.parameters.values():
        text = parameter.name
        if parameter.kind is parameter.VAR_POSITIONAL:
            text = f"*{text}"
        elif parameter.kind is parameter.VAR_KEYWORD:
            text = f"**{text}"
        if parameter.annotation is not parameter.empty:
            text = f"{text}: {_annotation(parameter.annotation)}"
        if parameter.default is not parameter.empty:
            text = f"{text} = {parameter.default!r}"
        parameters.append((parameter.kind, text))
    rendered = []
    for index, (kind, text) in enumerate(parameters):
        previous = parameters[index - 1][0] if index else None
        if kind is inspect.Parameter.KEYWORD_ONLY and previous not in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            rendered.append("*")
        rendered.append(text)
    prefix = "async " if inspect.iscoroutinefunction(function) else ""
    returns = signature.return_annotation
    arrow = "" if returns is signature.empty else f" -> {_annotation(returns)}"
    return f"{prefix}({', '.join(rendered)}){arrow}"


def _member(cls: type, name: str) -> str | None:
    try:
        value = inspect.getattr_static(cls, name)
    except AttributeError:
        return None
    if isinstance(value, property):
        assert value.fget is not None
        returns = inspect.signature(value.fget).return_annotation
        return f"property -> {_annotation(returns)}"
    if isinstance(value, (staticmethod, classmethod)):
        value = value.__func__
    if callable(value):
        return _signature(value)
    return f"attribute {type(value).__name__}"


def _own_classes(cls: type) -> list[type]:
    return [klass for klass in cls.__mro__ if klass.__module__.startswith("bookshelf")]


def _public_names(cls: type) -> list[str]:
    """Name the members a caller reaches, leaving out constructors only the SDK calls."""
    names = {
        name
        for klass in _own_classes(cls)
        for name in vars(klass)
        if not name.startswith("_") or name in DUNDERS
    }
    if cls.__name__ not in HANDLES:
        names.add("__init__")
    return sorted(names - PROVISIONAL_MEMBERS.get(cls.__name__, frozenset()))


def _attributes(cls: type) -> dict[str, str]:
    """The instance attributes a class declares, which ``vars`` cannot see."""
    return {
        name: _annotation(annotation)
        for klass in reversed(_own_classes(cls))
        for name, annotation in inspect.get_annotations(klass).items()
        if not name.startswith("_")
    }


def _describe_class(name: str, cls: type) -> dict[str, Any]:
    if issubclass(cls, enum.Enum):
        return {"kind": "enum", "members": {member.name: member.value for member in cls}}
    if name in ("Bookshelf", "AsyncBookshelf"):
        members = CLIENT_METHODS
    elif name == "ContentCache":
        members = CACHE_MEMBERS
    else:
        members = tuple(_public_names(cls))
    described: dict[str, Any] = {
        "kind": "class",
        "members": {
            member: text for member in members if (text := _member(cls, member)) is not None
        },
        "attributes": _attributes(cls),
    }
    if issubclass(cls, BaseException):
        described["bases"] = [
            base.__name__ for base in cls.__mro__[1:] if base not in (BaseException, object)
        ]
    return described


def _describe(value: Any) -> Any:
    if inspect.isclass(value):
        return _describe_class(value.__name__, value)
    if callable(value):
        return {"kind": "function", "signature": _signature(value)}
    return {"kind": "value", "type": type(value).__name__}


def _module(module: Any, names: list[str]) -> dict[str, Any]:
    return {name: _describe(getattr(module, name)) for name in sorted(names)}


def surface() -> dict[str, Any]:
    promised = [name for name in bookshelf.__all__ if name not in PROVISIONAL]
    return {
        "bookshelf.__all__": sorted(bookshelf.__all__),
        "bookshelf": _module(bookshelf, promised),
        "bookshelf.auth": _module(bookshelf.auth, list(bookshelf.auth.__all__)),
        "bookshelf.legacy": _module(bookshelf.legacy, list(bookshelf.legacy.__all__)),
    }


def test_the_promised_surface_matches_the_golden() -> None:
    current = surface()
    if UPDATE:
        GOLDEN.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    expected = json.loads(GOLDEN.read_text())

    assert current == expected, (
        "The promised Python API changed. If that is deliberate, add a changelog entry "
        "and rerun with UPDATE_SURFACE_GOLDEN=1 to accept it."
    )


def test_every_provisional_name_is_still_exported() -> None:
    assert set(bookshelf.__all__) >= PROVISIONAL


def test_no_promised_signature_names_a_generated_model_or_sentinel() -> None:
    _RAW_ANNOTATIONS.clear()
    rendered = json.dumps(surface())

    assert not [text for text in _RAW_ANNOTATIONS if "models." in text or "_generated" in text]
    assert "_Unset" not in rendered
    assert "_Inherit" not in rendered


def test_the_snapshot_covers_constructors_error_members_and_attributes() -> None:
    """Guards the collector itself, so a future exclusion cannot quietly drop coverage."""
    captured = surface()
    root = captured["bookshelf"]

    assert "__init__" in captured["bookshelf.auth"]["ClientCredentials"]["members"]
    assert "item_errors" in root["ConflictError"]["members"]
    assert "status_code" in root["APIError"]["attributes"]
    assert root["Book"]["attributes"]["book_id"] == "UUID"
    assert root["BookEntry"]["attributes"]["name_in_book"] == "str"
    assert "__init__" not in root["Book"]["members"]
    assert root["PartialRegistrationError"]["members"] == {
        "failed_indices": "property -> tuple[int, ...]"
    }
