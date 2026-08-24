"""Put already-serialised bytes into managed storage, returning the key they landed at.

The registration surface and the bundle replay both upload before they describe,
so the two-call upload dance lives here rather than in either of them.
"""

from bookshelf._core.client import BookshelfClient
from bookshelf._core.errors import BookshelfError
from bookshelf._generated import models


def _initiate(hash_: str, data: bytes, content_type: str) -> models.IngestUploadInitiateRequest:
    return models.IngestUploadInitiateRequest(
        hash=hash_,
        size_bytes=len(data),
        content_type=content_type,
    )


def _part_complete(part: models.UploadPartInfo, etag: str | None) -> models.UploadPartComplete:
    if not etag:
        raise BookshelfError(f"presigned PUT for part {part.part_number} returned no ETag")
    return models.UploadPartComplete(part_number=part.part_number, etag=etag.strip('"'))


def upload_bytes(
    client: BookshelfClient,
    data: bytes,
    *,
    hash_: str,
    content_type: str,
) -> str:
    """Upload ``data`` and return its managed storage path.

    A deployment that already holds the content answers the initiate call with the key,
    so nothing is transferred for it.
    """
    plan = client.initiate_ingest_upload(_initiate(hash_, data, content_type))
    if isinstance(plan, models.UploadAlreadyExistsResponse):
        return plan.storage_path
    multipart = plan.upload_id != "single"
    completed: list[models.UploadPartComplete] = []
    for part in plan.parts:
        etag = client.put_presigned(
            part.presigned_url,
            data[part.start_byte : part.end_byte],
            content_type=content_type,
        )
        if multipart:
            completed.append(_part_complete(part, etag))
    if multipart:
        client.complete_ingest_upload(
            models.IngestUploadCompleteRequest(
                upload_id=plan.upload_id,
                storage_path=plan.storage_path,
                parts=completed,
            )
        )
    return plan.storage_path


async def upload_bytes_async(
    client: BookshelfClient,
    data: bytes,
    *,
    hash_: str,
    content_type: str,
) -> str:
    """Asynchronous counterpart to :func:`upload_bytes`."""
    plan = await client.initiate_ingest_upload_async(_initiate(hash_, data, content_type))
    if isinstance(plan, models.UploadAlreadyExistsResponse):
        return plan.storage_path
    multipart = plan.upload_id != "single"
    completed: list[models.UploadPartComplete] = []
    for part in plan.parts:
        etag = await client.put_presigned_async(
            part.presigned_url,
            data[part.start_byte : part.end_byte],
            content_type=content_type,
        )
        if multipart:
            completed.append(_part_complete(part, etag))
    if multipart:
        await client.complete_ingest_upload_async(
            models.IngestUploadCompleteRequest(
                upload_id=plan.upload_id,
                storage_path=plan.storage_path,
                parts=completed,
            )
        )
    return plan.storage_path


__all__ = ["upload_bytes", "upload_bytes_async"]
