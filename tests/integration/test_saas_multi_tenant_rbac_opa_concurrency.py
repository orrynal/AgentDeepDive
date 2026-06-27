import uuid
import pytest
import httpx
import urllib.request
import json
import anyio
from sqlalchemy import select, text
from src.api.main import app
from src.database import async_session
from src.core.auth.models import TenantModel, UserModel
from src.core.auth.security import hash_password
from src.config import settings
from src.core.governance.guardrails import GuardrailEngine

@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


class TestSaaSMultiTenantRbacOpaConcurrency:
    
    @pytest.fixture(autouse=True)
    async def setup_tenants_and_users(self):
        # Generate unique ids and names
        self.tenant_a_id = uuid.uuid4()
        self.tenant_b_id = uuid.uuid4()
        self.tenant_a_name = f"TenantA-{uuid.uuid4().hex[:6]}"
        self.tenant_b_name = f"TenantB-{uuid.uuid4().hex[:6]}"
        
        self.users_to_cleanup = []
        self.tenants_to_cleanup = [self.tenant_a_id, self.tenant_b_id]
        
        # Usernames
        self.user_a_admin = f"admin-a-{uuid.uuid4().hex[:4]}"
        self.user_a_dev = f"dev-a-{uuid.uuid4().hex[:4]}"
        self.user_a_viewer = f"viewer-a-{uuid.uuid4().hex[:4]}"
        
        self.user_b_admin = f"admin-b-{uuid.uuid4().hex[:4]}"
        self.user_b_dev = f"dev-b-{uuid.uuid4().hex[:4]}"
        self.user_b_viewer = f"viewer-b-{uuid.uuid4().hex[:4]}"
        
        # Insert into DB
        async with async_session() as session:
            # Create tenants
            tenant_a = TenantModel(id=self.tenant_a_id, name=self.tenant_a_name)
            tenant_b = TenantModel(id=self.tenant_b_id, name=self.tenant_b_name)
            session.add_all([tenant_a, tenant_b])
            
            # Create Tenant A Users
            u_a_admin = UserModel(
                id=uuid.uuid4(), username=self.user_a_admin,
                password_hash=hash_password("adminApwd"), tenant_id=self.tenant_a_id, role="admin"
            )
            u_a_dev = UserModel(
                id=uuid.uuid4(), username=self.user_a_dev,
                password_hash=hash_password("devApwd"), tenant_id=self.tenant_a_id, role="developer"
            )
            u_a_viewer = UserModel(
                id=uuid.uuid4(), username=self.user_a_viewer,
                password_hash=hash_password("viewerApwd"), tenant_id=self.tenant_a_id, role="viewer"
            )
            
            # Create Tenant B Users
            u_b_admin = UserModel(
                id=uuid.uuid4(), username=self.user_b_admin,
                password_hash=hash_password("adminBpwd"), tenant_id=self.tenant_b_id, role="admin"
            )
            u_b_dev = UserModel(
                id=uuid.uuid4(), username=self.user_b_dev,
                password_hash=hash_password("devBpwd"), tenant_id=self.tenant_b_id, role="developer"
            )
            u_b_viewer = UserModel(
                id=uuid.uuid4(), username=self.user_b_viewer,
                password_hash=hash_password("viewerBpwd"), tenant_id=self.tenant_b_id, role="viewer"
            )
            
            session.add_all([u_a_admin, u_a_dev, u_a_viewer, u_b_admin, u_b_dev, u_b_viewer])
            await session.commit()
            
            self.users_to_cleanup.extend([
                self.user_a_admin, self.user_a_dev, self.user_a_viewer,
                self.user_b_admin, self.user_b_dev, self.user_b_viewer
            ])
            
        yield
        
        # Cleanup
        async with async_session() as session:
            # Cleanup roles or other objects created by tests if necessary
            await session.execute(text("DELETE FROM roles WHERE role_id LIKE 'saas_test_%'"))
            # Cleanup users and tenants
            if self.users_to_cleanup:
                usernames_str = ", ".join(f"'{u}'" for u in self.users_to_cleanup)
                await session.execute(text(f"DELETE FROM users WHERE username IN ({usernames_str})"))
            if self.tenants_to_cleanup:
                ids_str = ", ".join(f"'{tid}'" for tid in self.tenants_to_cleanup)
                await session.execute(text(f"DELETE FROM tenants WHERE id IN ({ids_str})"))
            await session.commit()

    async def get_jwt_token(self, client: httpx.AsyncClient, username, password) -> str:
        res = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert res.status_code == 200
        return res.json()["access_token"]

    @pytest.mark.anyio
    async def test_rbac_and_tenant_isolation_endpoints(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Login and get tokens
            token_a_admin = await self.get_jwt_token(client, self.user_a_admin, "adminApwd")
            token_a_dev = await self.get_jwt_token(client, self.user_a_dev, "devApwd")
            token_a_viewer = await self.get_jwt_token(client, self.user_a_viewer, "viewerApwd")
            token_b_admin = await self.get_jwt_token(client, self.user_b_admin, "adminBpwd")
            
            headers_a_admin = {"Authorization": f"Bearer {token_a_admin}"}
            headers_a_dev = {"Authorization": f"Bearer {token_a_dev}"}
            headers_a_viewer = {"Authorization": f"Bearer {token_a_viewer}"}
            headers_b_admin = {"Authorization": f"Bearer {token_b_admin}"}
            
            # --- RBAC Checks on Tenant A ---
            
            # 1. Admin creates a custom role for Tenant A
            role_payload = {
                "role_id": "saas_test_role_1",
                "name": "SaaS Test Role 1",
                "description": "Custom role for Tenant A",
                "system_prompt_prefix": "Test Prompt",
                "allowed_skills": [],
                "default_model": "gpt-4o",
                "max_token_budget": 1000
            }
            res_create = await client.post("/api/v1/roles", json=role_payload, headers=headers_a_admin)
            assert res_create.status_code == 201
            
            # 2. Developer tries to create custom role -> Should succeed (Developer has creation privilege)
            role_payload_dev = {
                "role_id": "saas_test_role_dev",
                "name": "SaaS Dev Role",
                "description": "Developer can create role",
                "system_prompt_prefix": "Test Prompt",
                "allowed_skills": [],
                "default_model": "gpt-4o",
                "max_token_budget": 1000
            }
            res_create_dev = await client.post("/api/v1/roles", json=role_payload_dev, headers=headers_a_dev)
            assert res_create_dev.status_code == 201
            
            # 3. Developer tries to DELETE a role -> Should get 403 Forbidden (Only Admin can delete/deactivate)
            res_delete_dev = await client.delete("/api/v1/roles/saas_test_role_dev", headers=headers_a_dev)
            assert res_delete_dev.status_code == 403
            
            # 4. Viewer tries to create custom role -> Should get 403 Forbidden
            role_payload_viewer = {
                "role_id": "saas_test_role_viewer",
                "name": "SaaS Viewer Role",
                "description": "Viewer cannot create this",
                "system_prompt_prefix": "Test Prompt",
                "allowed_skills": [],
                "default_model": "gpt-4o",
                "max_token_budget": 1000
            }
            res_create_viewer = await client.post("/api/v1/roles", json=role_payload_viewer, headers=headers_a_viewer)
            assert res_create_viewer.status_code == 403
            
            # 5. Viewer lists roles -> Should succeed (Viewer has read access)
            res_list = await client.get("/api/v1/roles", headers=headers_a_viewer)
            assert res_list.status_code == 200
            roles_list = [r["role_id"] for r in res_list.json()]
            assert "saas_test_role_1" in roles_list
            
            # --- Multi-Tenant Isolation Checks ---
            
            # 5. Tenant B Admin lists roles -> Should NOT see Tenant A's role
            res_list_b = await client.get("/api/v1/roles", headers=headers_b_admin)
            assert res_list_b.status_code == 200
            roles_list_b = [r["role_id"] for r in res_list_b.json()]
            assert "saas_test_role_1" not in roles_list_b
            
            # 6. Tenant B Admin tries to fetch Tenant A's role directly -> Should get 404 Not Found (isolated)
            res_get_b = await client.get("/api/v1/roles/saas_test_role_1", headers=headers_b_admin)
            assert res_get_b.status_code == 404

    @pytest.mark.anyio
    async def test_opa_network_chaos_and_local_ast_fallback(self, monkeypatch):
        """Verify safety guardrails continue working reliably when OPA experiences timeout/connection chaos."""
        monkeypatch.setattr(settings, "opa_enabled", True)
        
        # 1. Simulate OPA network outage/connection failure
        def mock_urlopen_failure(req, timeout=None):
            raise urllib.error.URLError("Connection timed out / connection refused")
        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_failure)
        
        engine = GuardrailEngine()
        engine._policy_uploaded = False
        
        # When OPA is unreachable, verify that local fallback engine successfully blocks malicious shell commands (L4)
        assert engine.evaluate("shell_exec", {"command": "sudo rm -rf /"}) == "L4"
        assert engine.evaluate("shell_exec", {"command": "dd if=/dev/zero of=/dev/sda"}) == "L4"
        assert engine.evaluate("shell_exec", {"command": "chmod +x scripts/"}) == "L4"
        
        # Path traversal out of workspace is blocked (L4)
        assert engine.evaluate("file_write", {"TargetFile": "../../../etc/passwd"}) == "L4"
        
        # Risky commands require approval (L3)
        assert engine.evaluate("shell_exec", {"command": "rm file.txt"}) == "L3"
        assert engine.evaluate("shell_exec", {"command": "mv file.txt dest.txt"}) == "L3"
        assert engine.evaluate("shell_exec", {"command": "curl http://exfil.com"}) == "L3"
        
        # Normal commands are allowed (L2)
        assert engine.evaluate("shell_exec", {"command": "echo 'Hello World'"}) == "L2"
        assert engine.evaluate("shell_exec", {"command": "git status"}) == "L2"

    @pytest.mark.anyio
    async def test_high_concurrency_tenant_access(self):
        """Simulate high concurrent requests from multiple tenants to verify no cross-tenant leakage or race conditions."""
        transport = httpx.ASGITransport(app=app)
        
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            token_a = await self.get_jwt_token(client, self.user_a_admin, "adminApwd")
            token_b = await self.get_jwt_token(client, self.user_b_admin, "adminBpwd")
            
            headers_a = {"Authorization": f"Bearer {token_a}"}
            headers_b = {"Authorization": f"Bearer {token_b}"}
            
            # Create a unique role for each tenant
            res_a = await client.post("/api/v1/roles", json={
                "role_id": "saas_test_role_a_concur",
                "name": "Concur A", "description": "T A", "system_prompt_prefix": "A",
                "allowed_skills": [], "default_model": "gpt-4o", "max_token_budget": 1000
            }, headers=headers_a)
            assert res_a.status_code == 201
            
            res_b = await client.post("/api/v1/roles", json={
                "role_id": "saas_test_role_b_concur",
                "name": "Concur B", "description": "T B", "system_prompt_prefix": "B",
                "allowed_skills": [], "default_model": "gpt-4o", "max_token_budget": 1000
            }, headers=headers_b)
            assert res_b.status_code == 201
            
            async def tenant_a_task():
                # Perform 15 rapid read checks on Tenant A
                for _ in range(15):
                    resp = await client.get("/api/v1/roles", headers=headers_a)
                    assert resp.status_code == 200
                    role_ids = [r["role_id"] for r in resp.json()]
                    assert "saas_test_role_a_concur" in role_ids
                    assert "saas_test_role_b_concur" not in role_ids
                    await anyio.sleep(0.01)
                    
            async def tenant_b_task():
                # Perform 15 rapid read checks on Tenant B
                for _ in range(15):
                    resp = await client.get("/api/v1/roles", headers=headers_b)
                    assert resp.status_code == 200
                    role_ids = [r["role_id"] for r in resp.json()]
                    assert "saas_test_role_b_concur" in role_ids
                    assert "saas_test_role_a_concur" not in role_ids
                    await anyio.sleep(0.01)
            
            # Run concurrently
            async with anyio.create_task_group() as tg:
                tg.start_soon(tenant_a_task)
                tg.start_soon(tenant_b_task)
                tg.start_soon(tenant_a_task)
                tg.start_soon(tenant_b_task)
