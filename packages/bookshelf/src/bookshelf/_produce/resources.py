"""Resource handles enriched with producer registration outcomes."""

from __future__ import annotations

from uuid import UUID

from bookshelf._consume.resources import AsyncResource as ConsumedAsyncResource
from bookshelf._consume.resources import Resource as ConsumedResource
from bookshelf._core.client import BookshelfClient
from bookshelf._generated import models
from bookshelf.cache import ContentCache


class Resource(ConsumedResource):
    """Synchronous resource handle retaining its registration outcome."""

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        tracking_id: str | UUID,
        *,
        metadata: models.ResourceRead | None = None,
        resource_type: models.ResourceType | None = None,
        registration_outcome: models.RegistrationOutcome | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(
            client,
            cache,
            tracking_id,
            metadata=metadata,
            resource_type=resource_type,
        )
        self.registration_outcome = registration_outcome
        self.name = name
        """The name this handle registered under, which is what ``book.add`` attaches it as."""

    @property
    def registration_status(self) -> models.Status2 | None:
        """Return how this handle's producer registration was resolved."""
        if self.registration_outcome is None:
            return None
        return self.registration_outcome.status


class AsyncResource(ConsumedAsyncResource):
    """Asynchronous resource handle retaining its registration outcome."""

    def __init__(
        self,
        client: BookshelfClient,
        cache: ContentCache,
        tracking_id: str | UUID,
        *,
        metadata: models.ResourceRead | None = None,
        resource_type: models.ResourceType | None = None,
        registration_outcome: models.RegistrationOutcome | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(
            client,
            cache,
            tracking_id,
            metadata=metadata,
            resource_type=resource_type,
        )
        self.registration_outcome = registration_outcome
        self.name = name
        """The name this handle registered under, which is what ``book.add`` attaches it as."""

    @property
    def registration_status(self) -> models.Status2 | None:
        """Return how this handle's producer registration was resolved."""
        if self.registration_outcome is None:
            return None
        return self.registration_outcome.status


__all__ = ["AsyncResource", "Resource"]
