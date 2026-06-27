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
async def test_roles_api_endpoints():
    # Setup test user for the default tenant
    default_tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    async with async_session() as session:
        result = await session.execute(select(UserModel).where(UserModel.username == "test_roles_admin"))
        user = result.scalar_one_or_none()
        if not user:
            user = UserModel(
                id=uuid.uuid4(),
                username="test_roles_admin",
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
            "username": "test_roles_admin",
            "password": "testpassword123"
        }
        login_response = await client.post("/api/v1/auth/login", json=login_payload)
        assert login_response.status_code == 200
        token = login_response.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}

        # 1. GET /api/v1/roles - List all roles
        response = await client.get("/api/v1/roles", headers=auth_headers)
        assert response.status_code == 200
        roles = response.json()
        assert len(roles) >= 10
        
        # Check that supervisor role exists
        supervisor_exists = any(r["role_id"] == "supervisor" for r in roles)
        assert supervisor_exists is True

        # 2. GET /api/v1/roles/{role_id} - Get specific role
        response = await client.get("/api/v1/roles/senior_coder", headers=auth_headers)
        assert response.status_code == 200
        role = response.json()
        assert role["role_id"] == "senior_coder"
        assert "code_refactor" in role["allowed_skills"]

        # 3. GET non-existent role - 404
        response = await client.get("/api/v1/roles/non_existent_role", headers=auth_headers)
        assert response.status_code == 404

        # 4. POST /api/v1/roles - Create new role
        new_role_payload = {
            "role_id": "api_test_role",
            "name": "API Test Role",
            "description": "For testing REST endpoints",
            "system_prompt_prefix": "You are a REST API test role.",
            "allowed_skills": ["code_analysis"],
            "default_model": "gpt-4o",
            "max_token_budget": 15000
        }
        response = await client.post("/api/v1/roles", json=new_role_payload, headers=auth_headers)
        assert response.status_code == 201
        created_role = response.json()
        assert created_role["role_id"] == "api_test_role"

        # Try creating duplicate - 409 Conflict
        response = await client.post("/api/v1/roles", json=new_role_payload, headers=auth_headers)
        assert response.status_code == 409

        # 5. PUT /api/v1/roles/{role_id} - Update role
        update_payload = {
            "name": "Updated API Test Role",
            "max_token_budget": 25000
        }
        response = await client.put("/api/v1/roles/api_test_role", json=update_payload, headers=auth_headers)
        assert response.status_code == 200
        updated_role = response.json()
        assert updated_role["name"] == "Updated API Test Role"
        assert updated_role["max_token_budget"] == 25000

        # 6. DELETE /api/v1/roles/{role_id} - Deactivate role
        response = await client.delete("/api/v1/roles/api_test_role", headers=auth_headers)
        assert response.status_code == 204

        # Verify deactivation
        response = await client.get("/api/v1/roles/api_test_role", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["is_active"] is False

    # Clean up from DB
    from sqlalchemy import text
    async with async_session() as session:
        await session.execute(text("DELETE FROM roles WHERE role_id = 'api_test_role'"))
        await session.execute(text("DELETE FROM users WHERE username = 'test_roles_admin'"))
        await session.commit()
