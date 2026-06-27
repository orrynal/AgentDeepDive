import pytest
import httpx
from unittest.mock import patch, AsyncMock, MagicMock
from tenacity import RetryError

from src.api.routes.skills import (
    parse_markdown_skill,
    async_parse_markdown_skill,
    http_get_with_retry,
    is_retryable_exception
)

def test_parse_markdown_skill_standard_frontmatter():
    markdown_content = """---
skill_id: test-skill-123
name: Test Skill Name
version: 2.1.0
description: A wonderful test skill
tags:
  - testing
  - unit
trigger_patterns:
  - run test
  - execute unit test
required_tools:
  - python_executor
---
# Welcome to Test Skill
This is the system prompt body.
"""
    result = parse_markdown_skill(markdown_content)
    assert result["skill_id"] == "test-skill-123"
    assert result["name"] == "Test Skill Name"
    assert result["version"] == "2.1.0"
    assert result["description"] == "A wonderful test skill"
    assert result["tags"] == ["testing", "unit"]
    assert result["trigger_patterns"] == ["run test", "execute unit test"]
    assert result["required_tools"] == ["python_executor"]
    assert "This is the system prompt body." in result["system_prompt"]

def test_parse_markdown_skill_heuristic_regex():
    markdown_content = """
# Name: Heuristic Skill
# ID: heuristic-skill-id
# Description: Heuristic description check
# Version: 1.5.0

Here is some body text.
"""
    result = parse_markdown_skill(markdown_content)
    assert result["name"] == "Heuristic Skill"
    assert result["skill_id"] == "heuristic-skill-id"
    assert result["description"] == "Heuristic description check"
    assert result["version"] == "1.5.0"
    assert "Here is some body text." in result["system_prompt"]

def test_parse_markdown_skill_absolute_fallbacks():
    markdown_content = "Just some text without frontmatter or headings."
    result = parse_markdown_skill(markdown_content)
    # Since parse_markdown_skill is synchronous, it returns None/empty for missing fields
    # and leaves absolute fallbacks to async_parse_markdown_skill
    assert result["skill_id"] is None
    assert result["name"] is None
    assert result["version"] is None

def test_parse_markdown_skill_non_standard_headings():
    markdown_content = """
# Skill Name: Non-Standard Skill Name
# ID: non-standard-skill-id

## Description:
This is a test description under a heading block.

## Trigger Patterns
- trigger pattern one
* trigger pattern two

### Required Tools:
* tool_one
* tool_two
* tool_three
"""
    result = parse_markdown_skill(markdown_content)
    assert result["name"] == "Non-Standard Skill Name"
    assert result["skill_id"] == "non-standard-skill-id"
    assert "This is a test description under a heading block." in result["description"]
    assert result["trigger_patterns"] == ["trigger pattern one", "trigger pattern two"]
    assert result["required_tools"] == ["tool_one", "tool_two", "tool_three"]

@pytest.mark.asyncio
async def test_async_parse_markdown_skill_no_llm_fallback():
    markdown_content = """---
skill_id: direct-id
name: Direct Name
---
Prompt body
"""
    # Should complete without calling litellm
    with patch("litellm.acompletion") as mock_completion:
        result = await async_parse_markdown_skill(markdown_content)
        mock_completion.assert_not_called()
        assert result["skill_id"] == "direct-id"
        assert result["name"] == "Direct Name"

@pytest.mark.asyncio
async def test_async_parse_markdown_skill_llm_fallback_success():
    markdown_content = "Only system prompt body for extraction."
    
    mock_choice = AsyncMock()
    mock_choice.message.content = '{"skill_id": "llm-extracted-id", "name": "LLM Extracted", "description": "Extracted via LLM", "version": "1.2.3", "tags": ["extracted"], "trigger_patterns": ["trigger"], "required_tools": ["tool"]}'
    mock_response = AsyncMock()
    mock_response.choices = [mock_choice]
    
    with patch("litellm.acompletion", return_value=mock_response) as mock_completion:
        result = await async_parse_markdown_skill(markdown_content)
        mock_completion.assert_called_once()
        assert result["skill_id"] == "llm-extracted-id"
        assert result["name"] == "LLM Extracted"
        assert result["description"] == "Extracted via LLM"
        assert result["version"] == "1.2.3"
        assert result["tags"] == ["extracted"]
        assert result["trigger_patterns"] == ["trigger"]
        assert result["required_tools"] == ["tool"]

@pytest.mark.asyncio
async def test_async_parse_markdown_skill_llm_fallback_failure():
    markdown_content = "Body without any identifiers."
    
    with patch("litellm.acompletion", side_effect=Exception("LLM offline")) as mock_completion:
        result = await async_parse_markdown_skill(markdown_content)
        mock_completion.assert_called_once()
        # Fallback to absolute values
        assert result["skill_id"] == "unknown-skill"
        assert result["name"] == "unknown-skill"

@pytest.mark.asyncio
async def test_http_get_with_retry_success():
    mock_client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_client.get.return_value = mock_response
    
    res = await http_get_with_retry(mock_client, "https://skills.sh/test")
    assert res == mock_response
    assert mock_client.get.call_count == 1

@pytest.mark.asyncio
async def test_http_get_with_retry_recoverable_failure():
    mock_client = AsyncMock()
    
    # First call raises RequestError, second call succeeds
    mock_response = MagicMock()
    mock_response.status_code = 200
    
    mock_client.get.side_effect = [
        httpx.RequestError("Temporary timeout"),
        mock_response
    ]
    
    # Use patch to speed up wait_exponential in tenacity during unit testing
    with patch("tenacity.nap.time.sleep", return_value=None):
        res = await http_get_with_retry(mock_client, "https://skills.sh/test")
        assert res == mock_response
        assert mock_client.get.call_count == 2

@pytest.mark.asyncio
async def test_http_get_with_retry_fatal_500_failure():
    mock_client = AsyncMock()
    
    # 500 internal server error on all attempts
    mock_response_500 = MagicMock()
    mock_response_500.status_code = 500
    mock_response_500.raise_for_status.side_effect = httpx.HTTPStatusError(
        message="500 Internal Server Error",
        request=MagicMock(),
        response=mock_response_500
    )
    mock_client.get.return_value = mock_response_500
    
    with patch("tenacity.nap.time.sleep", return_value=None):
        with pytest.raises(httpx.HTTPStatusError):
            await http_get_with_retry(mock_client, "https://skills.sh/test")
        # Should attempt 3 times (due to stop_after_attempt(3))
        assert mock_client.get.call_count == 3

@pytest.mark.asyncio
async def test_http_get_with_retry_non_retryable_404_failure():
    mock_client = AsyncMock()
    
    # 404 Not Found is not retryable
    mock_response_404 = MagicMock()
    mock_response_404.status_code = 404
    mock_response_404.raise_for_status.side_effect = httpx.HTTPStatusError(
        message="404 Not Found",
        request=MagicMock(),
        response=mock_response_404
    )
    mock_client.get.return_value = mock_response_404
    
    with patch("tenacity.nap.time.sleep", return_value=None):
        with pytest.raises(httpx.HTTPStatusError):
            await http_get_with_retry(mock_client, "https://skills.sh/test")
        # Should raise immediately on 404 without retrying
        assert mock_client.get.call_count == 1

@pytest.mark.asyncio
async def test_async_parse_markdown_skill_normalization():
    markdown_content = """---
skill_id: " My Extremely   Messy   ID !! "
name: Normalizer Test
version: v2.3.4
tags: "tag-a, tag-b"
trigger_patterns:
  - "  pattern-one  "
  - "`pattern-two`"
required_tools: null
---
Some body text
"""
    result = await async_parse_markdown_skill(markdown_content)
    assert result["skill_id"] == "my-extremely-messy-id"
    assert result["version"] == "2.3.4"
    assert result["tags"] == ["tag-a", "tag-b"]
    assert result["trigger_patterns"] == ["pattern-one", "pattern-two"]
    assert result["required_tools"] == []


def test_load_cached_skills_empty(tmp_path):
    from src.api.routes.skills import load_cached_skills
    res = load_cached_skills(tmp_path / "nonexistent")
    assert res == []


def test_load_cached_skills_success(tmp_path):
    from src.api.routes.skills import load_cached_skills
    import yaml
    
    # Create a dummy yaml skill
    dummy_skill = {
        "skill_id": "cached-test-v1",
        "name": "Cached Test Skill",
        "version": "1.0.0",
        "description": "Just cached",
        "tags": ["cache"],
        "trigger_patterns": ["test cache"],
        "required_tools": []
    }
    
    cache_file = tmp_path / "cached-test-v1.yaml"
    with open(cache_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(dummy_skill, f)
        
    res = load_cached_skills(tmp_path)
    assert len(res) == 1
    assert res[0]["skill_id"] == "cached-test-v1"
    assert res[0]["name"] == "Cached Test Skill"


@pytest.mark.asyncio
async def test_install_skill_cache_fallback(tmp_path):
    from src.api.routes.skills import install_skill
    from src.api.schemas.skill import SkillInstallRequest
    import yaml
    import hashlib
    
    # 1. Setup mock service
    mock_svc = AsyncMock()
    mock_svc.get_by_id.return_value = None
    mock_svc.create.side_effect = lambda data: data
    
    # 2. Setup mock request
    req = SkillInstallRequest(
        skill_name_or_url="https://skills.sh/packages/offline-test-skill.yaml",
        scope="global",
        workspace_path=None
    )
    
    # 3. Setup tmp cache directory
    mock_skills_dir = tmp_path / "skills"
    mock_skills_dir.mkdir(parents=True, exist_ok=True)
    mock_cache_dir = mock_skills_dir / ".cache"
    mock_cache_dir.mkdir(parents=True, exist_ok=True)
    
    dummy_yaml = """
skill_id: offline-test-skill
name: Offline Test Skill
version: 1.0.0
description: Cached offline fallback
system_prompt: System prompt offline
"""
    # Write to URL-hash cache file
    url_hash = hashlib.sha256(req.skill_name_or_url.encode("utf-8")).hexdigest()
    with open(mock_cache_dir / f"{url_hash}.yaml", "w", encoding="utf-8") as f:
        f.write(dummy_yaml)
        
    class MockPath:
        def __init__(self, *args, **kwargs):
            pass
        @property
        def parent(self):
            return self
        def __truediv__(self, other):
            if other == "skills":
                return mock_skills_dir
            return mock_skills_dir / other

    with patch("src.api.routes.skills.Path", MockPath):
        # Call install_skill
        res = await install_skill(req, svc=mock_svc)
        
        # Verify it installed using the cached data
        assert res["skill_id"] == "offline-test-skill"
        assert res["name"] == "Offline Test Skill"
        assert res["version"] == "1.0.0"
        
        # Verify it saved a name-based cache file
        name_cached_file = mock_cache_dir / "offline-test-skill.yaml"
        assert name_cached_file.exists()

