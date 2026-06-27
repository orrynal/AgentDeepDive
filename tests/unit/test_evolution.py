import os
import json
import tempfile
import yaml
import pytest
from src.evolution.diagnostics import DiagnosticsEngine
from src.evolution.evaluator import Evaluator
from src.evolution.optimizer import SkillOptimizer, find_skill_file
import litellm

def test_diagnostics_engine():
    engine = DiagnosticsEngine()

    # 1. Token limit
    res = engine.diagnose("context token budget exceeded", 1000, 1000, None)
    assert res["failure_category"] == "TOKEN_EXCEEDED"

    # 2. Tool error
    res = engine.diagnose("tool file_read failed due to permission", 100, 1000, None)
    assert res["failure_category"] == "TOOL_ERROR"

    # 3. JSON Schema violation
    eval_json_fail = {"json_valid": False, "rule_score": 0.7, "score": 0.8}
    res = engine.diagnose(None, 100, 1000, eval_json_fail)
    assert res["failure_category"] == "JSON_SCHEMA_VIOLATION"

    # 4. LLM Quality failure
    eval_quality_fail = {"json_valid": True, "rule_score": 1.0, "score": 0.5}
    res = engine.diagnose(None, 100, 1000, eval_quality_fail)
    assert res["failure_category"] == "LLM_QUALITY_FAILURE"

    # 5. Bad routing
    res = engine.diagnose("No suitable skill found", 100, 1000, None)
    assert res["failure_category"] == "BAD_ROUTING"

    # 6. Default fallback
    res = engine.diagnose(None, 100, 1000, None)
    assert res["failure_category"] == "UNKNOWN"

@pytest.mark.anyio
async def test_evaluator_evaluate_trace(monkeypatch):
    evaluator = Evaluator()

    # Mock litellm.acompletion response
    class MockChoices:
        def __init__(self, content):
            class Message:
                def __init__(self, content):
                    self.content = content
            self.message = Message(content)

    class MockResponse:
        def __init__(self, content):
            self.choices = [MockChoices(content)]

    # We need to mock acompletion to return JSON strings for Judge A and Judge B
    call_count = 0
    async def mock_acompletion(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Judge A
            return MockResponse('{"score": 9.0, "rationale": "Great logic"}')
        else:
            # Judge B
            return MockResponse('{"score": 7.0, "rationale": "Clear format"}')

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    # 1. Output is valid JSON, no errors
    result = await evaluator.evaluate_trace(
        task_description="Return status in JSON",
        skill_name="json_reporter",
        trace_steps=[],
        agent_output='{"status": "ok"}'
    )

    assert result["json_valid"] is True
    assert result["has_tool_errors"] is False
    assert result["has_security_violations"] is False
    assert result["score"] == pytest.approx(0.824)  # (10.0*0.2 + 7.8*0.8) / 10.0 = 0.824

    # 2. Output has OPA violation in trace_steps
    result_opa = await evaluator.evaluate_trace(
        task_description="Return status in JSON",
        skill_name="json_reporter",
        trace_steps=[{"output_summary": "OPA policy blocked execution of dangerous command"}],
        agent_output='{"status": "ok"}'
    )
    assert result_opa["has_security_violations"] is True
    # rule_score = 10 - 6 = 4. judge_consensus = 7. (since call_count > 1 returns 7.0 for both)
    # final_score = 4 * 0.2 + 7 * 0.8 = 6.4. normalized_score = 0.64.
    assert result_opa["score"] == pytest.approx(0.64)

    # 3. High discrepancy between Judge A and Judge B triggers Judge C
    call_count_c = 0
    async def mock_acompletion_discrepancy(*args, **kwargs):
        nonlocal call_count_c
        call_count_c += 1
        if call_count_c == 1:
            # Judge A (Logic)
            return MockResponse('{"score": 9.0, "rationale": "Great logic"}')
        elif call_count_c == 2:
            # Judge B (Structure - very low)
            return MockResponse('{"score": 3.0, "rationale": "Terrible format"}')
        else:
            # Judge C (Tie-breaker)
            return MockResponse('{"score": 6.0, "rationale": "Decent balance"}')

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion_discrepancy)
    result_discrepancy = await evaluator.evaluate_trace(
        task_description="Return status in JSON",
        skill_name="json_reporter",
        trace_steps=[],
        agent_output='{"status": "ok"}'
    )
    # Judge C was called, and final score is based on Judge C score of 6.0
    # rule_score = 10.
    # final_score = 10 * 0.2 + 6.0 * 0.8 = 6.8. normalized_score = 0.68
    assert result_discrepancy["judge_c_score"] == 0.6
    assert result_discrepancy["score"] == pytest.approx(0.68)

@pytest.mark.anyio
async def test_skill_optimizer(monkeypatch):
    # Setup temporary directory and mock skill YAML
    with tempfile.TemporaryDirectory() as tmpdir:
        skill_data = {
            "skill_id": "test_skill",
            "name": "Test Skill",
            "version": "1.2.3",
            "system_prompt": "Do test work."
        }
        skill_file_path = os.path.join(tmpdir, "test_skill.yaml")
        with open(skill_file_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(skill_data, f)

        # Mock litellm.acompletion to return new prompt
        class MockChoices:
            def __init__(self, content):
                class Message:
                    def __init__(self, content):
                        self.content = content
                self.message = Message(content)

        class MockResponse:
            def __init__(self, content):
                self.choices = [MockChoices(content)]

        async def mock_acompletion(*args, **kwargs):
            return MockResponse("```xml\nDo test work better.\n```")

        monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

        optimizer = SkillOptimizer()
        success = await optimizer.optimize_skill(
            skill_id="test_skill",
            diagnostic={"failure_category": "TOOL_ERROR", "reason": "failed step", "recommendation": "fix"},
            skills_dir=tmpdir
        )

        assert success is True

        # Read back optimized YAML
        with open(skill_file_path, "r", encoding="utf-8") as f:
            updated_data = yaml.safe_load(f)

        assert updated_data["system_prompt"] == "Do test work better."
        assert updated_data["version"] == "1.2.4"  # Version bumped
