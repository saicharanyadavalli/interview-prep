"""Integration tests for destructive account and progress endpoints.

Tests:
- POST /profile/reset-progress:
    - Atomically resets question solving, learning track progress, and practice history.
    - Preserves user_profiles, user_comments, and other users' records.
    - Handles users with no prior progress cleanly.
    - Rejects unauthenticated requests with 401.
- DELETE /profile/account:
    - Requires explicit confirmation payload {"confirm": True}.
    - Rejects unconfirmed ({"confirm": False}) requests with 400.
    - Atomically removes all user data across user_identities, user_comments,
      user_progress, learning_track_progress, practice_history, and user_profiles.
    - Coordinates Cognito admin_delete_user with identity resolution gracefully.
    - Cleans up S3 avatar assets.
    - Rejects unauthenticated requests with 401.
"""

from unittest.mock import MagicMock, patch
import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "ap-south-2_MockPool123")
    monkeypatch.setenv("AWS_REGION", "ap-south-2")


def test_reset_progress_deletes_only_user_progress_and_preserves_profiles_and_comments(
    client: TestClient, mock_supabase, mock_user, mock_other_user
):
    """Verify POST /profile/reset-progress deletes only caller progress and leaves profile/comments intact."""
    # Seed data for current user and another user
    mock_supabase.set_table_data("user_profiles", [
        {
            "id": mock_user["id"],
            "email": mock_user["email"],
            "username": mock_user["username"],
            "name": mock_user["name"],
        },
        {
            "id": mock_other_user["id"],
            "email": mock_other_user["email"],
            "username": mock_other_user["username"],
            "name": mock_other_user["name"],
        },
    ])

    mock_supabase.set_table_data("user_progress", [
        {"id": "up-1", "user_id": mock_user["id"], "qnum": 1, "is_solved": True},
        {"id": "up-2", "user_id": mock_user["id"], "qnum": 2, "is_solved": True},
        {"id": "up-3", "user_id": mock_other_user["id"], "qnum": 1, "is_solved": True},
    ])

    mock_supabase.set_table_data("learning_track_progress", [
        {"id": "ltp-1", "user_id": mock_user["id"], "track_id": "system-design", "step_no": 1, "completed": True},
        {"id": "ltp-2", "user_id": mock_user["id"], "track_id": "system-design", "step_no": 2, "completed": True},
        {"id": "ltp-3", "user_id": mock_other_user["id"], "track_id": "system-design", "step_no": 1, "completed": True},
    ])

    mock_supabase.set_table_data("practice_history", [
        {"id": "ph-1", "user_id": mock_user["id"], "qnum": 1},
        {"id": "ph-2", "user_id": mock_other_user["id"], "qnum": 2},
    ])

    mock_supabase.set_table_data("user_comments", [
        {"id": "uc-1", "user_id": mock_user["id"], "qnum": 1, "comment_text": "Important edge case notes"},
        {"id": "uc-2", "user_id": mock_other_user["id"], "qnum": 1, "comment_text": "Other user comment"},
    ])

    res = client.post("/profile/reset-progress")
    assert res.status_code == 200
    data = res.json()

    assert data["success"] is True
    assert "reset successfully" in data["message"].lower()
    assert data["stats"]["user_progress_deleted"] == 2
    assert data["stats"]["learning_track_progress_deleted"] == 2
    assert data["stats"]["practice_history_deleted"] == 1

    # Verify user's progress records were purged
    remaining_up = mock_supabase._tables.get("user_progress", [])
    assert len(remaining_up) == 1
    assert remaining_up[0]["user_id"] == mock_other_user["id"]

    remaining_ltp = mock_supabase._tables.get("learning_track_progress", [])
    assert len(remaining_ltp) == 1
    assert remaining_ltp[0]["user_id"] == mock_other_user["id"]

    remaining_ph = mock_supabase._tables.get("practice_history", [])
    assert len(remaining_ph) == 1
    assert remaining_ph[0]["user_id"] == mock_other_user["id"]

    # Verify user_profiles was NOT modified or deleted
    profiles = mock_supabase._tables.get("user_profiles", [])
    assert len(profiles) == 2
    assert any(p["id"] == mock_user["id"] for p in profiles)

    # Verify user_comments was NOT modified or deleted
    comments = mock_supabase._tables.get("user_comments", [])
    assert len(comments) == 2
    assert any(c["user_id"] == mock_user["id"] for c in comments)


def test_reset_progress_empty_state_succeeds(client: TestClient, mock_supabase, mock_user):
    """Verify POST /profile/reset-progress returns 200 with 0 count when no records exist."""
    mock_supabase.set_table_data("user_progress", [])
    mock_supabase.set_table_data("learning_track_progress", [])
    mock_supabase.set_table_data("practice_history", [])

    res = client.post("/profile/reset-progress")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["stats"]["user_progress_deleted"] == 0
    assert data["stats"]["learning_track_progress_deleted"] == 0
    assert data["stats"]["practice_history_deleted"] == 0


def test_reset_progress_unauthenticated_returns_401(unauth_client: TestClient):
    """Verify POST /profile/reset-progress returns 401 when no token is provided."""
    res = unauth_client.post("/profile/reset-progress")
    assert res.status_code == 401


def test_delete_account_requires_confirm_true(client: TestClient):
    """Verify DELETE /profile/account returns 400 when confirm is False, or 422 if missing."""
    # confirm = False
    res = client.request("DELETE", "/profile/account", json={"confirm": False})
    assert res.status_code == 400
    assert "confirm=true" in res.json()["detail"].lower()

    # Missing confirm field
    res_empty = client.request("DELETE", "/profile/account", json={})
    assert res_empty.status_code == 422

    # Extra disallowed fields
    res_extra = client.request("DELETE", "/profile/account", json={"confirm": True, "extra": "forbidden"})
    assert res_extra.status_code == 422


def test_delete_account_deletes_all_user_records_transactionally(
    client: TestClient, mock_supabase, mock_user, mock_other_user
):
    """Verify DELETE /profile/account removes all user records across all tables."""
    user_id = mock_user["id"]
    other_id = mock_other_user["id"]

    mock_supabase.set_table_data("user_profiles", [
        {"id": user_id, "email": mock_user["email"], "username": mock_user["username"], "avatar_url": ""},
        {"id": other_id, "email": mock_other_user["email"], "username": mock_other_user["username"]},
    ])
    mock_supabase.set_table_data("user_identities", [
        {"id": "ident-1", "user_id": user_id, "provider": "cognito", "provider_sub": "cognito-sub-123", "email": mock_user["email"]},
        {"id": "ident-2", "user_id": other_id, "provider": "cognito", "provider_sub": "cognito-sub-999", "email": mock_other_user["email"]},
    ])
    mock_supabase.set_table_data("user_comments", [
        {"id": "com-1", "user_id": user_id, "qnum": 10},
        {"id": "com-2", "user_id": other_id, "qnum": 10},
    ])
    mock_supabase.set_table_data("user_progress", [
        {"id": "up-1", "user_id": user_id, "qnum": 10},
        {"id": "up-2", "user_id": other_id, "qnum": 10},
    ])
    mock_supabase.set_table_data("learning_track_progress", [
        {"id": "ltp-1", "user_id": user_id, "track_id": "system-design", "step_no": 1},
        {"id": "ltp-2", "user_id": other_id, "track_id": "system-design", "step_no": 1},
    ])
    mock_supabase.set_table_data("practice_history", [
        {"id": "ph-1", "user_id": user_id, "qnum": 10},
        {"id": "ph-2", "user_id": other_id, "qnum": 10},
    ])

    with patch("boto3.client") as mock_boto:
        mock_cognito = MagicMock()
        mock_boto.return_value = mock_cognito

        res = client.request("DELETE", "/profile/account", json={"confirm": True})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "deleted successfully" in data["message"].lower()

        # Check Cognito AdminDeleteUser was called with resolved provider_sub identity
        mock_cognito.admin_delete_user.assert_called_once_with(
            UserPoolId="ap-south-2_MockPool123",
            Username="cognito-sub-123",
        )

    # Check that caller's records are gone from all tables
    assert len(mock_supabase._tables.get("user_profiles", [])) == 1
    assert mock_supabase._tables["user_profiles"][0]["id"] == other_id

    assert len(mock_supabase._tables.get("user_identities", [])) == 1
    assert mock_supabase._tables["user_identities"][0]["user_id"] == other_id

    assert len(mock_supabase._tables.get("user_comments", [])) == 1
    assert mock_supabase._tables["user_comments"][0]["user_id"] == other_id

    assert len(mock_supabase._tables.get("user_progress", [])) == 1
    assert mock_supabase._tables["user_progress"][0]["user_id"] == other_id

    assert len(mock_supabase._tables.get("learning_track_progress", [])) == 1
    assert mock_supabase._tables["learning_track_progress"][0]["user_id"] == other_id

    assert len(mock_supabase._tables.get("practice_history", [])) == 1
    assert mock_supabase._tables["practice_history"][0]["user_id"] == other_id


def test_delete_account_deletes_with_username_fallback_when_no_identities(
    client: TestClient, mock_supabase, mock_user
):
    """Verify DELETE /profile/account falls back to username when user_identities has no rows."""
    user_id = mock_user["id"]
    mock_supabase.set_table_data("user_profiles", [
        {"id": user_id, "email": mock_user["email"], "username": mock_user["username"]}
    ])
    mock_supabase.set_table_data("user_identities", [])

    with patch("boto3.client") as mock_boto:
        mock_cognito = MagicMock()
        mock_boto.return_value = mock_cognito

        res = client.request("DELETE", "/profile/account", json={"confirm": True})
        assert res.status_code == 200
        assert res.json()["success"] is True

        mock_cognito.admin_delete_user.assert_called_once_with(
            UserPoolId="ap-south-2_MockPool123",
            Username=mock_user["username"],
        )


def test_delete_account_handles_cognito_failure_gracefully(client: TestClient, mock_supabase, mock_user):
    """Verify DELETE /profile/account succeeds even if Cognito user is not found or fails."""
    user_id = mock_user["id"]
    mock_supabase.set_table_data("user_profiles", [
        {"id": user_id, "email": mock_user["email"], "username": mock_user["username"]}
    ])

    with patch("boto3.client") as mock_boto:
        mock_cognito = MagicMock()
        mock_cognito.admin_delete_user.side_effect = ClientError(
            {"Error": {"Code": "UserNotFoundException", "Message": "User not found."}},
            "AdminDeleteUser",
        )
        mock_boto.return_value = mock_cognito

        res = client.request("DELETE", "/profile/account", json={"confirm": True})
        assert res.status_code == 200
        assert res.json()["success"] is True


def test_delete_account_cleans_up_s3_avatar(client: TestClient, mock_supabase, mock_user):
    """Verify DELETE /profile/account attempts S3 avatar cleanup if user had an avatar."""
    user_id = mock_user["id"]
    avatar_url = f"https://d29abcdef01234.cloudfront.net/avatars/{user_id}/sample-avatar.png"

    mock_supabase.set_table_data("user_profiles", [
        {"id": user_id, "email": mock_user["email"], "username": mock_user["username"], "avatar_url": avatar_url}
    ])

    with patch("services.s3_storage_service.delete_asset") as mock_delete_asset, \
         patch("boto3.client"):
        res = client.request("DELETE", "/profile/account", json={"confirm": True})
        assert res.status_code == 200
        assert res.json()["success"] is True
        mock_delete_asset.assert_called_once_with(f"avatars/{user_id}/sample-avatar.png")


def test_delete_account_unauthenticated_returns_401(unauth_client: TestClient):
    """Verify DELETE /profile/account returns 401 when no token is provided."""
    res = unauth_client.request("DELETE", "/profile/account", json={"confirm": True})
    assert res.status_code == 401
