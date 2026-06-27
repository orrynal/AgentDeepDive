"""Task Splitter — decomposes a complex task into a DAG of subtasks.

Uses an LLM to analyze a natural language task description and produce
a structured DAG with proper dependencies.
"""

import json

import litellm
import structlog

from src.config import settings
from src.core.orchestrator.models import DAGDefinition, DAGEdge, DAGNode
from src.database import async_session
from src.core.skill.service import SkillService
from src.core.workspace.manager import workspace_manager

logger = structlog.get_logger()

SPLIT_SYSTEM_PROMPT_TEMPLATE = """你是一个任务分解专家。你的职责是将复杂的软件工程任务拆解为一个有向无环图(DAG)。

规则:
1. 每个子任务必须是原子性的、可独立执行的
2. 明确标注子任务之间的依赖关系
3. 无依赖的子任务应该可以并行执行
4. 为每个子任务分配合适的Skill ID，必须且只能从下面给出的【可用的Skill类型】中选择

可用的Skill类型:
{skills_list}

输出严格的JSON格式:
{{
  "dag_name": "任务名称",
  "nodes": [
    {{
      "node_id": "step-1",
      "name": "子任务名称",
      "skill_id": "选择最匹配的Skill ID",
      "description": "具体要做什么，需要包含足够的信息供该Skill的智能体执行",
      "dependencies": [],
      "priority": 50
    }}
  ],
  "edges": [
    {{"from_node": "step-1", "to_node": "step-2"}}
  ]
}}"""


async def split_task(task_description: str) -> DAGDefinition:
    """Use LLM to decompose a complex task into a DAG."""
    logger.info("Splitting task into DAG", task=task_description[:100])

    # Fetch active skills dynamically from current workspace
    active_ws = workspace_manager.active_workspace
    skills_list_str = ""
    try:
        async with async_session() as session:
            skill_svc = SkillService(session)
            skills = await skill_svc.list_all(active_only=True, workspace_path=active_ws)
            for s in skills:
                desc = s.get("description", "") or ""
                skills_list_str += f"- {s['skill_id']}: {s['name']} ({desc})\n"
    except Exception as ex:
        logger.error("Failed to query active skills for task splitter, falling back to static list", error=str(ex))
        skills_list_str = (
            "- code-analysis-v1: 代码分析（只读，分析现有代码结构/质量/依赖）\n"
            "- code-generator-v1: 代码生成（编写新代码、编写完整功能、实现游戏等）\n"
            "- code-reviewer-v1: 代码评审与质量把关（提供明确 of APPROVED/REJECTED 结论）\n"
            "- perf-optimizer-v1: 性能调优与重构\n"
            "- bug-fixer-v1: Bug修复与故障定位\n"
            "- doc-writer-v1: 文档与报告编写\n"
            "- test-generator-v1: 测试生成与验证\n"
        )

    system_prompt = SPLIT_SYSTEM_PROMPT_TEMPLATE.format(skills_list=skills_list_str)

    response = await litellm.acompletion(
        model=settings.default_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请将以下任务拆解为DAG:\n\n{task_description}"},
        ],
        temperature=0.2,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    # Parse — handle markdown code blocks if model wraps in ```json
    if "```" in content:
        content = content.split("```json")[-1].split("```")[0]

    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        # Fallback: single-node DAG
        logger.warning("Failed to parse LLM DAG output, creating single-node DAG", error=str(e), raw_content=content)
        return DAGDefinition(
            name=task_description[:50],
            nodes=[DAGNode(
                node_id="step-1",
                name=task_description[:100],
                skill_id="code-analysis-v1",
                description=task_description,
            )],
        )

    # Build DAG from parsed JSON
    nodes = [
        DAGNode(
            node_id=n.get("node_id", f"step-{i}"),
            name=n.get("name", ""),
            skill_id=n.get("skill_id", "code-analysis-v1"),
            description=n.get("description", ""),
            dependencies=n.get("dependencies", []),
            priority=n.get("priority", 50),
        )
        for i, n in enumerate(data.get("nodes", []))
    ]

    edges = [
        DAGEdge(from_node=e["from_node"], to_node=e["to_node"])
        for e in data.get("edges", [])
    ]

    dag = DAGDefinition(
        name=data.get("dag_name", task_description[:50]),
        description=task_description,
        nodes=nodes,
        edges=edges,
    )

    logger.info("Task split into DAG", dag_id=dag.dag_id,
                nodes=len(nodes), edges=len(edges))
    return dag
