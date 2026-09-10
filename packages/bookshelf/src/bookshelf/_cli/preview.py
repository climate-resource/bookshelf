"""``bookshelf preview``: store a pull request's candidate books for review.

The feedstock CI workflow runs ``upload`` once per pull request build.
The platform owns the check run and the pull request comment,
so the command prints the ids and links and nothing else.
"""

from pathlib import Path
from typing import Any

import pydantic
import typer

from bookshelf._cli._runtime import (
    EXIT_AUTH_REQUIRED,
    EXIT_INVALID_BUNDLE,
    EXIT_USAGE,
    CliError,
    command_errors,
    emit,
    emit_json,
    field,
    note,
)
from bookshelf._core.actions_oidc import ActionsTokenError, fetch_actions_token
from bookshelf._core.auth import StaticToken
from bookshelf._core.client import BookshelfClient
from bookshelf._core.config import resolve_base_url
from bookshelf._generated import models
from bookshelf.publisher.bundle import InvalidBundleError
from bookshelf.publisher.preview import PreviewIdentity, upload_preview

AUDIENCE = "bookshelf"

preview_app = typer.Typer(help="Store pull request previews.", no_args_is_help=True)


def _summary(preview: models.PreviewDetail) -> dict[str, Any]:
    return {
        "preview_id": str(preview.id),
        "proposal_url": preview.proposal_url,
        "preview_url": preview.preview_url,
        "state": preview.state.value,
        "books": [target.model_dump(mode="json") for target in preview.targets],
    }


def _emit(summary: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        emit_json(summary)
        return
    rows = [
        field("Preview", summary["preview_id"]),
        field("State", summary["state"]),
        field("Proposal", summary["proposal_url"]),
        field("Preview URL", summary["preview_url"]),
    ]
    for book in summary["books"]:
        baseline = book["baseline"]
        against = baseline if isinstance(baseline, str) else f"edition {baseline['edition']}"
        uploaded = "uploaded" if book["uploaded"] else "not uploaded"
        rows.append(field("Book", f"{book['volume']} {book['version']}, {uploaded}, {against}"))
    emit("\n".join(rows))


@preview_app.command("upload")
def upload(
    bundles: list[Path] = typer.Argument(..., help="Bundle directories, one per candidate book."),
    repository: str = typer.Option(..., "--repository", help="Feedstock repository as OWNER/NAME."),
    pr: int = typer.Option(..., "--pr", help="Pull request number."),
    pr_url: str = typer.Option(..., "--pr-url", help="Pull request web URL."),
    head_sha: str = typer.Option(..., "--head-sha", help="Pull request head commit."),
    main_sha: str = typer.Option(
        ..., "--main-sha", help="Base commit the candidate built against."
    ),
    tree: str = typer.Option(..., "--tree", help="Tree hash of the candidate build."),
    run_id: str = typer.Option(..., "--run-id", help="GitHub Actions run producing the upload."),
    api_url: str | None = typer.Option(None, "--api-url", help="Deployment to upload to."),
    json_output: bool = typer.Option(False, "--json", help="Emit the summary as JSON."),
) -> None:
    """Create a preview for a pull request, upload every candidate book and seal it.

    Authenticates with the job's GitHub Actions OIDC token,
    so the workflow needs the 'id-token: write' permission and holds no Bookshelf credential.
    """
    with command_errors():
        try:
            models.PreviewCandidate(head_sha=head_sha, main_sha=main_sha, candidate_tree=tree)
        except pydantic.ValidationError as exc:
            raise CliError(
                "--head-sha, --main-sha and --tree must each be a 7 to 64 character hex SHA",
                exit_code=EXIT_USAGE,
            ) from exc
        identity = PreviewIdentity(
            repository=repository,
            pr_number=pr,
            pr_url=pr_url,
            head_sha=head_sha,
            main_sha=main_sha,
            candidate_tree=tree,
            run_id=run_id,
        )
        try:
            token = fetch_actions_token(AUDIENCE)
        except ActionsTokenError as exc:
            raise CliError(str(exc), exit_code=EXIT_AUTH_REQUIRED) from exc

        # The OIDC token is the only credential, so the ambient chain is never consulted.
        with BookshelfClient(resolve_base_url(api_url), auth=StaticToken(token)) as client:
            try:
                outcome = upload_preview(bundles, client, identity)
            except InvalidBundleError as exc:
                raise CliError(str(exc), exit_code=EXIT_INVALID_BUNDLE) from exc

        _emit(_summary(outcome.preview), json_output=json_output)
        if outcome.refused:
            for path, problem in outcome.refused.items():
                note(f"Refused {path}: {problem}")
            raise typer.Exit(code=EXIT_INVALID_BUNDLE)
