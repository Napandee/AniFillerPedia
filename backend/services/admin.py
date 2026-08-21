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
from schemas.admin import AdminUserListOut, AdminUserOut

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


async def update_role(session, *, target_user_id: int, new_role: str, changed_by_user_id: int) -> dict:
    if new_role not in admin_repo.VALID_ROLES:
        raise fastapi.HTTPException(status_code=422, detail=f"role must be one of {admin_repo.VALID_ROLES}")

    old_role = await admin_repo.get_user_role(session, target_user_id)
    if old_role is None:
        raise fastapi.HTTPException(status_code=404, detail="user not found")

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
