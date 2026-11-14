"""Announcement display policies, versioning and per-subject dismissal.

Covers the two production issues this work fixes:

* Issue 1 — a dismissed announcement never reappeared. Dismissals were
  browser-local only and permanent. Now they are tracked per subject
  (user or anonymous device) and per announcement *version*, and the
  display policy decides when an announcement becomes eligible again.

* Issue 2 — an updated announcement stayed hidden because updates mutate
  the same row (same id) while the dismissal key was the id alone. Now a
  content-affecting admin edit bumps ``Announcement.version``, which
  invalidates prior dismissals.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.auth import SESSION_COOKIE_NAME, create_access_token
from app.models.platform import AnnouncementState
from app.models.user import User
from app.services.announcements import (
    AnnouncementValidationError,
    device_subject,
    is_visible,
    user_subject,
    validate_display_policy,
)

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def _state(*, dismissed_at=None, last_seen_at=None):
    """A minimal AnnouncementState stand-in for the pure policy engine."""
    return AnnouncementState(
        subject_type="user",
        subject_id=str(uuid.uuid4()),
        announcement_id=uuid.uuid4(),
        announcement_version=1,
        dismissed_at=dismissed_at,
        last_seen_at=last_seen_at,
    )


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Keep the shared per-IP limiter from bleeding across tests.

    The admin announcement endpoints allow 30 writes/minute per IP; this
    suite creates many announcements, so the budget is reset per test to
    keep it independent of execution order.
    """
    from app.middleware.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()


# ---------------------------------------------------------------------------
# Pure policy engine
# ---------------------------------------------------------------------------


def test_once_until_dismissed_visible_until_dismissed():
    visible = is_visible(
        display_policy="once_until_dismissed",
        recur_interval_minutes=None,
        state=None,
        session_start=NOW,
        now=NOW,
    )
    assert visible is True

    dismissed = _state(dismissed_at=NOW)
    visible = is_visible(
        display_policy="once_until_dismissed",
        recur_interval_minutes=None,
        state=dismissed,
        session_start=NOW,
        now=NOW + timedelta(days=30),
    )
    assert visible is False


def test_every_login_hidden_after_dismissal_in_same_session():
    state = _state(dismissed_at=NOW)
    visible = is_visible(
        display_policy="every_login",
        recur_interval_minutes=None,
        state=state,
        session_start=NOW,
        now=NOW + timedelta(minutes=5),
    )
    assert visible is False


def test_every_login_reappears_on_next_login():
    """A new login advances the session start, so the announcement returns."""
    state = _state(dismissed_at=NOW)
    next_session = NOW + timedelta(hours=2)
    visible = is_visible(
        display_policy="every_login",
        recur_interval_minutes=None,
        state=state,
        session_start=next_session,
        now=next_session,
    )
    assert visible is True


def test_every_login_last_seen_prevents_repeat_within_session():
    """`last_seen_at` alone (dismissed_at NULL) hides it for the session."""
    state = _state(last_seen_at=NOW)
    visible = is_visible(
        display_policy="every_login",
        recur_interval_minutes=None,
        state=state,
        session_start=NOW,
        now=NOW + timedelta(minutes=1),
    )
    assert visible is False


def test_every_login_last_seen_expires_with_next_login():
    state = _state(last_seen_at=NOW)
    next_session = NOW + timedelta(hours=1)
    visible = is_visible(
        display_policy="every_login",
        recur_interval_minutes=None,
        state=state,
        session_start=next_session,
        now=next_session,
    )
    assert visible is True


def test_recurring_reappears_after_interval():
    state = _state(dismissed_at=NOW)
    hidden = is_visible(
        display_policy="recurring",
        recur_interval_minutes=60,
        state=state,
        session_start=NOW,
        now=NOW + timedelta(minutes=59),
    )
    assert hidden is False

    visible = is_visible(
        display_policy="recurring",
        recur_interval_minutes=60,
        state=state,
        session_start=NOW,
        now=NOW + timedelta(minutes=60),
    )
    assert visible is True


def test_recurring_visible_when_never_dismissed():
    visible = is_visible(
        display_policy="recurring",
        recur_interval_minutes=60,
        state=None,
        session_start=NOW,
        now=NOW,
    )
    assert visible is True


def test_unknown_policy_shows_rather_than_hides():
    visible = is_visible(
        display_policy="something_new",
        recur_interval_minutes=None,
        state=_state(dismissed_at=NOW),
        session_start=NOW,
        now=NOW,
    )
    assert visible is True


# ---------------------------------------------------------------------------
# Display-policy validation
# ---------------------------------------------------------------------------


def test_recurring_requires_interval():
    with pytest.raises(AnnouncementValidationError):
        validate_display_policy("recurring", None)


def test_recurring_rejects_zero_interval():
    with pytest.raises(AnnouncementValidationError):
        validate_display_policy("recurring", 0)


def test_non_recurring_rejects_interval():
    with pytest.raises(AnnouncementValidationError):
        validate_display_policy("once_until_dismissed", 30)


def test_unknown_policy_rejected():
    with pytest.raises(AnnouncementValidationError):
        validate_display_policy("nope", None)


def test_switching_to_recurring_keeps_previous_interval():
    policy, interval = validate_display_policy(
        "recurring",
        None,
        previous_policy="recurring",
        previous_interval=120,
    )
    assert policy == "recurring"
    assert interval == 120


# ---------------------------------------------------------------------------
# Admin API: versioning + policy fields
# ---------------------------------------------------------------------------


def _create(admin_client, **overrides):
    body = {"title": "Notice", "message": "body", "kind": "general"}
    body.update(overrides)
    created = admin_client.post("/api/v1/admin/announcements", json=body)
    assert created.status_code == 201, created.text
    return created.json()


def _publish(admin_client, aid):
    resp = admin_client.put(
        f"/api/v1/admin/announcements/{aid}", json={"state": "published"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_admin_create_accepts_display_policy(admin_client):
    created = _create(
        admin_client,
        display_policy="recurring",
        recur_interval_minutes=45,
    )
    assert created["display_policy"] == "recurring"
    assert created["recur_interval_minutes"] == 45
    assert created["version"] == 1


def test_admin_list_empty_returns_empty_list(admin_client):
    resp = admin_client.get("/api/v1/admin/announcements")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_admin_list_returns_display_contract(admin_client):
    created = _create(
        admin_client,
        display_policy="recurring",
        recur_interval_minutes=15,
    )

    resp = admin_client.get("/api/v1/admin/announcements")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert isinstance(rows, list)
    row = next(item for item in rows if item["id"] == created["id"])
    assert row["version"] == created["version"]
    assert row["display_policy"] == "recurring"
    assert row["recur_interval_minutes"] == 15
    assert row["audience"] == "all"


def test_admin_create_rejects_recurring_without_interval(admin_client):
    resp = admin_client.post(
        "/api/v1/admin/announcements",
        json={
            "title": "Notice",
            "message": "body",
            "display_policy": "recurring",
        },
    )
    assert resp.status_code == 400, resp.text


def test_admin_update_rejects_interval_without_recurring(admin_client):
    created = _create(admin_client)
    resp = admin_client.put(
        f"/api/v1/admin/announcements/{created['id']}",
        json={"recur_interval_minutes": 30},
    )
    assert resp.status_code == 400, resp.text


def test_content_update_bumps_version(admin_client):
    created = _create(admin_client)
    assert created["version"] == 1

    updated = admin_client.put(
        f"/api/v1/admin/announcements/{created['id']}",
        json={"title": "Updated notice"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2


def test_disable_does_not_bump_version(admin_client):
    created = _create(admin_client)
    updated = admin_client.put(
        f"/api/v1/admin/announcements/{created['id']}",
        json={"is_enabled": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 1


def test_reenable_bumps_version(admin_client):
    created = _create(admin_client)
    disabled = admin_client.put(
        f"/api/v1/admin/announcements/{created['id']}",
        json={"is_enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["version"] == 1

    enabled = admin_client.put(
        f"/api/v1/admin/announcements/{created['id']}",
        json={"is_enabled": True},
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["version"] == 2


def test_publish_bumps_version(admin_client):
    created = _create(admin_client)
    published = _publish(admin_client, created["id"])
    assert published["version"] == 2


def test_unrelated_update_does_not_bump_version(admin_client):
    created = _create(admin_client)
    published = _publish(admin_client, created["id"])
    assert published["version"] == 2
    updated = admin_client.put(
        f"/api/v1/admin/announcements/{created['id']}",
        json={"is_dismissible": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2


# ---------------------------------------------------------------------------
# Public feed + per-subject dismissal (integration)
# ---------------------------------------------------------------------------


def _auth_client(anon_client, user):
    token = create_access_token(
        subject=str(user.id),
        token_version=int(getattr(user, "token_version", 0) or 0),
    )
    anon_client.cookies.set(SESSION_COOKIE_NAME, token)
    return anon_client


async def _other_user(test_db):
    user = User(
        id=uuid.uuid4(),
        name="Second User",
        email=f"second-{uuid.uuid4().hex}@example.com",
        role="user",
        is_verified=True,
    )
    test_db.add(user)
    await test_db.commit()
    await test_db.refresh(user)
    return user


def _feed_ids(client):
    resp = client.get("/api/v1/platform/announcements")
    assert resp.status_code == 200, resp.text
    return [item["id"] for item in resp.json()]


def test_dismissal_hides_announcement_for_dismissing_subject(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(admin_client)
    _publish(admin_client, created["id"])
    aid = created["id"]

    client = _auth_client(anon_client, mock_user)
    assert aid in _feed_ids(client)

    resp = client.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    assert resp.status_code == 200, resp.text
    assert aid not in _feed_ids(client)


async def test_dismissal_does_not_affect_other_user(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(admin_client)
    _publish(admin_client, created["id"])
    aid = created["id"]

    first = _auth_client(anon_client, mock_user)
    first.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    assert aid not in _feed_ids(first)

    other = await _other_user(test_db)
    anon_client.cookies.clear()
    second = _auth_client(anon_client, other)
    assert aid in _feed_ids(second)


def test_dismissal_does_not_affect_anonymous_device(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(admin_client)
    _publish(admin_client, created["id"])
    aid = created["id"]

    client = _auth_client(anon_client, mock_user)
    client.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    assert aid not in _feed_ids(client)

    # A different browser (different device id) still sees it.
    anon_client.cookies.clear()
    anon_client.cookies.set("revora_device_id", str(uuid.uuid4()))
    assert aid in _feed_ids(anon_client)


def test_anonymous_device_dismissal_is_scoped_to_that_device(
    test_db, admin_client, anon_client
):
    """Two browsers (two device ids) must not share dismissals."""
    created = _create(admin_client)
    _publish(admin_client, created["id"])
    aid = created["id"]

    browser_a = str(uuid.uuid4())
    browser_b = str(uuid.uuid4())

    anon_client.cookies.set("revora_device_id", browser_a)
    resp = anon_client.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    assert resp.status_code == 200, resp.text
    assert aid not in _feed_ids(anon_client)

    anon_client.cookies.set("revora_device_id", browser_b)
    assert aid in _feed_ids(anon_client)


def test_signed_in_user_overrides_device_subject(
    test_db, admin_client, anon_client, mock_user
):
    """A signed-in user is tracked by account, not by browser."""
    created = _create(admin_client)
    _publish(admin_client, created["id"])
    aid = created["id"]

    anon_client.cookies.set("revora_device_id", str(uuid.uuid4()))
    anon_client.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    assert aid not in _feed_ids(anon_client)

    # The same browser, now signed in: the user subject has no dismissal.
    client = _auth_client(anon_client, mock_user)
    assert aid in _feed_ids(client)


def test_dismissal_survives_logout_and_login(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(admin_client, display_policy="once_until_dismissed")
    _publish(admin_client, created["id"])
    aid = created["id"]

    client = _auth_client(anon_client, mock_user)
    client.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    assert aid not in _feed_ids(client)

    # Log out (cookie cleared) then log back in with a fresh token.
    anon_client.cookies.clear()
    client = _auth_client(anon_client, mock_user)
    assert aid not in _feed_ids(client)


def test_updated_announcement_reappears_after_dismissal(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(admin_client)
    _publish(admin_client, created["id"])
    aid = created["id"]

    client = _auth_client(anon_client, mock_user)
    client.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    assert aid not in _feed_ids(client)

    # Admin edits the content -> new version -> eligible again.
    updated = admin_client.put(
        f"/api/v1/admin/announcements/{aid}",
        json={"title": "Updated notice"},
    )
    assert updated.status_code == 200, updated.text
    # draft(v1) -> published(v2) -> content edit(v3)
    assert updated.json()["version"] == 3
    assert aid in _feed_ids(client)


def test_republish_reappears_after_dismissal(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(admin_client)
    _publish(admin_client, created["id"])
    aid = created["id"]

    client = _auth_client(anon_client, mock_user)
    client.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    assert aid not in _feed_ids(client)

    # Unpublish then publish again -> new version.
    admin_client.put(
        f"/api/v1/admin/announcements/{aid}", json={"state": "draft"}
    )
    _publish(admin_client, aid)
    assert aid in _feed_ids(client)


def test_every_login_hidden_after_seen_within_session(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(admin_client, display_policy="every_login")
    _publish(admin_client, created["id"])
    aid = created["id"]

    client = _auth_client(anon_client, mock_user)
    assert aid in _feed_ids(client)

    resp = client.post(f"/api/v1/platform/announcements/{aid}/seen")
    assert resp.status_code == 200, resp.text
    assert aid not in _feed_ids(client)


async def test_every_login_reappears_after_next_login(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(admin_client, display_policy="every_login")
    _publish(admin_client, created["id"])
    aid = created["id"]

    client = _auth_client(anon_client, mock_user)
    client.post(f"/api/v1/platform/announcements/{aid}/seen")
    assert aid not in _feed_ids(client)

    # The "seen" marker belongs to the previous login session: backdate it,
    # then perform a new login (a fresh token carries a new session start).
    state = (
        await test_db.execute(
            select(AnnouncementState).where(
                AnnouncementState.announcement_id == uuid.UUID(aid)
            )
        )
    ).scalars().first()
    assert state is not None
    state.last_seen_at = datetime.now(UTC) - timedelta(hours=1)
    test_db.add(state)
    await test_db.commit()

    anon_client.cookies.clear()
    client = _auth_client(anon_client, mock_user)
    assert aid in _feed_ids(client)


async def test_recurring_feed_reappears_after_interval(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(
        admin_client,
        display_policy="recurring",
        recur_interval_minutes=60,
    )
    _publish(admin_client, created["id"])
    aid = created["id"]

    client = _auth_client(anon_client, mock_user)
    client.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    assert aid not in _feed_ids(client)

    # Backdate the dismissal beyond the interval.
    state = (
        await test_db.execute(
            select(AnnouncementState).where(
                AnnouncementState.announcement_id == uuid.UUID(aid)
            )
        )
    ).scalars().first()
    assert state is not None
    state.dismissed_at = datetime.now(UTC) - timedelta(minutes=61)
    test_db.add(state)
    await test_db.commit()

    assert aid in _feed_ids(client)


def test_draft_announcement_not_in_feed(test_db, admin_client, anon_client):
    created = _create(admin_client)
    aid = created["id"]
    assert aid not in _feed_ids(anon_client)


def test_dismiss_endpoint_is_idempotent(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(admin_client)
    _publish(admin_client, created["id"])
    aid = created["id"]

    client = _auth_client(anon_client, mock_user)
    first = client.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    second = client.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert aid not in _feed_ids(client)


def test_dismiss_unknown_announcement_returns_204(anon_client):
    resp = anon_client.post(
        f"/api/v1/platform/announcements/{uuid.uuid4()}/dismiss"
    )
    assert resp.status_code == 204


def test_feed_exposes_display_policy_fields(admin_client, anon_client):
    created = _create(
        admin_client,
        display_policy="recurring",
        recur_interval_minutes=30,
    )
    _publish(admin_client, created["id"])
    aid = created["id"]

    resp = anon_client.get("/api/v1/platform/announcements")
    assert resp.status_code == 200, resp.text
    item = next(a for a in resp.json() if a["id"] == aid)
    assert item["display_policy"] == "recurring"
    assert item["recur_interval_minutes"] == 30
    assert item["version"] >= 1
    assert item["dismissed"] is False


def test_admin_create_defaults_to_every_login(admin_client):
    created = _create(admin_client)
    assert created["display_policy"] == "every_login"


def test_non_dismissible_dismiss_is_rejected_and_stays_visible(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(admin_client, is_dismissible=False)
    _publish(admin_client, created["id"])
    aid = created["id"]

    client = _auth_client(anon_client, mock_user)
    assert aid in _feed_ids(client)

    resp = client.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    assert resp.status_code == 403, resp.text
    assert aid in _feed_ids(client)


def test_non_dismissible_seen_does_not_hide_announcement(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(admin_client, is_dismissible=False)
    _publish(admin_client, created["id"])
    aid = created["id"]

    client = _auth_client(anon_client, mock_user)
    assert aid in _feed_ids(client)

    resp = client.post(f"/api/v1/platform/announcements/{aid}/seen")
    assert resp.status_code == 204, resp.text
    assert aid in _feed_ids(client)


def test_non_dismissible_survives_logout_and_login(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(admin_client, is_dismissible=False)
    _publish(admin_client, created["id"])
    aid = created["id"]

    client = _auth_client(anon_client, mock_user)
    client.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    client.post(f"/api/v1/platform/announcements/{aid}/seen")
    assert aid in _feed_ids(client)

    anon_client.cookies.clear()
    client = _auth_client(anon_client, mock_user)
    assert aid in _feed_ids(client)


def test_reenable_resets_previous_dismissals(
    test_db, admin_client, anon_client, mock_user
):
    created = _create(admin_client)
    _publish(admin_client, created["id"])
    aid = created["id"]

    client = _auth_client(anon_client, mock_user)
    client.post(f"/api/v1/platform/announcements/{aid}/dismiss")
    assert aid not in _feed_ids(client)

    admin_client.put(
        f"/api/v1/admin/announcements/{aid}", json={"is_enabled": False}
    )
    enabled = admin_client.put(
        f"/api/v1/admin/announcements/{aid}", json={"is_enabled": True}
    )
    assert enabled.status_code == 200, enabled.text
    assert aid in _feed_ids(client)


def test_subject_helpers_build_distinct_keys():
    user = user_subject(uuid.uuid4(), None)
    device = device_subject(str(uuid.uuid4()), None)
    assert user.subject_type == "user"
    assert device.subject_type == "device"
    assert user.key != device.key
