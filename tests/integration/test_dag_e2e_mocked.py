import os
import pytest
from unittest.mock import patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.config import settings
from src.core.orchestrator.models import DAGDefinition, DAGNode
from src.core.orchestrator.dag_engine import DAGEngine
from src.core.skill.models import Base as SkillBase
from src.core.role.models import Base as RoleBase
from src.core.skill.service import SkillService

class MockToolCallFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments

class MockToolCall:
    def __init__(self, id: str, name: str, arguments: str):
        self.id = id
        self.type = "function"
        self.function = MockToolCallFunction(name, arguments)

class MockChoiceMessage:
    def __init__(self, content: str | None = None, tool_calls: list = None):
        self.content = content
        self.tool_calls = tool_calls
    
    def model_dump(self):
        dumped = {"role": "assistant"}
        if self.content is not None:
            dumped["content"] = self.content
        if self.tool_calls is not None:
            dumped["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                }
                for tc in self.tool_calls
            ]
        return dumped

class MockChoice:
    def __init__(self, content: str | None = None, tool_calls: list = None):
        self.message = MockChoiceMessage(content, tool_calls)

class MockUsage:
    def __init__(self):
        self.prompt_tokens = 5
        self.completion_tokens = 10
        self.total_tokens = 15

class MockResponse:
    def __init__(self, content: str | None = None, tool_calls: list = None):
        self.choices = [MockChoice(content, tool_calls)]
        self.usage = MockUsage()

@pytest.mark.asyncio
async def test_dag_e2e_execution_with_llm_mocking():
    # 1. Setup workspace paths and test files
    workspace = settings.resolved_workspace_path
    input_file_path = os.path.join(workspace, "test_e2e_input.txt")
    output_file_path = os.path.join(workspace, "test_e2e_output.txt")
    
    # Write input file
    with open(input_file_path, "w", encoding="utf-8") as f:
        f.write("Hello from E2E integration test!")
        
    # Ensure output file doesn't exist initially
    if os.path.exists(output_file_path):
        os.remove(output_file_path)

    # 2. Database and Skill Setup
    from src.core.auth.models import TenantModel, UserModel
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(SkillBase.metadata.create_all)
        await conn.run_sync(RoleBase.metadata.create_all)

    async with async_session() as session:
        skill_svc = SkillService(session)
        # Clear existing test skills to prevent duplicate keys
        from sqlalchemy import text
        await session.execute(text("DELETE FROM skills WHERE skill_id IN ('test_e2e_reader', 'test_e2e_writer')"))
        await session.commit()
        
        await skill_svc.create({
            "skill_id": "test_e2e_reader",
            "name": "E2E File Reader",
            "tags": ["analysis"],
            "system_prompt": "You read files.",
            "required_tools": ["file_read"]
        })
        await skill_svc.create({
            "skill_id": "test_e2e_writer",
            "name": "E2E File Writer",
            "tags": ["documentation"],
            "system_prompt": "You write files.",
            "required_tools": ["file_write"]
        })
        await session.commit()

    # 3. Define the DAG
    dag = DAGDefinition(
        name="E2E Mocked Exec DAG",
        workspace_path=workspace,
        project_name="e2e_test",
        nodes=[
            DAGNode(
                node_id="node-read",
                name="Read Node",
                skill_id="test_e2e_reader",
                description="Read input text file",
            ),
            DAGNode(
                node_id="node-write",
                name="Write Node",
                skill_id="test_e2e_writer",
                description="Write output text file",
                dependencies=["node-read"]
            )
        ]
    )

    # 4. State tracking for litellm mock calls
    read_call_count = 0
    write_call_count = 0

    async def mock_acompletion(*args, **kwargs):
        nonlocal read_call_count, write_call_count
        messages = kwargs.get("messages", [])
        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        
        if "You read files." in system_msg:
            read_call_count += 1
            if read_call_count == 1:
                # Return tool call to read input file
                tc = MockToolCall(
                    id="call_read_1",
                    name="file_read",
                    arguments=f'{{"path": "{input_file_path}"}}'
                )
                return MockResponse(tool_calls=[tc])
            else:
                # Return final response
                return MockResponse(content="Successfully read the file contents.")
                
        elif "You write files." in system_msg:
            write_call_count += 1
            if write_call_count == 1:
                # Return tool call to write output file
                tc = MockToolCall(
                    id="call_write_1",
                    name="file_write",
                    arguments=f'{{"path": "{output_file_path}", "content": "Hello from E2E integration test!"}}'
                )
                return MockResponse(tool_calls=[tc])
            else:
                # Return final response
                return MockResponse(content="Successfully wrote the file contents.")
        
        # Fallback
        return MockResponse(content="Fallback answer.")

    # Disable Contract Net to make execution direct & deterministic
    with patch("litellm.acompletion", mock_acompletion), \
         patch("src.config.settings.contract_net_enabled", False):
        
        async with async_session() as session:
            skill_svc = SkillService(session)
            dag_engine = DAGEngine(skill_svc)
            
            result_dag = await dag_engine.execute(dag)
            await session.commit()
            
            # Print node errors if any failed
            for n in result_dag.nodes:
                if n.error:
                    print(f"Node {n.node_id} failed with error: {n.error}")

            # 5. Assertions
            assert result_dag.status == "completed"
            assert result_dag.get_node("node-read").color == "green"
            assert result_dag.get_node("node-write").color == "green"
            
            # Assert calls count
            assert read_call_count >= 2
            assert write_call_count >= 2

            # Assert output file actually exists and contains the correct content
            assert os.path.exists(output_file_path)
            with open(output_file_path, "r", encoding="utf-8") as f:
                content = f.read()
            assert content == "Hello from E2E integration test!"

    # Cleanup test files
    if os.path.exists(input_file_path):
        os.remove(input_file_path)
    if os.path.exists(output_file_path):
        os.remove(output_file_path)

    await engine.dispose()
