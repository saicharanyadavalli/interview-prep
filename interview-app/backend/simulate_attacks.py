import json
from fastapi.testclient import TestClient
from main import app
from routes.auth import get_current_user
import io

def mock_get_current_user():
    return {
        "id": "12345678-1234-1234-1234-123456789012",
        "email": "test@example.com"
    }

def simulate_attacks():
    print("Initializing TestClient...")
    client = TestClient(app)
    
    print("1. Simulating repeated failed logins...")
    for _ in range(3):
        client.post(
            "/auth/session",
            json={"access_token": "invalid_token"},
            headers={"Authorization": "Bearer invalid_token"}
        )

    print("2. Simulating brute force (hitting rate limit)...")
    for _ in range(12):
        client.post(
            "/auth/session",
            json={"access_token": "invalid_token_for_rate_limit"},
            headers={"Authorization": "Bearer invalid_token"}
        )

    print("\n--- Overriding Auth Dependency for subsequent tests ---")
    app.dependency_overrides[get_current_user] = mock_get_current_user

    print("3. Simulating privilege escalation...")
    client.get("/admin/dashboard")

    print("4. Simulating unusual AI usage...")
    client.post(
        "/assistant/ask",
        json={
            "interview_question": "Explain quicksort",
            "user_doubt": "What's the weather like in Tokyo?",
            "conversation_history": []
        }
    )

    print("5. Simulating excessive uploads...")
    large_file_bytes = b"0" * (6 * 1024 * 1024) # 6MB
    client.post(
        "/profile/avatar/upload",
        files={"file": ("test.png", large_file_bytes, "image/png")}
    )

    # Revert override
    app.dependency_overrides.clear()
    
    print("\nAttacks simulated successfully. Check logs/app.log and run alert_monitor.py.")

if __name__ == "__main__":
    simulate_attacks()
