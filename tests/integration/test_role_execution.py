import pytest
from src.core.agent.executor import AgentExecutor

@pytest.mark.asyncio
async def test_role_execution_permissions_and_prompts():
    role = {
        "role_id": "test_architect",
        "name": "Test Architect",
        "system_prompt_prefix": "You are a software architect.",
        "allowed_skills": ["code_analysis"],
        "default_model": "ollama/qwen3.5:2b",
        "max_token_budget": 20000
    }
    
    allowed_skill = {
        "skill_id": "code_analysis",
        "name": "Code Analysis",
        "tags": ["analysis"],
        "system_prompt": "Analyze the complexity."
    }
    
    disallowed_skill = {
        "skill_id": "code_refactor",
        "name": "Code Refactor",
        "tags": ["refactor"],
        "system_prompt": "Refactor the logic."
    }
    
    executor = AgentExecutor()
    
    # 1. Verify that disallowed skill is blocked immediately by permission gates
    res_disallowed = await executor.execute(
        task_id="task-123",
        task_description="Refactor this file",
        skill=disallowed_skill,
        role=role
    )
    assert res_disallowed["status"] == "failed"
    assert "Security Alert: Role 'Test Architect' is not authorized to execute Skill 'code_refactor'" in res_disallowed["error"]

    # 2. Verify prompt building logic combines prefix + skill prompt + context
    prompt = executor._build_system_prompt(allowed_skill, "module code context", role)
    assert "You are a software architect." in prompt
    assert "Analyze the complexity." in prompt
    assert "module code context" in prompt
