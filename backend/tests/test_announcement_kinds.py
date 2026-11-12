"""Regression tests for announcement kind storage and validation."""

import pytest

from app.models.platform import ANNOUNCEMENT_KINDS, Announcement


def test_announcement_kind_column_fits_all_supported_kinds():
    column = Announcement.__table__.c.kind

    assert column.type.length == 50
    assert max(len(kind) for kind in ANNOUNCEMENT_KINDS) <= column.type.length


@pytest.mark.parametrize("kind", ANNOUNCEMENT_KINDS)
async def test_create_announcement_accepts_every_supported_kind(
    test_db, admin_client, kind
):
    response = admin_client.post(
        "/api/v1/admin/announcements",
        json={
            "title": f"{kind} announcement",
            "message": "Regression test message",
            "kind": kind,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["kind"] == kind


async def test_update_announcement_accepts_scheduled_maintenance(
    test_db, admin_client
):
    created = admin_client.post(
        "/api/v1/admin/announcements",
        json={
            "title": "Update kind",
            "message": "Regression test message",
            "kind": "general",
        },
    )
    assert created.status_code == 201, created.text
    announcement_id = created.json()["id"]

    response = admin_client.put(
        f"/api/v1/admin/announcements/{announcement_id}",
        json={"kind": "scheduled_maintenance"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "scheduled_maintenance"


async def test_invalid_announcement_kind_returns_400_on_create(
    test_db, admin_client
):
    response = admin_client.post(
        "/api/v1/admin/announcements",
        json={
            "title": "Invalid kind",
            "message": "Regression test message",
            "kind": "not_a_supported_kind",
        },
    )

    assert response.status_code == 400


async def test_invalid_announcement_kind_returns_400_on_update(
    test_db, admin_client
):
    created = admin_client.post(
        "/api/v1/admin/announcements",
        json={
            "title": "Invalid kind update",
            "message": "Regression test message",
            "kind": "general",
        },
    )
    assert created.status_code == 201, created.text
    announcement_id = created.json()["id"]

    response = admin_client.put(
        f"/api/v1/admin/announcements/{announcement_id}",
        json={"kind": "not_a_supported_kind"},
    )

    assert response.status_code == 400
