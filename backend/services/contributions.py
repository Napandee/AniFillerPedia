from fastapi import HTTPException
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.citations as citations_repo
import repositories.contributions as contributions_repo
import repositories.outbox as outbox_repo
from schemas.contributions import CitationOut, ContributionCreate, ContributionOut

# NOTE ON TRANSACTIONS: this module assumes the caller (the router) has
# already opened `async with session.begin():` — matching the convention
# established (and bug-fixed) in #8's auth router, not wrapping its own
# transaction here. See routers/contributions.py.


async def submit_contribution(
    session: AsyncSession, payload: ContributionCreate, current_user: Row | None
) -> ContributionOut:
    if not payload.license_accepted:
        raise HTTPException(status_code=422, detail="license_accepted must be true")

    existing_pending = await contributions_repo.find_pending_for_episode(
        session, payload.series_id, payload.episode_number
    )
    if existing_pending is not None:
        # #20: at most one pending contribution per episode — point the
        # caller at the existing one instead of a dead-end rejection.
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "A contribution for this episode is already pending review — "
                    "endorse or dispute it instead of submitting a competing one."
                ),
                "existing_contribution_id": existing_pending.id,
            },
        )

    citation_row = await citations_repo.create(
        session,
        url=payload.citation.url,
        description=payload.citation.description,
        submitted_by=current_user.id if current_user else None,
    )

    contribution_row = await contributions_repo.create(
        session,
        series_id=payload.series_id,
        episode_number=payload.episode_number,
        proposed_status=payload.proposed_status,
        proposed_note=payload.proposed_note,
        citation_id=citation_row.id,
        submitted_by=current_user.id if current_user else None,
        license_accepted=payload.license_accepted,
    )

    # Same transaction as the insert above (CLAUDE.md Architecture) — #9's
    # worker will pick this up once #15 registers a handler for it; until
    # then it's correctly left unprocessed, not silently dropped.
    await outbox_repo.write(
        session,
        event_type="contribution.submitted",
        payload={
            "contribution_id": contribution_row.id,
            "series_id": payload.series_id,
            "episode_number": payload.episode_number,
        },
    )

    return ContributionOut(
        id=contribution_row.id,
        series_id=contribution_row.series_id,
        episode_number=contribution_row.episode_number,
        proposed_status=contribution_row.proposed_status,
        proposed_note=contribution_row.proposed_note,
        citation=CitationOut(
            id=citation_row.id, url=citation_row.url, description=citation_row.description
        ),
        submitted_at=contribution_row.submitted_at,
        review_status=contribution_row.review_status,
        resolution_method=contribution_row.resolution_method,
        reviewed_at=contribution_row.reviewed_at,
        review_note=contribution_row.review_note,
    )


async def list_my_contributions(session: AsyncSession, user_id: int) -> list[ContributionOut]:
    rows = await contributions_repo.list_mine(session, user_id)
    return [
        ContributionOut(
            id=row.id,
            series_id=row.series_id,
            episode_number=row.episode_number,
            proposed_status=row.proposed_status,
            proposed_note=row.proposed_note,
            citation=CitationOut(
                id=row.citation_id, url=row.citation_url, description=row.citation_description
            ),
            submitted_at=row.submitted_at,
            review_status=row.review_status,
            resolution_method=row.resolution_method,
            reviewed_at=row.reviewed_at,
            review_note=row.review_note,
        )
        for row in rows
    ]
