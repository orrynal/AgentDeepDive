"""Role Router — routes tasks to the best matching authorized Role using semantic similarity."""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.role.service import RoleService

logger = structlog.get_logger()


class RoleRouter:
    """Routes a task and its resolved Skill to the most appropriate authorized Role."""

    def __init__(self, session: AsyncSession, embedder=None):
        self.service = RoleService(session)
        self.embedder = embedder  # SentenceTransformer instance (optional)
        self._role_embeddings_cache = {}  # Cache: role_id -> np.ndarray

    async def route_role(self, query: str, skill_id: str) -> dict | None:
        """Find the best matching Role for a given task query and specific skill_id.

        Args:
            query: Natural language task description
            skill_id: The skill ID that the node will execute

        Returns:
            The matched Role dictionary, or None if no authorized role is found
        """
        # 1. Fetch all active roles
        roles = await self.service.list_all(active_only=True)
        if not roles:
            logger.warning("No active roles found in database")
            return None

        # 2. Security Gate: filter roles that explicitly allow this skill_id
        authorized_roles = []
        for r in roles:
            if skill_id in r.get("allowed_skills", []):
                authorized_roles.append(r)

        if not authorized_roles:
            logger.warning("Security Alert: No roles are authorized to run skill", skill_id=skill_id)
            return None

        # If only one role is authorized, return it directly to save computation
        if len(authorized_roles) == 1:
            logger.info("Single authorized role assigned directly", role_id=authorized_roles[0]["role_id"], skill_id=skill_id)
            return authorized_roles[0]

        # 3. Semantic similarity matching if embedder is configured
        if self.embedder:
            try:
                import numpy as np
                query_vec = self.embedder.encode(query)
                query_norm = np.linalg.norm(query_vec)

                best_score = -1.0
                best_role = None

                for role in authorized_roles:
                    role_id = role["role_id"]
                    # Get or compute role embedding
                    if role_id not in self._role_embeddings_cache:
                        role_text = f"{role['name']}. {role.get('description', '')}"
                        self._role_embeddings_cache[role_id] = self.embedder.encode(role_text)

                    role_vec = self._role_embeddings_cache[role_id]
                    role_norm = np.linalg.norm(role_vec)

                    if query_norm > 0 and role_norm > 0:
                        score = np.dot(query_vec, role_vec) / (query_norm * role_norm)
                    else:
                        score = 0.0

                    if score > best_score:
                        best_score = score
                        best_role = role

                if best_role:
                    logger.info(
                        "Semantic role routing successful",
                        query=query,
                        skill_id=skill_id,
                        matched_role=best_role["role_id"],
                        score=float(best_score),
                    )
                    return best_role
            except Exception as e:
                logger.warning("Semantic role routing failed, falling back to keyword heuristics", error=str(e))

        # 4. Fallback: Keyword/Heuristic overlap matching
        best_count = -1
        best_role = authorized_roles[0]

        query_words = set(query.lower().replace(",", " ").replace(".", " ").split())
        for role in authorized_roles:
            role_text = f"{role['name']} {role.get('description', '')}".lower()
            match_count = sum(1 for w in query_words if w in role_text)
            if match_count > best_count:
                best_count = match_count
                best_role = role

        logger.info(
            "Heuristic role routing selected",
            query=query,
            skill_id=skill_id,
            matched_role=best_role["role_id"],
            match_count=best_count,
        )
        return best_role
