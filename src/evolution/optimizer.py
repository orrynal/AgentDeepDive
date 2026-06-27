"""Skill Self-Optimizer for auto-patching Skill prompts based on diagnostics.

Modifies and upgrades the version of the corresponding skill's YAML file.
"""

import os
import re
import yaml
import litellm
import structlog
from typing import Any
from src.config import settings

logger = structlog.get_logger()


def find_skill_file(skills_dir: str, skill_id: str) -> str | None:
    """Recursively search for a skill YAML file containing the specified skill_id."""
    for root, _, files in os.walk(skills_dir):
        for f in files:
            if f.endswith(".yaml") or f.endswith(".yml"):
                path = os.path.join(root, f)
                try:
                    with open(path, "r", encoding="utf-8") as file:
                        data = yaml.safe_load(file)
                        if data and data.get("skill_id") == skill_id:
                            return path
                except Exception:
                    continue
    return None


class SkillOptimizer:
    """Analyzes diagnostics to automatically patch and improve Skill Prompts."""

    def __init__(self, model: str | None = None):
        self.model = model or settings.default_model

    async def generate_optimized_prompt(
        self,
        skill_id: str,
        diagnostic: dict[str, Any],
        skills_dir: str | None = None
    ) -> str | None:
        """Analyze failure and call LLM to generate an optimized system prompt without writing to disk."""
        if skills_dir is None:
            skills_dir = os.path.join(settings.resolved_workspace_path, "skills")
        path = find_skill_file(skills_dir, skill_id)
        if not path:
            logger.warning("Skill file not found on disk for prompt generation", skill_id=skill_id)
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error("Failed to read skill file", path=path, error=str(e))
            return None

        current_prompt = yaml_data.get("system_prompt", "")

        prompt = f"""You are an Expert Prompt Engineer.
Analyze the following failure diagnostics for Skill '{skill_id}':
Failure Category: {diagnostic.get('failure_category')}
Reason: {diagnostic.get('reason')}
Recommendation: {diagnostic.get('recommendation')}

Here is the current system prompt of the Skill:
---
{current_prompt}
---

Your task is to optimize the system prompt by appending specific guidelines, rules, or requirements to address the failure root cause. Do NOT lose the original guidelines.
Return ONLY the newly optimized system prompt string. Do not include markdown fences like ``` or introductory/concluding text. Return the raw string.
"""
        try:
            resp = await litellm.acompletion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=2048
            )
            new_prompt = resp.choices[0].message.content.strip()

            # Clean markdown wraps if the model returned them anyway
            if new_prompt.startswith("```"):
                new_prompt = re.sub(r"^```[a-zA-Z]*\n|```$", "", new_prompt, flags=re.MULTILINE).strip()

            return new_prompt
        except Exception as e:
            logger.error("Failed to generate optimized prompt via LLM", skill_id=skill_id, error=str(e))
            return None

    async def optimize_skill(
        self,
        skill_id: str,
        diagnostic: dict[str, Any],
        skills_dir: str | None = None
    ) -> bool:
        """Patch system prompt in the corresponding YAML and bump minor version."""
        if skills_dir is None:
            skills_dir = os.path.join(settings.resolved_workspace_path, "skills")
        path = find_skill_file(skills_dir, skill_id)
        if not path:
            return False

        new_prompt = await self.generate_optimized_prompt(skill_id, diagnostic, skills_dir)
        if not new_prompt:
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}
            
            yaml_data["system_prompt"] = new_prompt

            # Bump version (patch number)
            version = yaml_data.get("version", "1.0.0")
            parts = version.split(".")
            if len(parts) == 3:
                parts[2] = str(int(parts[2]) + 1)
                yaml_data["version"] = ".".join(parts)

            # Write back
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(yaml_data, f, allow_unicode=True, sort_keys=False)

            logger.info(
                "Skill auto-patched and optimized",
                skill_id=skill_id,
                new_version=yaml_data["version"],
                path=path,
            )
            return True
        except Exception as e:
            logger.error("Failed to write optimized skill file", skill_id=skill_id, error=str(e))
            return False


# Global Singleton
skill_optimizer = SkillOptimizer()
