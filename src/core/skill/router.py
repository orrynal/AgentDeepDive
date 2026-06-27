"""Skill Router — matches user intent to the best Skill.

Uses a two-stage strategy:
  1. Keyword matching (fast, exact tag overlap)
  2. Semantic vector matching (Milvus + sentence-transformers)
  3. Hybrid scoring to produce final ranked results
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.skill.service import SkillService

logger = structlog.get_logger()


class SkillRouter:
    """Routes user tasks to the most appropriate Skill."""

    # Weight for hybrid scoring: keyword_score * W_KW + semantic_score * W_SEM
    WEIGHT_KEYWORD = 0.4
    WEIGHT_SEMANTIC = 0.6

    def __init__(self, session: AsyncSession, embedder=None, milvus_client=None, tenant_id: str | None = None):
        self.service = SkillService(session, tenant_id=tenant_id)
        self.embedder = embedder        # SentenceTransformer instance (optional)
        self.milvus = milvus_client      # Milvus client (optional)

    async def route(self, query: str, top_k: int = 3) -> list[dict]:
        """Find the best matching Skills for a natural language query.

        Args:
            query: Natural language task description
            top_k: Number of top results to return

        Returns:
            List of skill dicts with added 'match_score' field, sorted by relevance
        """
        from src.core.workspace.manager import workspace_manager
        active_ws = workspace_manager.active_workspace

        # Stage 1: Keyword matching
        keyword_results = await self._keyword_match(query, workspace_path=active_ws)

        # Stage 2: Semantic matching (if embedder is available)
        semantic_results = await self._semantic_match(query, top_k=top_k * 2, workspace_path=active_ws)

        # Stage 3: Merge and rank
        merged = self._merge_results(keyword_results, semantic_results)

        # Sort by score descending and return top_k
        merged.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        return merged[:top_k]

    async def _keyword_match(self, query: str, workspace_path: str | None = None) -> list[dict]:
        """Stage 1: Match query words against skill tags and trigger_patterns."""
        # Tokenize query into words
        query_tokens = set(query.lower().replace(",", " ").replace("，", " ").split())

        all_skills = await self.service.list_all(active_only=True, workspace_path=workspace_path)
        results = []

        for skill in all_skills:
            score = 0.0
            tags = set(t.lower() for t in skill.get("tags", []))
            triggers = [t.lower() for t in skill.get("trigger_patterns", [])]

            # Tag overlap score
            overlap = query_tokens & tags
            if tags:
                score += len(overlap) / len(tags) * 0.6

            # Trigger pattern substring match
            for trigger in triggers:
                if trigger in query.lower() or query.lower() in trigger:
                    score += 0.4
                    break

            if score > 0:
                results.append({**skill, "keyword_score": min(score, 1.0)})

        return results

    async def _semantic_match(self, query: str, top_k: int = 6, workspace_path: str | None = None) -> list[dict]:
        """Stage 2: Semantic vector similarity search via Milvus."""
        if not self.embedder or not self.milvus:
            logger.debug("Semantic matching skipped — embedder or Milvus not configured")
            return []

        try:
            # Encode query
            query_embedding = self.embedder.encode(query).tolist()

            # Search in Milvus
            search_results = self.milvus.search(
                collection_name="skill_embeddings",
                data=[query_embedding],
                limit=top_k,
                output_fields=["skill_id"],
            )

            # Fetch full skill data for matched IDs
            results = []
            for hit in search_results[0]:
                skill_id = hit["entity"]["skill_id"]
                skill = await self.service.get_by_id(skill_id)
                if skill and skill.get("is_active", True):
                    sws = skill.get("workspace_path")
                    if sws is None or sws == "" or sws == workspace_path:
                        results.append({
                            **skill,
                            "semantic_score": hit["distance"],  # cosine similarity
                        })
            return results

        except Exception as e:
            logger.warning("Semantic search failed, falling back to keyword only", error=str(e))
            return []

    def _merge_results(
        self, keyword_results: list[dict], semantic_results: list[dict]
    ) -> list[dict]:
        """Merge keyword and semantic results with weighted scoring."""
        merged: dict[str, dict] = {}

        for skill in keyword_results:
            sid = skill["skill_id"]
            merged[sid] = {
                **skill,
                "match_score": skill.get("keyword_score", 0) * self.WEIGHT_KEYWORD,
            }

        for skill in semantic_results:
            sid = skill["skill_id"]
            sem_score = skill.get("semantic_score", 0) * self.WEIGHT_SEMANTIC
            if sid in merged:
                merged[sid]["match_score"] += sem_score
                merged[sid]["semantic_score"] = skill.get("semantic_score", 0)
            else:
                merged[sid] = {**skill, "match_score": sem_score}

        return list(merged.values())
