"""Mutable draft-book handles for producer workflows."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Self
from uuid import UUID

from bookshelf._core.client import BookshelfClient
from bookshelf._generated import models
from bookshelf._produce.types import AuthorInput, HasTrackingId, UsedInput
from bookshelf._produce.visibility import INHERIT, VisibilityInput

if TYPE_CHECKING:
    from bookshelf._produce.activities import Activity, AsyncActivity


DEFAULT_WRITE_TYPE = "tabular"
"""The resource type :meth:`DraftBook.write` records when the caller states none.

``tabular`` is the generic table, so a frame is never catalogued as something it might not be.
A producer that wants the platform's timeseries treatment states ``type="timeseries"``.
"""


def _written_name(resource: object) -> str:
    """Return the name a handle was registered under, refusing one that never took a name."""
    name: object = getattr(resource, "name", None)
    if not isinstance(name, str) or not name:
        raise ValueError(
            "book.add needs a resource registered under a name, and this handle has none. "
            "Register it with name= or attach it with book.attach(resource, name_in_book=...)."
        )
    return name


def _attach_request(
    resource: HasTrackingId | str | UUID,
    *,
    name_in_book: str,
    data_dictionary: Sequence[models.DataDictionaryEntry] | None,
) -> models.BookEntryAttach:
    """Build an attachment while preserving an omitted dictionary field."""
    tracking_id = (
        UUID(str(resource)) if isinstance(resource, str | UUID) else UUID(str(resource.tracking_id))
    )
    if data_dictionary is None:
        return models.BookEntryAttach(tracking_id=tracking_id, name_in_book=name_in_book)
    return models.BookEntryAttach(
        tracking_id=tracking_id,
        name_in_book=name_in_book,
        data_dictionary=list(data_dictionary),
    )


class DraftBook:
    """Mutable synchronous draft-book handle."""

    def __init__(
        self,
        client: BookshelfClient,
        detail: models.BookDetail,
        *,
        activity: Callable[[], Activity] | None = None,
    ) -> None:
        self._client = client
        self.metadata = detail
        # The activity book.write registers through.
        # A book drafted without one can still attach resources the caller registered itself, so this stays optional.
        self._activity = activity

    def _writing_activity(self) -> Activity:
        if self._activity is None:
            raise RuntimeError(
                "book.write needs the activity its sink opens, and this book was drafted without one. "
                "Register through bs.activity(...) and attach with book.add."
            )
        return self._activity()

    def write(
        self,
        name: str,
        obj: object,
        *,
        type: str | models.ResourceType = DEFAULT_WRITE_TYPE,
        used: Sequence[UsedInput] = (),
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        description: str | None = None,
        authors: Sequence[AuthorInput] | None = None,
        doi: str | None = None,
        citation: str | None = None,
        license: str | None = None,
        license_url: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        format: str | None = None,
        dedupe: bool = True,
    ) -> Any:  # noqa: ANN401
        """Register one output and attach it under ``name`` in a single call.

        This is sugar over the layered form,
        and it produces the same bundle as registering inside ``bs.activity(...)``
        and then calling :meth:`add`.
        The resource name and the book entry name are one name,
        because that is what replay addresses the resource by.

        The catalogue fields describe this resource rather than the book holding it,
        so a derived output credits whoever produced it and nothing is inherited.
        """
        resource = self._writing_activity().register(
            obj,
            type=type,
            name=name,
            used=used,
            visibility=visibility,
            tags=tags,
            description=description,
            authors=authors,
            doi=doi,
            citation=citation,
            license=license,
            license_url=license_url,
            metadata=metadata,
            format=format,
            dedupe=dedupe,
        )
        self.attach(resource, name_in_book=name, data_dictionary=data_dictionary)
        return resource

    def add(self, *resources: HasTrackingId) -> Self:
        """Attach already registered resources, each under the name it registered as."""
        for resource in resources:
            self.attach(resource, name_in_book=_written_name(resource))
        return self

    @property
    def book_id(self) -> UUID:
        return self.metadata.book_id

    @property
    def status(self) -> str:
        return self.metadata.status

    def attach(
        self,
        resource: HasTrackingId | str | UUID,
        *,
        name_in_book: str,
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
    ) -> models.BookEntryAttachResponse:
        """Attach a resource under a book-local name and optional entry dictionary.

        Omitting ``data_dictionary`` preserves the dictionary on an existing entry.
        Pass an empty sequence to clear it.
        """
        request = _attach_request(
            resource,
            name_in_book=name_in_book,
            data_dictionary=data_dictionary,
        )
        return self._client.attach_entry(str(self.book_id), request)

    def publish(self) -> Self:
        """Publish the assembled draft and update this handle in place."""
        self.metadata = self._client.publish_book(str(self.book_id))
        return self


class AsyncDraftBook:
    """Mutable asynchronous draft-book handle."""

    def __init__(
        self,
        client: BookshelfClient,
        detail: models.BookDetail,
        *,
        activity: Callable[[], AsyncActivity] | None = None,
    ) -> None:
        self._client = client
        self.metadata = detail
        self._activity = activity

    def _writing_activity(self) -> AsyncActivity:
        if self._activity is None:
            raise RuntimeError(
                "book.write needs the activity its sink opens, and this book was drafted without one. "
                "Register through bs.activity(...) and attach with book.add."
            )
        return self._activity()

    async def write(
        self,
        name: str,
        obj: object,
        *,
        type: str | models.ResourceType = DEFAULT_WRITE_TYPE,
        used: Sequence[UsedInput] = (),
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
        visibility: VisibilityInput = INHERIT,
        tags: Sequence[str] = (),
        description: str | None = None,
        authors: Sequence[AuthorInput] | None = None,
        doi: str | None = None,
        citation: str | None = None,
        license: str | None = None,
        license_url: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        format: str | None = None,
        dedupe: bool = True,
    ) -> Any:  # noqa: ANN401
        """Register one output and attach it under ``name`` in a single call.

        The asynchronous twin of :meth:`DraftBook.write`, with the same bundle result.
        """
        resource = await self._writing_activity().register(
            obj,
            type=type,
            name=name,
            used=used,
            visibility=visibility,
            tags=tags,
            description=description,
            authors=authors,
            doi=doi,
            citation=citation,
            license=license,
            license_url=license_url,
            metadata=metadata,
            format=format,
            dedupe=dedupe,
        )
        await self.attach(resource, name_in_book=name, data_dictionary=data_dictionary)
        return resource

    async def add(self, *resources: HasTrackingId) -> Self:
        """Attach already registered resources, each under the name it registered as."""
        for resource in resources:
            await self.attach(resource, name_in_book=_written_name(resource))
        return self

    @property
    def book_id(self) -> UUID:
        return self.metadata.book_id

    @property
    def status(self) -> str:
        return self.metadata.status

    async def attach(
        self,
        resource: HasTrackingId | str | UUID,
        *,
        name_in_book: str,
        data_dictionary: Sequence[models.DataDictionaryEntry] | None = None,
    ) -> models.BookEntryAttachResponse:
        """Attach a resource under a book-local name and optional entry dictionary.

        Omitting ``data_dictionary`` preserves the dictionary on an existing entry.
        Pass an empty sequence to clear it.
        """
        request = _attach_request(
            resource,
            name_in_book=name_in_book,
            data_dictionary=data_dictionary,
        )
        return await self._client.attach_entry_async(str(self.book_id), request)

    async def publish(self) -> Self:
        """Publish the assembled draft and update this handle in place."""
        self.metadata = await self._client.publish_book_async(str(self.book_id))
        return self


__all__ = ["DEFAULT_WRITE_TYPE", "AsyncDraftBook", "DraftBook"]
