from fastapi import HTTPException
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession

import repositories.contributions as contributions_repo
import repositories.episodes as episodes_repo
import repositories.series as series_repo
from schemas.contributions import ContributionHistoryEntry, UserRef, VoteOut
from schemas.episodes import CitationOut, EpisodeOut


def _row_to_episode_out(row: Row) -> EpisodeOut:
    return EpisodeOut(
        id=row.id,
        series_id=row.series_id,
        episode_number=row.episode_number,
        status=row.status,
        status_note=row.status_note,
        title=row.title,
        citation=CitationOut(
            id=row.citation_id,
            url=row.citation_url,
            description=row.citation_description,
            source_count=row.citation_source_count,
            methodology_note=row.citation_methodology_note,
        ),
        updated_at=row.updated_at,
        aired_at=row.aired_at,
        has_pending_contribution=row.has_pending_contribution,
    )


async def list_episodes_for_series(session: AsyncSession, series_id: int) -> list[EpisodeOut]:
    series_row = await series_repo.get_series_by_id(session, series_id)
    if series_row is None:
        raise HTTPException(status_code=404, detail="Series not found")
    rows = await episodes_repo.list_for_series(session, series_id)
    return [_row_to_episode_out(row) for row in rows]


async def get_episode(session: AsyncSession, episode_id: int) -> EpisodeOut:
    row = await episodes_repo.get_by_id(session, episode_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Episode not found")
    return _row_to_episode_out(row)


def _user_ref(id_: int | None, display_name: str | None, github_id: str | None) -> UserRef | None:
    if id_ is None:
        return None
    return UserRef(id=id_, display_name=display_name, github_id=github_id)


async def get_episode_history(
    session: AsyncSession, episode_id: int
) -> list[ContributionHistoryEntry]:
    loc = await contributions_repo.get_episode_series_and_number(session, episode_id)
    if loc is None:
        raise HTTPException(status_code=404, detail="Episode not found")

    contribution_rows = await contributions_repo.list_for_episode(
        session, loc.series_id, loc.episode_number
    )
    contribution_ids = [row.id for row in contribution_rows]
    vote_rows = await contributions_repo.list_votes_for_contributions(session, contribution_ids)

    votes_by_contribution: dict[int, list[VoteOut]] = {}
    for v in vote_rows:
        votes_by_contribution.setdefault(v.contribution_id, []).append(
            VoteOut(
                voter=_user_ref(v.voter_id, v.voter_display_name, v.voter_github_id),
                vote=v.vote,
                weight_at_vote=v.weight_at_vote,
                created_at=v.created_at,
            )
        )

    return [
        ContributionHistoryEntry(
            id=row.id,
            proposed_status=row.proposed_status,
            proposed_note=row.proposed_note,
            citation=CitationOut(
                id=row.citation_id, url=row.citation_url, description=row.citation_description
            ),
            submitted_by=_user_ref(row.submitter_id, row.submitter_display_name, row.submitter_github_id),
            submitted_at=row.submitted_at,
            review_status=row.review_status,
            resolution_method=row.resolution_method,
            reviewed_by=_user_ref(row.reviewer_id, row.reviewer_display_name, row.reviewer_github_id),
            reviewed_at=row.reviewed_at,
            review_note=row.review_note,
            votes=votes_by_contribution.get(row.id, []),
        )
        for row in contribution_rows
    ]
