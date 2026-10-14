"""Contract tests: GET /auth/me must expose the persisted GitHub avatar.

The frontend hydrates the sidebar avatar from /auth/me after a page
refresh, while the login payloads use `image`. This endpoint serializes
the DB field `avatar_url`; the frontend maps it to `image` via
normalizeUserProfile. These tests pin the contract so the mapping
cannot silently break.
"""


async def test_me_returns_persisted_avatar_url(client, mock_user, test_db):
    avatar = "https://avatars.githubusercontent.com/u/123?v=4"
    mock_user.avatar_url = avatar
    test_db.add(mock_user)
    await test_db.commit()
    # Eagerly load every column: the endpoint serializes the ORM object
    # in a sync context, so no lazy attribute IO may remain.
    await test_db.refresh(mock_user)

    resp = client.get("/api/v1/auth/me")

    assert resp.status_code == 200
    body = resp.json()
    assert body["avatar_url"] == avatar
    assert body["id"] == str(mock_user.id)


async def test_me_avatar_null_when_user_has_none(client, mock_user):
    resp = client.get("/api/v1/auth/me")

    assert resp.status_code == 200
    assert resp.json()["avatar_url"] is None
