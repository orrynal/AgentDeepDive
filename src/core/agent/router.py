"""Adaptive Agent Router for deciding execution tiers."""

import os
from enum import Enum
import logging
from src.config import settings

logger = logging.getLogger("adaptive_router")


class RoutingTier(str, Enum):
    SMALL = "small"    # Tier 1: Single Generalist Agent
    MEDIUM = "medium"  # Tier 2: Static Lightweight Multi-Agent
    LARGE = "large"    # Tier 3: Fully Decentralized ContractNet Bidding


class AdaptiveRouter:
    """Decides the routing tier for a given task DAG and workspace."""

    @staticmethod
    def count_workspace_files(workspace_path: str) -> int:
        """Count the number of relevant source/configuration files in the workspace."""
        if not workspace_path or not os.path.exists(workspace_path):
            return 0
        
        ignored_dirs = {
            ".git", ".github", ".venv", "venv", "node_modules", 
            "__pycache__", ".pytest_cache", "dist", "build", ".idea", ".gemini"
        }
        
        file_count = 0
        try:
            for root, dirs, files in os.walk(workspace_path):
                # Prune ignored directories in-place
                dirs[:] = [d for d in dirs if d not in ignored_dirs]
                file_count += len(files)
        except Exception as e:
            logger.warning(f"Error walking workspace path '{workspace_path}': {e}")
            
        return file_count

    @classmethod
    def determine_tier(
        cls, 
        node_count: int, 
        workspace_path: str | None = None,
        explicit_tier: str | None = None
    ) -> RoutingTier:
        """Determine the routing tier based on constraints or explicit setting."""
        if not settings.adaptive_routing_enabled:
            return RoutingTier.LARGE

        if explicit_tier:
            try:
                return RoutingTier(explicit_tier.lower())
            except ValueError:
                logger.warning(f"Invalid explicit_tier '{explicit_tier}'. Falling back to auto-detection.")

        # 1. Gather metrics
        file_count = cls.count_workspace_files(workspace_path) if workspace_path else 0
        
        logger.info(f"AdaptiveRouter: Evaluating DAG with {node_count} nodes and {file_count} workspace files.")

        # 2. Apply classification rules
        # Tier 1 (Small)
        if (node_count <= settings.adaptive_max_nodes_small and 
                file_count <= settings.adaptive_max_files_small):
            logger.info("AdaptiveRouter decision: Tier 1 (SMALL) -> Single Generalist Mode")
            return RoutingTier.SMALL

        # Tier 2 (Medium)
        if (node_count <= settings.adaptive_max_nodes_medium and 
                file_count <= settings.adaptive_max_files_medium):
            logger.info("AdaptiveRouter decision: Tier 2 (MEDIUM) -> Static Lightweight Multi-Agent Mode")
            return RoutingTier.MEDIUM

        # Tier 3 (Large)
        logger.info("AdaptiveRouter decision: Tier 3 (LARGE) -> Fully Decentralized Bidding Mode")
        return RoutingTier.LARGE
