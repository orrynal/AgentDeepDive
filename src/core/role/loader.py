"""Load Role definitions from YAML files into the database."""

from pathlib import Path

import structlog
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.role.service import RoleService

logger = structlog.get_logger()


async def load_roles_from_directory(
    roles_dir: str | Path,
    session: AsyncSession,
) -> int:
    """Scan a directory for role.yaml files and upsert them into the DB.

    Returns the number of roles loaded.
    """
    roles_path = Path(roles_dir)
    if not roles_path.exists():
        logger.warning("Roles directory not found", path=str(roles_path))
        return 0

    svc = RoleService(session)
    loaded = 0

    for yaml_file in roles_path.rglob("role.yaml"):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)

            if not data or "role_id" not in data:
                logger.warning("Skipping invalid role file", path=str(yaml_file))
                continue

            role_id = data["role_id"]
            existing = await svc.get_by_id(role_id)

            if existing:
                await svc.update(role_id, data)
                logger.info("Role updated", role_id=role_id, source=str(yaml_file))
            else:
                await svc.create(data)
                logger.info("Role created", role_id=role_id, source=str(yaml_file))

            loaded += 1

        except Exception as e:
            logger.error("Failed to load role", path=str(yaml_file), error=str(e))

    return loaded
