"""Skill Registry API endpoints — backed by PostgreSQL."""

from pathlib import Path
import yaml
import httpx
import structlog
import urllib.parse
import json
import re
import hashlib
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from src.api.schemas.skill import SkillCreate, SkillResponse, SkillUpdate, SkillInstallRequest, SkillPreviewRequest, SkillPreviewResponse
from src.core.skill.service import SkillService
from src.database import get_db
from src.core.auth.security import get_current_user, RoleRequired
from src.core.auth.models import UserModel

logger = structlog.get_logger()

router = APIRouter()

def is_retryable_exception(exception: Exception) -> bool:
    if isinstance(exception, httpx.RequestError):
        return True
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code >= 500
    return False

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception(is_retryable_exception),
    reraise=True
)
async def http_get_with_retry(client: httpx.AsyncClient, url: str, timeout: float = 8.0, **kwargs):
    res = await client.get(url, timeout=timeout, **kwargs)
    res.raise_for_status()
    return res


def _get_service(
    session: AsyncSession = Depends(get_db),
    user: UserModel = Depends(get_current_user),
) -> SkillService:
    return SkillService(session, tenant_id=user.tenant_id)


REMOTE_MARKET_SKILLS = [
    {
        "skill_id": "react-generator-v1",
        "name": "React Component Generator",
        "version": "1.2.0",
        "description": "Generate modern React components with CSS styling and interactive hooks based on specifications.",
        "tags": ["react", "frontend", "code-gen"],
        "trigger_patterns": ["react component", "generate react"],
        "required_tools": [],
        "risk_level": "low",
        "approval_required": False,
        "url": "https://skills.sh/packages/react-generator-v1.yaml"
    },
    {
        "skill_id": "db-connector-v1",
        "name": "SaaS Database Connector",
        "version": "1.0.5",
        "description": "One-click connection and query generation for SaaS databases (Postgres, MySQL, Snowflake).",
        "tags": ["database", "sql", "saas"],
        "trigger_patterns": ["connect database", "query db"],
        "required_tools": ["db_query_tool"],
        "risk_level": "medium",
        "approval_required": True,
        "url": "https://skills.sh/packages/db-connector-v1.yaml"
    },
    {
        "skill_id": "web-searcher-v1",
        "name": "网络搜索与信息检索专家",
        "version": "1.0.0",
        "description": "通过互联网搜索引擎检索最新的实时信息、开发资源 or 外部文档",
        "tags": ["web", "search", "network", "query"],
        "trigger_patterns": ["联网搜索", "查找资料", "web search"],
        "required_tools": ["web_search_ddg"],
        "risk_level": "low",
        "approval_required": False,
        "url": "https://skills.sh/packages/web-searcher-v1.yaml"
    },
    {
        "skill_id": "web-reader-v1",
        "name": "网页正文提取",
        "version": "1.0.0",
        "description": "输入指定URL，下载网页内容并使用Jina Reader提取出Markdown格式的干净文本正文",
        "tags": ["web", "read", "jina", "extract"],
        "trigger_patterns": ["阅读网页", "网页解析", "read url"],
        "required_tools": ["web_read_jina"],
        "risk_level": "low",
        "approval_required": False,
        "url": "https://skills.sh/packages/web-reader-v1.yaml"
    }
]

def get_mock_skill_yaml(skill_id: str) -> str | None:
    if skill_id == "react-generator-v1":
        return """
skill_id: react-generator-v1
name: React Component Generator
version: 1.2.0
description: Generate modern React components with CSS styling and interactive hooks based on specifications.
tags:
  - react
  - frontend
  - code-gen
trigger_patterns:
  - react component
  - generate react
context_budget: 16000
required_tools: []
input_schema:
  type: object
  properties:
    spec:
      type: string
      description: Component specifications
output_schema:
  type: object
  properties:
    code:
      type: string
system_prompt: |
  你是一个熟练的 React 组件生成专家。根据用户的需求描述，生成符合规范的、设计优秀的 React 页面或组件代码。
risk_level: low
approval_required: false
"""
    elif skill_id == "db-connector-v1":
        return """
skill_id: db-connector-v1
name: SaaS Database Connector
version: 1.0.5
description: One-click connection and query generation for SaaS databases (Postgres, MySQL, Snowflake).
tags:
  - database
  - sql
  - saas
trigger_patterns:
  - connect database
  - query db
context_budget: 12000
required_tools:
  - db_query_tool
input_schema:
  type: object
  properties:
    connection_string:
      type: string
    query:
      type: string
output_schema:
  type: object
  properties:
    rows:
      type: array
system_prompt: |
  你是一个专业的 SaaS 数据库连接与查询生成专家。使用 db_query_tool 工具来执行数据库操作，并整理出结构化的查询报告。
risk_level: medium
approval_required: true
"""
    elif skill_id == "web-searcher-v1":
        return """
skill_id: web-searcher-v1
name: 网络搜索与信息检索专家
version: 1.0.0
description: 通过互联网搜索引擎检索最新的实时信息、开发资源或外部文档
tags:
  - web
  - search
  - network
  - query
trigger_patterns:
  - 联网搜索
  - 查找资料
  - web search
context_budget: 12000
required_tools:
  - web_search_ddg
input_schema:
  type: object
  properties:
    query:
      type: string
output_schema:
  type: object
  properties:
    results:
      type: string
system_prompt: |
  你是一个优秀的网络搜索与信息检索专家。根据用户输入的内容，使用 web_search_ddg 工具检索互联网上的相关网页。
risk_level: low
approval_required: false
"""
    elif skill_id == "web-reader-v1":
        return """
skill_id: web-reader-v1
name: 网页正文提取
version: 1.0.0
description: 输入指定URL，下载网页内容并使用Jina Reader提取出Markdown格式的干净文本正文
tags:
  - web
  - read
  - jina
  - extract
trigger_patterns:
  - 阅读网页
  - 网页解析
  - read url
context_budget: 16000
required_tools:
  - web_read_jina
input_schema:
  type: object
  properties:
    url:
      type: string
output_schema:
  type: object
  properties:
    content:
      type: string
system_prompt: |
  你是一个网页正文提取专家。根据指定的 URL 路径，使用 web_read_jina 抓取网页并提取出清晰无噪声的 Markdown 正文。
risk_level: low
approval_required: false
"""
    return None


def load_cached_skills(cache_dir: Path) -> list[dict]:
    cached_list = []
    if not cache_dir.exists():
        return cached_list
    for item in cache_dir.iterdir():
        if item.is_file() and item.suffix in (".yaml", ".yml", ".md"):
            try:
                with open(item, "r", encoding="utf-8") as f:
                    content = f.read()
                if item.suffix == ".md":
                    data = parse_markdown_skill(content)
                else:
                    data = yaml.safe_load(content)
                if data and isinstance(data, dict):
                    skill_id = data.get("skill_id") or data.get("skillId")
                    name = data.get("name")
                    if skill_id and name:
                        cached_list.append({
                            "skill_id": skill_id,
                            "name": name,
                            "version": data.get("version", "1.0.0"),
                            "description": data.get("description", ""),
                            "tags": data.get("tags", []),
                            "trigger_patterns": data.get("trigger_patterns", []),
                            "required_tools": data.get("required_tools", []),
                            "risk_level": data.get("risk_level", "low"),
                            "approval_required": data.get("approval_required", False),
                            "url": data.get("url") or f"file://{item.absolute()}"
                        })
            except Exception as e:
                logger.warning("Failed to load cached skill file", path=str(item), error=str(e))
    return cached_list


def normalize_and_correct_skill_metadata(parsed: dict, is_async: bool = False) -> dict:
    # 1. Normalize skill_id (must be lowercase alphanumeric + hyphens/underscores)
    if parsed.get("skill_id"):
        sid = str(parsed["skill_id"]).strip().lower()
        sid = re.sub(r'[^a-zA-Z0-9_-]', '-', sid)
        sid = re.sub(r'-+', '-', sid)  # collapse multiple hyphens
        parsed["skill_id"] = sid.strip("-")
    elif is_async:
        # absolute fallback if missing
        if parsed.get("name"):
            sid = str(parsed["name"]).strip().lower()
            sid = re.sub(r'[^a-zA-Z0-9_-]', '-', sid)
            sid = re.sub(r'-+', '-', sid)
            parsed["skill_id"] = sid.strip("-")
        else:
            parsed["skill_id"] = "unknown-skill"

    # Ensure name is set
    if is_async and not parsed.get("name"):
        parsed["name"] = parsed["skill_id"]

    # 2. Normalize and default version
    if parsed.get("version"):
        v_clean = str(parsed["version"]).strip().lower()
        if v_clean.startswith("v"):
            v_clean = v_clean[1:].strip()
        parsed["version"] = v_clean
    elif is_async:
        parsed["version"] = "1.0.0"

    # 3. Clean list fields
    for list_field in ["tags", "trigger_patterns", "required_tools"]:
        val = parsed.get(list_field)
        if val is None:
            parsed[list_field] = []
        elif isinstance(val, str):
            parsed[list_field] = [x.strip("`'\" \t") for x in val.split(",") if x.strip()]
        elif isinstance(val, list):
            cleaned_list = []
            for item in val:
                if item is not None:
                    cleaned_list.append(str(item).strip("`'\" \t"))
            parsed[list_field] = cleaned_list
        else:
            parsed[list_field] = []
            
    return parsed


def parse_markdown_skill(contents: str) -> dict:
    import yaml
    frontmatter = {}
    body = contents
    stripped = contents.strip()
    
    # 1. Standard YAML Frontmatter Parsing (Tolerating different whitespace/newlines)
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', stripped, re.DOTALL)
    if frontmatter_match:
        try:
            frontmatter = yaml.safe_load(frontmatter_match.group(1)) or {}
            body = frontmatter_match.group(2).strip()
        except Exception:
            pass
    elif stripped.startswith("---"):
        parts = stripped.split("---")
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
                body = "---".join(parts[2:]).strip()
            except Exception:
                pass
                
    # Extract properties from frontmatter
    skill_id = frontmatter.get("skillId") or frontmatter.get("skill_id") or frontmatter.get("name")
    name = frontmatter.get("name")
    description = frontmatter.get("description")
    version = frontmatter.get("version")
    tags = frontmatter.get("tags") or []
    trigger_patterns = frontmatter.get("trigger_patterns") or []
    required_tools = frontmatter.get("required_tools") or []

    # FSM/Section-based parser for non-YAML markdown sections
    lines = stripped.splitlines()
    current_section = None
    section_content_lines = []
    sections = {}
    
    for line in lines:
        stripped_line = line.strip()
        
        # Check if line is a header: e.g., "# Header", "## Header", "**Header**", "__Header__"
        h_clean = None
        if stripped_line.startswith(("#", "**", "__")):
            h_clean = re.sub(r'^(#{1,6}\s*|\*\*|__)', '', stripped_line)
            h_clean = re.sub(r'(\*\*|__|:)$', '', h_clean).strip()
            
        if h_clean:
            # Save previous section content
            if current_section:
                sections[current_section] = section_content_lines
            # Start new section
            header_text = h_clean
            current_section = header_text.lower()
            section_content_lines = []
            
            # Check for inline content in header like "Tags: analysis, web"
            inline_match = re.match(r'^([^:]+):\s*(.+)$', header_text)
            if inline_match:
                header_name = inline_match.group(1).strip().lower()
                header_val = inline_match.group(2).strip()
                if header_name not in sections:
                    sections[header_name] = []
                sections[header_name].append(header_val)
        else:
            if current_section:
                section_content_lines.append(stripped_line)
                
    # Save the last section
    if current_section:
        sections[current_section] = section_content_lines

    # Helper function to find a section by alias names
    def get_section_lines(aliases: list[str]) -> list[str]:
        for alias in aliases:
            if alias in sections:
                return sections[alias]
            # Check for partial match/starts with
            for key, val in sections.items():
                if key.startswith(alias):
                    return val
        return []

    # Helper to parse list items from lines (bullets, dashes, stars, or comma-separated)
    def parse_list_items(lines: list[str]) -> list[str]:
        items = []
        for l in lines:
            if not l:
                continue
            # Remove markdown list bullets: -, *, +, 1., etc.
            l_clean = re.sub(r'^[-*+]\s+', '', l)
            l_clean = re.sub(r'^\d+\.\s+', '', l_clean)
            # Strip backticks, quotes, and whitespace
            l_clean = l_clean.strip("`'\" \t")
            if l_clean:
                # Check if it contains comma-separated items on a single line
                if "," in l_clean and not l_clean.startswith("["):
                    items.extend([x.strip("`'\" \t") for x in l_clean.split(",") if x.strip()])
                else:
                    items.append(l_clean)
        return items

    # Parse individual fields if not set
    # 1. Name
    if not name:
        name_lines = get_section_lines(["name", "skill name", "skill_name"])
        if name_lines:
            name = name_lines[0].strip("`'\" \t")
        else:
            # Regex fallback
            match = re.search(r'(?:^|\n)#+\s*(?:Skill\s*Name|Name):\s*(.*)', stripped, re.IGNORECASE)
            if match:
                name = match.group(1).strip()

    # 2. Skill ID
    if not skill_id:
        id_lines = get_section_lines(["id", "skill id", "skill_id", "skillid"])
        if id_lines:
            skill_id = id_lines[0].strip("`'\" \t")
        else:
            # Regex fallback
            match = re.search(r'(?:^|\n)#+\s*(?:Skill\s*ID|ID):\s*(.*)', stripped, re.IGNORECASE)
            if match:
                skill_id = match.group(1).strip()
            elif name:
                skill_id = re.sub(r'[^a-zA-Z0-9_-]', '-', name.lower())

    # 3. Description
    if not description:
        desc_lines = get_section_lines(["description", "desc", "about"])
        if desc_lines:
            description = "\n".join(desc_lines).strip()
        else:
            # Regex fallback
            match = re.search(r'(?:^|\n)#+\s*(?:Description):\s*(.*)', stripped, re.IGNORECASE)
            if match:
                description = match.group(1).strip()

    # 4. Version
    if not version:
        ver_lines = get_section_lines(["version", "ver"])
        if ver_lines:
            version = ver_lines[0].strip("`'\" \t")
        else:
            # Regex fallback
            match = re.search(r'(?:^|\n)#+\s*(?:Version):\s*(.*)', stripped, re.IGNORECASE)
            if match:
                version = match.group(1).strip()

    # 5. Tags
    if not tags:
        tag_lines = get_section_lines(["tags", "tag"])
        tags = parse_list_items(tag_lines)

    # 6. Trigger Patterns
    if not trigger_patterns:
        trigger_lines = get_section_lines(["trigger patterns", "trigger_patterns", "triggers", "trigger"])
        trigger_patterns = parse_list_items(trigger_lines)

    # 7. Required Tools
    if not required_tools:
        tool_lines = get_section_lines(["required tools", "required_tools", "tools", "required tool"])
        required_tools = parse_list_items(tool_lines)

    # Inline regex fallback checks if list fields are still empty
    if not tags:
        match = re.search(r'(?:^|\n)#+\s*Tags:\s*(.*)', stripped, re.IGNORECASE)
        if match:
            tags = [x.strip("`'\" \t") for x in match.group(1).split(",") if x.strip()]
    if not trigger_patterns:
        match = re.search(r'(?:^|\n)#+\s*Trigger\s*Patterns:\s*(.*)', stripped, re.IGNORECASE)
        if match:
            trigger_patterns = [x.strip("`'\" \t") for x in match.group(1).split(",") if x.strip()]
    if not required_tools:
        match = re.search(r'(?:^|\n)#+\s*Required\s*Tools:\s*(.*)', stripped, re.IGNORECASE)
        if match:
            required_tools = [x.strip("`'\" \t") for x in match.group(1).split(",") if x.strip()]

    return normalize_and_correct_skill_metadata({
        "skill_id": skill_id,
        "name": name,
        "description": description,
        "version": version,
        "tags": tags,
        "trigger_patterns": trigger_patterns,
        "required_tools": required_tools,
        "system_prompt": body
    })


async def async_parse_markdown_skill(contents: str) -> dict:
    # First, run the synchronous parsing logic
    parsed = parse_markdown_skill(contents)
    
    # Check if we need LLM fallback to extract metadata
    has_id = parsed.get("skill_id") and parsed.get("skill_id") != "unknown-skill"
    has_name = bool(parsed.get("name"))
    has_prompt = bool(parsed.get("system_prompt") and len(parsed["system_prompt"].strip()) > 10)
    
    if has_id and has_name and has_prompt:
        return normalize_and_correct_skill_metadata(parsed, is_async=True)
        
    # Otherwise, attempt LLM fallback
    try:
        import litellm
        from src.config import settings
        
        prompt = f"""
Analyze the following Markdown content of an AI Agent Skill and extract its metadata.
Return a valid JSON object with the following fields:
- skill_id: a unique identifier for the skill (e.g., 'web-searcher-v1')
- name: a human-readable name for the skill (e.g., 'Web Search Specialist')
- description: a short description of what the skill does
- version: the version string (e.g., '1.0.0')
- tags: a list of string tags
- trigger_patterns: a list of string patterns that trigger this skill
- required_tools: a list of tools required by this skill

If some fields are not mentioned in the text, guess reasonable values based on the content.

Markdown Content:
---
{contents}
---

Ensure your response is ONLY the JSON block. Do not include markdown wraps or explanation.
"""
        if settings.agnes_api_key:
            model = settings.agnes_default_model or "agnes-2.0-flash"
        else:
            model = settings.default_model or "gpt-4o"
            
        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        raw_content = response.choices[0].message.content.strip()
        json_match = re.search(r'(\{.*\})', raw_content, re.DOTALL)
        if json_match:
            raw_content = json_match.group(1)
        llm_data = json.loads(raw_content)
        if isinstance(llm_data, dict):
            # Merge missing fields
            for key in ["skill_id", "name", "description", "version", "tags", "trigger_patterns", "required_tools"]:
                # If key is missing or is the default "unknown-skill", overwrite with LLM data
                current_val = parsed.get(key)
                if (not current_val or current_val == "unknown-skill" or current_val == []) and llm_data.get(key):
                    parsed[key] = llm_data[key]
    except Exception as e:
        logger.warning("Failed to extract skill metadata via LLM fallback", error=str(e))
        
    return normalize_and_correct_skill_metadata(parsed, is_async=True)


@router.get("/skills/market/search", response_model=list[dict])
async def search_market_skills(
    query: str | None = None,
):
    """Search or list skills available in the market (from local skills template registry + skills.sh index)."""
    skills_dir = Path(__file__).parent.parent.parent.parent / "skills"
    market_skills = []
    
    # 1. Load local market skills
    if skills_dir.exists():
        for item in skills_dir.iterdir():
            if item.is_dir() and not item.name.startswith(("_", "test_")):
                yaml_path = item / "skill.yaml"
                if yaml_path.exists():
                    try:
                        with open(yaml_path, "r", encoding="utf-8") as f:
                            data = yaml.safe_load(f)
                            if data and isinstance(data, dict):
                                skill_id = data.get("skill_id", item.name)
                                name = data.get("name", item.name)
                                description = data.get("description", "")
                                tags = data.get("tags", [])
                                version = data.get("version", "1.0.0")
                                
                                if query:
                                    q_lower = query.lower()
                                    in_name = q_lower in name.lower()
                                    in_desc = q_lower in description.lower()
                                    in_tags = any(q_lower in t.lower() for t in tags)
                                    in_id = q_lower in skill_id.lower()
                                    if not (in_name or in_desc or in_tags or in_id):
                                        continue
                                        
                                market_skills.append({
                                    "skill_id": skill_id,
                                    "name": name,
                                    "version": version,
                                    "description": description,
                                    "tags": tags,
                                    "trigger_patterns": data.get("trigger_patterns", []),
                                    "required_tools": data.get("required_tools", []),
                                    "risk_level": data.get("risk_level", "low"),
                                    "approval_required": data.get("approval_required", False),
                                    "url": f"https://skills.sh/packages/{skill_id}.yaml"
                                })
                    except Exception as e:
                        logger.error("Failed to parse market skill YAML", path=str(yaml_path), error=str(e))
                        
    # 1.5 Load cached skills from .cache
    cache_dir = skills_dir / ".cache"
    if cache_dir.exists():
        cached_skills = load_cached_skills(cache_dir)
        for s in cached_skills:
            skill_id = s["skill_id"]
            name = s["name"]
            description = s["description"]
            tags = s["tags"]
            
            if query:
                q_lower = query.lower()
                in_name = q_lower in name.lower()
                in_desc = q_lower in description.lower()
                in_tags = any(q_lower in t.lower() for t in tags)
                in_id = q_lower in skill_id.lower()
                if not (in_name or in_desc or in_tags or in_id):
                    continue
                    
            if any(local_s["skill_id"] == skill_id for local_s in market_skills):
                continue
                
            market_skills.append(s)
                        
    # 2. Fetch remote skills from skills.sh index
    remote_skills = []
    try:
        async with httpx.AsyncClient() as client:
            if query:
                quoted_query = urllib.parse.quote(query)
                url = f"https://skills.sh/api/search?q={quoted_query}"
            else:
                url = "https://skills.sh/api/skills/all-time/0"
                
            res = await http_get_with_retry(client, url, timeout=8.0)
            res_data = res.json()
            if isinstance(res_data, dict) and "skills" in res_data:
                remote_skills = res_data["skills"]
    except Exception as e:
        logger.warning("Failed to fetch remote skills from marketplace, using mock fallback", error=str(e))
        remote_skills = REMOTE_MARKET_SKILLS
        
    for s in remote_skills:
        skill_id = s.get("skillId") or s.get("skill_id") or s.get("name", "")
        if not skill_id:
            continue
        name = s.get("name") or skill_id
        source = s.get("source", "")
        installs = s.get("installs", 0)
        
        description = s.get("description")
        if not description:
            if source:
                description = f"GitHub: https://github.com/{source} | Installs: {installs}"
            else:
                description = f"Installs: {installs}"
                
        tags = s.get("tags") or []
        if not tags:
            if source:
                tags = source.split("/") + [name]
            else:
                tags = [name]
                
        url = s.get("url")
        if not url:
            if source:
                url = f"https://skills.sh/api/download/{source}/{skill_id}"
            else:
                url = f"https://skills.sh/packages/{skill_id}.yaml"
        
        if query:
            q_lower = query.lower()
            in_name = q_lower in name.lower()
            in_desc = q_lower in description.lower()
            in_tags = any(q_lower in t.lower() for t in tags)
            in_id = q_lower in skill_id.lower()
            if not (in_name or in_desc or in_tags or in_id):
                continue
                
        # Avoid duplication
        if any(local_s["skill_id"] == skill_id for local_s in market_skills):
            continue
            
        market_skills.append({
            "skill_id": skill_id,
            "name": name,
            "version": s.get("version", "1.0.0"),
            "description": description,
            "tags": tags,
            "trigger_patterns": s.get("trigger_patterns") or [name],
            "required_tools": s.get("required_tools", []),
            "risk_level": s.get("risk_level", "low"),
            "approval_required": s.get("approval_required", False),
            "url": url
        })
                    
    return market_skills


@router.post("/skills/install", response_model=SkillResponse)
async def install_skill(
    req: SkillInstallRequest,
    svc: SkillService = Depends(_get_service),
    user: UserModel = Depends(RoleRequired(["admin", "developer"])),
):
    """Install a skill from the local repository (name) or a remote URL."""
    skills_dir = Path(__file__).parent.parent.parent.parent / "skills"
    cache_dir = skills_dir / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    skill_yaml_content = None
    
    if req.skill_name_or_url.startswith(("http://", "https://")):
        url = req.skill_name_or_url
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cache_file = cache_dir / f"{url_hash}.yaml"
        url_filename = url.split("/")[-1]
        fallback_file = cache_dir / url_filename
        
        # 1. Try URL hash-based cache first
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    skill_yaml_content = f.read()
                logger.info("Using cached remote skill package (hash match)", url=url, cache_path=str(cache_file))
            except Exception as e:
                logger.warning("Failed to read cached skill file", path=str(cache_file), error=str(e))
                
        # 2. Try URL filename-based cache next
        if not skill_yaml_content and fallback_file.exists():
            try:
                with open(fallback_file, "r", encoding="utf-8") as f:
                    skill_yaml_content = f.read()
                logger.info("Using cached remote skill package (filename match)", url=url, cache_path=str(fallback_file))
            except Exception as e:
                logger.warning("Failed to read fallback cached skill file", path=str(fallback_file), error=str(e))
                
        # 3. Download if not cached
        if not skill_yaml_content:
            try:
                async with httpx.AsyncClient() as client:
                    res = await http_get_with_retry(client, url, timeout=8.0)
                    skill_yaml_content = res.text
                    # Save to cache
                    with open(cache_file, "w", encoding="utf-8") as f:
                        f.write(skill_yaml_content)
                    logger.info("Downloaded and cached remote skill package successfully", url=url, cache_path=str(cache_file))
            except Exception as e:
                # Try to fallback to mock YAML if download fails (offline mode)
                skill_id_guess = url_filename.replace(".yaml", "").replace(".yml", "").replace(".md", "")
                mock_yaml = get_mock_skill_yaml(skill_id_guess)
                if mock_yaml:
                    skill_yaml_content = mock_yaml
                    logger.info("Remote download failed; fell back to mock skill YAML", skill_id=skill_id_guess)
                else:
                    # Check if there is a name-based cache file matching the guessed ID
                    for ext in (".yaml", ".yml", ".md"):
                        name_cached = cache_dir / f"{skill_id_guess}{ext}"
                        if name_cached.exists():
                            try:
                                with open(name_cached, "r", encoding="utf-8") as f:
                                    skill_yaml_content = f.read()
                                logger.info("Remote download failed; fell back to name-cached skill file", skill_id=skill_id_guess, path=str(name_cached))
                                break
                            except Exception:
                                pass
                                
                if not skill_yaml_content:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Failed to fetch remote skill YAML (network error or timeout). "
                            f"Offline cache not available. Please check your network connection. Error: {str(e)}"
                        )
                    )
    else:
        # Check mock registry first
        mock_yaml = get_mock_skill_yaml(req.skill_name_or_url)
        if mock_yaml:
            skill_yaml_content = mock_yaml
        else:
            folder_name = req.skill_name_or_url.replace("-v1", "").replace("-", "_")
            local_path = skills_dir / folder_name / "skill.yaml"
            
            # If not in local path, search locally under skills/
            if not local_path.exists():
                for item in skills_dir.iterdir():
                    if item.is_dir() and not item.name.startswith(("_", "test_")):
                        yaml_path = item / "skill.yaml"
                        if yaml_path.exists():
                            try:
                                with open(yaml_path, "r", encoding="utf-8") as f:
                                    data = yaml.safe_load(f)
                                    if data and (data.get("skill_id") == req.skill_name_or_url or item.name == req.skill_name_or_url):
                                        local_path = yaml_path
                                        break
                            except Exception:
                                continue
            
            # If still not found, search in local cache_dir
            if not local_path.exists():
                for ext in (".yaml", ".yml", ".md"):
                    potential_cached = cache_dir / f"{req.skill_name_or_url}{ext}"
                    if potential_cached.exists():
                        local_path = potential_cached
                        break
                                
            if local_path.exists():
                try:
                    with open(local_path, "r", encoding="utf-8") as f:
                        skill_yaml_content = f.read()
                    logger.info("Using local skill file path", path=str(local_path))
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Failed to read local skill YAML: {str(e)}")
            else:
                # Try to search skills.sh API online to resolve this remote skill ID
                remote_url = None
                try:
                    async with httpx.AsyncClient() as client:
                        quoted_query = urllib.parse.quote(req.skill_name_or_url)
                        res = await http_get_with_retry(client, f"https://skills.sh/api/search?q={quoted_query}", timeout=8.0)
                        res_data = res.json()
                        if isinstance(res_data, dict) and "skills" in res_data:
                            for s in res_data["skills"]:
                                s_id = s.get("skillId") or s.get("skill_id") or s.get("name")
                                if s_id == req.skill_name_or_url and s.get("source"):
                                    remote_url = f"https://skills.sh/api/download/{s.get('source')}/{s_id}"
                                    break
                except Exception as e:
                    logger.error("Failed to query skills.sh search API for installation fallback", error=str(e))
                
                if remote_url:
                    try:
                        async with httpx.AsyncClient() as client:
                            res = await http_get_with_retry(client, remote_url, timeout=8.0)
                            skill_yaml_content = res.text
                            # Save to URL-hash cache too
                            url_hash = hashlib.sha256(remote_url.encode("utf-8")).hexdigest()
                            with open(cache_dir / f"{url_hash}.yaml", "w", encoding="utf-8") as f:
                                f.write(skill_yaml_content)
                    except Exception as e:
                        raise HTTPException(status_code=400, detail=f"Failed to download remote skill from {remote_url}. Please check your network connection or try importing locally. Error: {str(e)}")
                else:
                    raise HTTPException(status_code=404, detail=f"Skill '{req.skill_name_or_url}' not found in local market, remote registry, or offline cache")

    data = None
    # Try parsing it as a JSON payload from skills.sh download API first
    try:
        payload = json.loads(skill_yaml_content)
        if isinstance(payload, dict) and "files" in payload:
            files = payload.get("files", [])
            skill_md_content = None
            for f in files:
                if f.get("path") == "SKILL.md":
                    skill_md_content = f.get("contents")
                    break
            if not skill_md_content and files:
                skill_md_content = files[0].get("contents")
                
            if skill_md_content:
                parsed = await async_parse_markdown_skill(skill_md_content)
                skill_id_fallback = req.skill_name_or_url.split("/")[-1].replace(".yaml", "")
                data = {
                    "skill_id": parsed.get("skill_id") or skill_id_fallback,
                    "name": parsed.get("name") or skill_id_fallback,
                    "description": parsed.get("description") or f"Downloaded from skills.sh package {skill_id_fallback}",
                    "version": parsed.get("version") or "1.0.0",
                    "tags": parsed.get("tags") or [skill_id_fallback],
                    "trigger_patterns": parsed.get("trigger_patterns") or [skill_id_fallback],
                    "system_prompt": parsed.get("system_prompt") or "",
                    "context_budget": 16000,
                    "required_tools": parsed.get("required_tools") or [],
                    "input_schema": {},
                    "output_schema": {},
                    "risk_level": "low",
                    "approval_required": False
                }
    except Exception:
        pass

    if not data:
        # Fallback to parsing as raw YAML
        try:
            data = yaml.safe_load(skill_yaml_content)
            if not data or not isinstance(data, dict):
                raise ValueError("YAML is empty or not a valid dictionary")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid YAML structure: {str(e)}")

    skill_id = data.get("skill_id") or data.get("skillId")
    name = data.get("name")
    if not skill_id or not name:
        raise HTTPException(status_code=400, detail="Skill YAML must contain 'skill_id' and 'name'")

    workspace_path = None
    if req.scope == "project":
        if not req.workspace_path:
            raise HTTPException(status_code=400, detail="workspace_path is required when scope is 'project'")
        workspace_path = req.workspace_path

    create_data = {
        "skill_id": skill_id,
        "name": name,
        "version": data.get("version", "1.0.0"),
        "description": data.get("description"),
        "tags": data.get("tags", []),
        "trigger_patterns": data.get("trigger_patterns", []),
        "context_budget": data.get("context_budget", 8000),
        "required_tools": data.get("required_tools", []),
        "input_schema": data.get("input_schema", {}),
        "output_schema": data.get("output_schema", {}),
        "system_prompt": data.get("system_prompt"),
        "risk_level": data.get("risk_level", "low"),
        "approval_required": data.get("approval_required", False),
        "estimated_tokens": data.get("estimated_tokens", 10000),
        "estimated_duration_sec": data.get("estimated_duration_sec", 120),
        "workspace_path": workspace_path,
        "is_active": True,
    }

    existing = await svc.get_by_id(skill_id)
    if existing:
        installed = await svc.update(skill_id, create_data)
    else:
        installed = await svc.create(create_data)

    try:
        final_cache_path = cache_dir / f"{skill_id}.yaml"
        with open(final_cache_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(create_data, f, allow_unicode=True)
        logger.info("Saved final skill payload to name-based cache", skill_id=skill_id, path=str(final_cache_path))
    except Exception as e:
        logger.warning("Failed to save final skill package to name-based cache", skill_id=skill_id, error=str(e))

    return installed


# NOTE: Static paths MUST come before parameterized paths to avoid route conflicts

@router.post("/skills/preview", response_model=SkillPreviewResponse)
async def preview_skill(
    req: SkillPreviewRequest,
    user: UserModel = Depends(RoleRequired(["admin", "developer"])),
):
    """Parse skill file content (YAML or Markdown) and return preview metadata and warnings."""
    content = req.content
    stripped = content.strip()
    
    parser_type = "markdown"
    warnings = []
    
    # 1. Determine type
    is_yaml = False
    if stripped.startswith("{") or (":" in stripped and not stripped.startswith("#") and not stripped.startswith("---")):
        is_yaml = True
        
    if is_yaml:
        parser_type = "yaml"
        try:
            parsed = yaml.safe_load(content)
            if not parsed or not isinstance(parsed, dict):
                raise ValueError("YAML content is empty or not a dictionary")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse YAML content: {str(e)}")
            
        # Basic validation warnings
        if not parsed.get("skill_id"):
            warnings.append("Missing 'skill_id'.")
        if not parsed.get("name"):
            warnings.append("Missing 'name'.")
        if not parsed.get("system_prompt"):
            warnings.append("Missing 'system_prompt'.")
            
        parsed = normalize_and_correct_skill_metadata(parsed, is_async=True)
    else:
        # Markdown parsing with our parser
        parsed = await async_parse_markdown_skill(content)
        
        # Check warnings on original parsed before fallback
        raw_parsed = parse_markdown_skill(content)
        if not raw_parsed.get("name"):
            warnings.append("Skill 'name' was missing and automatically inferred/generated.")
        if not raw_parsed.get("skill_id") or raw_parsed.get("skill_id") == "unknown-skill":
            warnings.append("Skill 'skill_id' was missing and automatically generated.")
        if not raw_parsed.get("system_prompt"):
            warnings.append("No system prompt body detected in Markdown (anything outside YAML header is treated as system prompt).")
        if not raw_parsed.get("trigger_patterns"):
            warnings.append("No trigger patterns defined. The skill name was used as trigger.")
            
    return SkillPreviewResponse(
        parser_type=parser_type,
        metadata=parsed,
        warnings=warnings
    )


@router.get("/skills/search/{query}", response_model=list[SkillResponse])
async def search_skills(
    query: str,
    svc: SkillService = Depends(_get_service),
):
    """Search Skills by tags (comma-separated)."""
    tags = [t.strip() for t in query.split(",")]
    return await svc.search_by_tags(tags)


@router.post("/skills", response_model=SkillResponse, status_code=201)
async def create_skill(
    skill: SkillCreate,
    svc: SkillService = Depends(_get_service),
    user: UserModel = Depends(RoleRequired(["admin", "developer"])),
):
    """Register a new Skill."""
    existing = await svc.get_by_id(skill.skill_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Skill '{skill.skill_id}' already exists")
    return await svc.create(skill.model_dump())


@router.get("/skills", response_model=list[SkillResponse])
async def list_skills(
    active_only: bool = True,
    workspace_path: str | None = None,
    svc: SkillService = Depends(_get_service),
):
    """List all registered Skills."""
    return await svc.list_all(active_only=active_only, workspace_path=workspace_path)


@router.get("/skills/{skill_id}", response_model=SkillResponse)
async def get_skill(
    skill_id: str,
    svc: SkillService = Depends(_get_service),
):
    """Get a specific Skill by ID."""
    skill = await svc.get_by_id(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return skill


@router.put("/skills/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: str,
    body: SkillUpdate,
    svc: SkillService = Depends(_get_service),
    user: UserModel = Depends(RoleRequired(["admin", "developer"])),
):
    """Update an existing Skill."""
    result = await svc.update(skill_id, body.model_dump(exclude_unset=True))
    if not result:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return result


@router.delete("/skills/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: str,
    svc: SkillService = Depends(_get_service),
    user: UserModel = Depends(RoleRequired(["admin"])),
):
    """Uninstall/completely delete a Skill from database."""
    success = await svc.delete(skill_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
