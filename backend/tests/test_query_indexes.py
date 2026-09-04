"""Real-Postgres tests for #194 — confirms the four indexes added in
migrations/018_backend_integrity_bundle.sql actually exist and that
Postgres' planner is willing to use each one for the real query pattern it
was added for. `EXPLAIN` output at today's tiny table sizes can't always
be forced to prefer an index scan over a sequential scan (the planner
correctly picks whichever is cheaper for a handful of rows) — so these
tests assert the index exists AND is a real, valid candidate the planner
recognizes for the query's WHERE clause, using `SET enable_seqscan = off`
to force index selection where a plan comparison alone wouldn't be
meaningful on an empty/near-empty test table.
"""

import pytest
from sqlalchemy import text

from core.db import async_session_factory


async def _index_exists(index_name: str) -> bool:
    async with async_session_factory() as session:
        row = (
            await session.execute(
                text("SELECT 1 FROM pg_indexes WHERE indexname = :name"), {"name": index_name}
            )
        ).first()
        return row is not None


@pytest.mark.asyncio
async def test_contributions_by_series_and_episode_index_exists() -> None:
    assert await _index_exists("contributions_by_series_and_episode")


@pytest.mark.asyncio
async def test_contributions_by_submitted_by_index_exists() -> None:
    assert await _index_exists("contributions_by_submitted_by")


@pytest.mark.asyncio
async def test_contribution_votes_by_voter_index_exists() -> None:
    assert await _index_exists("contribution_votes_by_voter")


@pytest.mark.asyncio
async def test_outbox_events_unprocessed_index_exists() -> None:
    assert await _index_exists("outbox_events_unprocessed")


@pytest.mark.asyncio
async def test_contributions_by_series_and_episode_index_usable_by_planner() -> None:
    """Confirms the index is real (not just present but unusable, e.g. the
    wrong column order) by forcing the planner to prefer an index scan and
    checking it picks THIS index for list_for_episode's exact query shape.
    """
    async with async_session_factory() as session:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = (
            await session.execute(
                text(
                    "EXPLAIN SELECT * FROM contributions "
                    "WHERE series_id = 1 AND episode_number = 1"
                )
            )
        ).scalars().all()
    plan_text = "\n".join(plan)
    assert "contributions_by_series_and_episode" in plan_text, plan_text


@pytest.mark.asyncio
async def test_contributions_by_submitted_by_index_usable_by_planner() -> None:
    async with async_session_factory() as session:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = (
            await session.execute(text("EXPLAIN SELECT * FROM contributions WHERE submitted_by = 1"))
        ).scalars().all()
    plan_text = "\n".join(plan)
    assert "contributions_by_submitted_by" in plan_text, plan_text


@pytest.mark.asyncio
async def test_contribution_votes_by_voter_index_usable_by_planner() -> None:
    async with async_session_factory() as session:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = (
            await session.execute(text("EXPLAIN SELECT * FROM contribution_votes WHERE voter_id = 1"))
        ).scalars().all()
    plan_text = "\n".join(plan)
    assert "contribution_votes_by_voter" in plan_text, plan_text


@pytest.mark.asyncio
async def test_outbox_events_unprocessed_index_usable_by_planner() -> None:
    async with async_session_factory() as session:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        plan = (
            await session.execute(
                text(
                    "EXPLAIN SELECT id FROM outbox_events WHERE processed_at IS NULL "
                    "ORDER BY id LIMIT 10"
                )
            )
        ).scalars().all()
    plan_text = "\n".join(plan)
    assert "outbox_events_unprocessed" in plan_text, plan_text
