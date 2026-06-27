"""Load Skill definitions from YAML files into the database."""

from pathlib import Path

import structlog
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.skill.service import SkillService

logger = structlog.get_logger()


async def load_skills_from_directory(
    skills_dir: str | Path,
    session: AsyncSession,
) -> int:
    """Scan a directory for skill.yaml files and upsert them into the DB.

    Returns the number of skills loaded.
    """
    skills_path = Path(skills_dir)
    if not skills_path.exists():
        logger.warning("Skills directory not found", path=str(skills_path))
        return 0

    svc = SkillService(session)
    loaded = 0

    for yaml_file in skills_path.rglob("skill.yaml"):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)

            if not data or "skill_id" not in data:
                logger.warning("Skipping invalid skill file", path=str(yaml_file))
                continue

            skill_id = data["skill_id"]
            existing = await svc.get_by_id(skill_id)

            if existing:
                await svc.update(skill_id, data)
                logger.info("Skill updated", skill_id=skill_id, source=str(yaml_file))
            else:
                await svc.create(data)
                logger.info("Skill created", skill_id=skill_id, source=str(yaml_file))

            loaded += 1

        except Exception as e:
            logger.error("Failed to load skill", path=str(yaml_file), error=str(e))

    return loaded
