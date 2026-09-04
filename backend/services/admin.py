"""Admin-tier business logic: user listing with computed trust_score,
role promotion/demotion with an audit-trail write.

trust_score formula (CLAUDE.md Decisions Made): approved_count +
likes_received * small_weight - rejected_count * penalty. **v1
simplification, noted honestly rather than silently done**: no `likes`
mechanism exists anywhere in schema.sql yet (checked — contribution_votes
is endorse/dispute on *pending* contributions, not likes on approved
ones), so the likes term is 0 for now. Formula reduces to
approved_count - rejected_count * REJECTION_PENALTY until a real likes
data source exists to build the other term against.

`compute_trust_score` is public (not module-private) because #14's
community trust-weighted voting reuses this exact formula to derive each
voter's `weight_at_vote` — one formula, two call sites (this module's user
listing, services/contributions.py's vote-casting), never two
implementations that could drift apart.
"""

import fastapi

from repositories import admin as admin_repo
from repositories import outbox as outbox_repo
from repositories import traffic_analytics as traffic_repo
from schemas.admin import (
    AdminUserListOut,
    AdminUserOut,
    SuspensionUpdateOut,
    TrafficCountryEntryOut,
    TrafficPathEntryOut,
    TrafficRollupListOut,
    TrafficRollupOut,
    TrafficStatusEntryOut,
    VoteClusteringPairOut,
    VoteClusteringReportOut,
)

REJECTION_PENALTY = 2


def compute_trust_score(approved_count: int, rejected_count: int) -> int:
    return approved_count - rejected_count * REJECTION_PENALTY


async def list_users(session, limit: int, offset: int) -> AdminUserListOut:
    rows, total = await admin_repo.list_users_with_stats(session, limit, offset)
    items = [
        AdminUserOut(
            id=row.id,
            role=row.role,
            github_id=row.github_id,
            discord_id=row.discord_id,
            google_id=row.google_id,
            display_name=row.display_name,
            approved_count=row.approved_count,
            rejected_count=row.rejected_count,
            trust_score=compute_trust_score(row.approved_count, row.rejected_count),
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
    return AdminUserListOut(items=items, total=total, limit=limit, offset=offset)


async def update_role(
    session, *, target_user_id: int, new_role: str, changed_by_user_id: int, changed_by_role: str
) -> dict:
    if new_role not in admin_repo.VALID_ROLES:
        raise fastapi.HTTPException(status_code=422, detail=f"role must be one of {admin_repo.VALID_ROLES}")

    old_role = await admin_repo.get_user_role(session, target_user_id)
    if old_role is None:
        raise fastapi.HTTPException(status_code=404, detail="user not found")

    # Owner tier (decided 2026-08-21, CLAUDE.md): the owner's own row can
    # never be changed through this endpoint, by anyone — 'owner' isn't in
    # VALID_ROLES so a demotion is the only thing this check needs to catch
    # (an attempt to set someone's role TO 'owner' already 422s above).
    if old_role == "owner":
        raise fastapi.HTTPException(status_code=403, detail="the owner's role cannot be changed")

    # Only the owner can mint new admins — a plain admin can still promote/
    # demote between contributor and moderator (require_admin already
    # gates this whole endpoint), but granting 'admin' itself is reserved
    # so admins can't create peers or bypass the owner.
    if new_role == "admin" and changed_by_role != "owner":
        raise fastapi.HTTPException(status_code=403, detail="only the owner can grant the admin role")

    # NOT `async with session.begin():` here — deliberately, same fix as
    # #12's routers/contributions.py: the require_admin dependency this
    # endpoint uses already ran get_current_user's SELECT, which
    # autobegins a transaction on this session, so session.begin() would
    # raise "a transaction is already begun." The router commits
    # explicitly after this returns.
    updated = await admin_repo.update_user_role(session, target_user_id, new_role)
    # Audit-trail write, per CLAUDE.md's non-negotiable guardrail — a role
    # change is exactly the kind of thing "who did what, when" needs to
    # cover, same pattern as #13's contribution.approved events, in the
    # same (already-open) transaction as the actual change.
    await outbox_repo.write(
        session,
        event_type="user.role_changed",
        payload={
            "user_id": target_user_id,
            "old_role": old_role,
            "new_role": new_role,
            "changed_by": changed_by_user_id,
        },
    )
    return {"id": updated.id, "role": updated.role}


async def update_suspension(
    session, *, target_user_id: int, suspended: bool, reason: str | None
) -> SuspensionUpdateOut:
    """#209: admin/owner-only account suspension. Mirrors update_role's
    owner-immunity check (the owner's own row can never be touched through
    an admin-tier endpoint by anyone) — there is no "only the owner can
    suspend an admin" restriction the way role-granting has one, since
    suspension doesn't create a new privileged account the way granting
    'admin' does.
    """
    role = await admin_repo.get_user_role(session, target_user_id)
    if role is None:
        raise fastapi.HTTPException(status_code=404, detail="user not found")
    if role == "owner":
        raise fastapi.HTTPException(status_code=403, detail="the owner's account cannot be suspended")

    updated = await admin_repo.set_user_suspension(
        session, target_user_id, suspended=suspended, reason=reason if suspended else None
    )

    # Audit-trail write, same convention as role changes above.
    await outbox_repo.write(
        session,
        event_type="user.suspended" if suspended else "user.unsuspended",
        payload={"user_id": target_user_id, "reason": reason} if suspended else {"user_id": target_user_id},
    )

    return SuspensionUpdateOut(
        id=updated.id,
        suspended=updated.suspended_at is not None,
        suspended_at=updated.suspended_at.isoformat() if updated.suspended_at else None,
        suspended_reason=updated.suspended_reason,
    )


async def get_vote_clustering_report(
    session, min_reciprocal_count: int, limit: int
) -> VoteClusteringReportOut:
    """#203: see repositories/admin.py's find_reciprocal_endorsement_pairs
    for the query and full rationale.
    """
    rows = await admin_repo.find_reciprocal_endorsement_pairs(session, min_reciprocal_count, limit)
    items = [
        VoteClusteringPairOut(
            user_a_id=row.user_a_id,
            user_a_display_name=row.user_a_display_name,
            user_b_id=row.user_b_id,
            user_b_display_name=row.user_b_display_name,
            a_endorsed_b_count=row.a_endorsed_b_count,
            b_endorsed_a_count=row.b_endorsed_a_count,
            combined_endorsement_count=row.combined_endorsement_count,
            last_activity_at=row.last_activity_at.isoformat(),
        )
        for row in rows
    ]
    return VoteClusteringReportOut(items=items, min_reciprocal_count=min_reciprocal_count)


async def list_traffic_rollups(session, limit: int) -> TrafficRollupListOut:
    """#221: the admin traffic dashboard's only real query — most recent
    `limit` days of Cloudflare-sourced rollups, newest first. An empty
    `items` list is a legitimate, expected v1 state (no token configured
    yet, or the daily loop hasn't run yet) — the frontend page renders its
    own explicit "no data yet" message for that case rather than treating
    it as an error.
    """
    rows = await traffic_repo.list_daily_rollups(session, limit)
    items = [
        TrafficRollupOut(
            rollup_date=row.rollup_date.isoformat(),
            total_requests=row.total_requests,
            top_paths=[TrafficPathEntryOut(**entry) for entry in row.top_paths],
            status_breakdown=[TrafficStatusEntryOut(**entry) for entry in row.status_breakdown],
            top_countries=[TrafficCountryEntryOut(**entry) for entry in row.top_countries],
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
    return TrafficRollupListOut(items=items)
