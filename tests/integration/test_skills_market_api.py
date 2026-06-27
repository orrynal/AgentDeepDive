import pytest
import httpx
import uuid
from sqlalchemy import select
from src.api.main import app
from src.config import settings
from src.database import async_session
from src.core.auth.models import UserModel
from src.core.auth.security import hash_password

@pytest.mark.asyncio
async def test_skills_market_and_install_api():
    # Setup test user for the default tenant
    default_tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    async with async_session() as session:
        result = await session.execute(select(UserModel).where(UserModel.username == "test_skills_admin"))
        user = result.scalar_one_or_none()
        if not user:
            user = UserModel(
                id=uuid.uuid4(),
                username="test_skills_admin",
                password_hash=hash_password("testpassword123"),
                tenant_id=default_tenant_id,
                role="admin"
            )
            session.add(user)
            await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Login to get JWT
        login_payload = {
            "username": "test_skills_admin",
            "password": "testpassword123"
        }
        login_response = await client.post("/api/v1/auth/login", json=login_payload)
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # 1. GET /api/v1/skills/market/search - Search all skills
        response = await client.get("/api/v1/skills/market/search", headers=auth_headers)
        assert response.status_code == 200
        skills = response.json()
        assert len(skills) > 0
        
        # Verify specific skill like web_searcher is present
        searcher_found = any(s["skill_id"] == "web-searcher-v1" for s in skills)
        assert searcher_found is True

        # 2. GET /api/v1/skills/market/search?query=web_searcher - Filter skills
        response = await client.get("/api/v1/skills/market/search?query=web-searcher-v1", headers=auth_headers)
        assert response.status_code == 200
        filtered_skills = response.json()
        assert len(filtered_skills) > 0
        assert all("web-searcher-v1" in s["skill_id"] for s in filtered_skills)

        # 3. POST /api/v1/skills/install - Install as global
        install_payload = {
            "skill_name_or_url": "web-searcher-v1",
            "scope": "global"
        }
        response = await client.post("/api/v1/skills/install", json=install_payload, headers=auth_headers)
        assert response.status_code == 200
        installed = response.json()
        assert installed["skill_id"] == "web-searcher-v1"
        assert installed["workspace_path"] is None

        # 4. POST /api/v1/skills/install - Install as project
        install_payload = {
            "skill_name_or_url": "web-searcher-v1",
            "scope": "project",
            "workspace_path": "/tmp/mock_workspace"
        }
        response = await client.post("/api/v1/skills/install", json=install_payload, headers=auth_headers)
        assert response.status_code == 200
        installed_project = response.json()
        assert installed_project["skill_id"] == "web-searcher-v1"
        assert installed_project["workspace_path"] == "/tmp/mock_workspace"

        # 5. GET /api/v1/skills - List installed skills for workspace
        response = await client.get("/api/v1/skills?workspace_path=/tmp/mock_workspace", headers=auth_headers)
        assert response.status_code == 200
        installed_list = response.json()
        has_skill = any(s["skill_id"] == "web-searcher-v1" for s in installed_list)
        assert has_skill is True

        # 6. DELETE /api/v1/skills/{skill_id} - Deactivate (delete) skill
        response = await client.delete("/api/v1/skills/web-searcher-v1", headers=auth_headers)
        assert response.status_code == 204

        # Verify deactivation by checking list active-only
        response = await client.get("/api/v1/skills?active_only=true&workspace_path=/tmp/mock_workspace", headers=auth_headers)
        assert response.status_code == 200
        active_list = response.json()
        has_skill_active = any(s["skill_id"] == "web-searcher-v1" for s in active_list)
        assert has_skill_active is False

    # Clean up from DB
    from sqlalchemy import text
    async with async_session() as session:
        await session.execute(text("DELETE FROM skills WHERE skill_id = 'web-searcher-v1'"))
        await session.execute(text("DELETE FROM users WHERE username = 'test_skills_admin'"))
        await session.commit()
