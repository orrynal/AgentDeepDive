import uuid
import pytest
import httpx
from src.api.main import app
from src.database import async_session
from sqlalchemy import text, select
from src.core.auth.models import TenantModel, UserModel
from src.core.auth.security import hash_password

pytestmark = pytest.mark.integration

@pytest.mark.asyncio
async def test_auth_registration_and_login():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Register a new tenant
        tenant_name = f"AuthTestTenant-{uuid.uuid4().hex[:6]}"
        username = f"admin-{uuid.uuid4().hex[:6]}"
        reg_payload = {
            "tenant_name": tenant_name,
            "username": username,
            "password": "strongpassword123"
        }
        response = await client.post("/api/v1/auth/register", json=reg_payload)
        assert response.status_code == 201
        reg_data = response.json()
        assert reg_data["user"]["username"] == username
        assert reg_data["user"]["role"] == "admin"
        assert "tenant_id" in reg_data["user"]

        # 2. Login with registered user
        login_payload = {
            "username": username,
            "password": "strongpassword123"
        }
        response = await client.post("/api/v1/auth/login", json=login_payload)
        assert response.status_code == 200
        login_data = response.json()
        assert "access_token" in login_data
        token = login_data["access_token"]

        # 3. Access GET /auth/me
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get("/api/v1/auth/me", headers=headers)
        assert response.status_code == 200
        me_data = response.json()
        assert me_data["username"] == username
        assert me_data["role"] == "admin"

    # Cleanup
    async with async_session() as session:
        await session.execute(text(f"DELETE FROM users WHERE username = '{username}'"))
        await session.execute(text(f"DELETE FROM tenants WHERE name = '{tenant_name}'"))
        await session.commit()


@pytest.mark.asyncio
async def test_rbac_permissions():
    # Setup: Create a viewer user in the default tenant
    default_tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    username_viewer = f"viewer-{uuid.uuid4().hex[:6]}"
    async with async_session() as session:
        viewer = UserModel(
            id=uuid.uuid4(),
            username=username_viewer,
            password_hash=hash_password("viewpassword123"),
            tenant_id=default_tenant_id,
            role="viewer"
        )
        session.add(viewer)
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Login as viewer
        login_payload = {
            "username": username_viewer,
            "password": "viewpassword123"
        }
        response = await client.post("/api/v1/auth/login", json=login_payload)
        assert response.status_code == 200
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Viewer should be able to list roles (GET /roles)
        response = await client.get("/api/v1/roles", headers=headers)
        assert response.status_code == 200

        # 2. Viewer should NOT be able to create a role (POST /roles) -> 403
        new_role_payload = {
            "role_id": "viewer_test_role",
            "name": "Viewer Test Role",
            "description": "Viewer shouldn't create this",
            "system_prompt_prefix": "You are a test role.",
            "allowed_skills": [],
            "default_model": "gpt-4o",
            "max_token_budget": 1000
        }
        response = await client.post("/api/v1/roles", json=new_role_payload, headers=headers)
        assert response.status_code == 403

    # Cleanup
    async with async_session() as session:
        await session.execute(text(f"DELETE FROM users WHERE username = '{username_viewer}'"))
        await session.commit()


@pytest.mark.asyncio
async def test_multi_tenant_isolation():
    # Setup: Create two tenants and their admin users
    tenant_a_name = f"TenantA-{uuid.uuid4().hex[:6]}"
    tenant_b_name = f"TenantB-{uuid.uuid4().hex[:6]}"
    user_a_name = f"admina-{uuid.uuid4().hex[:6]}"
    user_b_name = f"adminb-{uuid.uuid4().hex[:6]}"

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Register Tenant A
        res_a = await client.post("/api/v1/auth/register", json={
            "tenant_name": tenant_a_name, "username": user_a_name, "password": "passwordA123"
        })
        assert res_a.status_code == 201
        tenant_a_id = res_a.json()["user"]["tenant_id"]

        # Register Tenant B
        res_b = await client.post("/api/v1/auth/register", json={
            "tenant_name": tenant_b_name, "username": user_b_name, "password": "passwordB123"
        })
        assert res_b.status_code == 201
        tenant_b_id = res_b.json()["user"]["tenant_id"]

        # Login A
        res_login_a = await client.post("/api/v1/auth/login", json={"username": user_a_name, "password": "passwordA123"})
        token_a = res_login_a.json()["access_token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        # Login B
        res_login_b = await client.post("/api/v1/auth/login", json={"username": user_b_name, "password": "passwordB123"})
        token_b = res_login_b.json()["access_token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # 1. Tenant A creates a role
        role_payload = {
            "role_id": "isolated_role_a",
            "name": "Isolated Role A",
            "description": "Role only visible to Tenant A",
            "system_prompt_prefix": "You are Role A.",
            "allowed_skills": [],
            "default_model": "gpt-4o",
            "max_token_budget": 5000
        }
        res_create_role = await client.post("/api/v1/roles", json=role_payload, headers=headers_a)
        assert res_create_role.status_code == 201

        # 2. Tenant A lists roles, should see "isolated_role_a"
        res_list_a = await client.get("/api/v1/roles", headers=headers_a)
        assert res_list_a.status_code == 200
        roles_a = [r["role_id"] for r in res_list_a.json()]
        assert "isolated_role_a" in roles_a

        # 3. Tenant B lists roles, should NOT see "isolated_role_a"
        res_list_b = await client.get("/api/v1/roles", headers=headers_b)
        assert res_list_b.status_code == 200
        roles_b = [r["role_id"] for r in res_list_b.json()]
        assert "isolated_role_a" not in roles_b

        # 4. Tenant B tries to GET Tenant A's role directly, should return 404
        res_get_b = await client.get("/api/v1/roles/isolated_role_a", headers=headers_b)
        assert res_get_b.status_code == 404

    # Cleanup
    async with async_session() as session:
        await session.execute(text(f"DELETE FROM roles WHERE role_id = 'isolated_role_a'"))
        await session.execute(text(f"DELETE FROM users WHERE username IN ('{user_a_name}', '{user_b_name}')"))
        await session.execute(text(f"DELETE FROM tenants WHERE id IN ('{tenant_a_id}', '{tenant_b_id}')"))
        await session.commit()
