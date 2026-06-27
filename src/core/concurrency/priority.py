"""Dynamic Priority Calculator for task scheduling.

Computes a 0-100 priority score based on:
- Task type base priority
- Severity level
- Wait time (anti-starvation)
- Module criticality
"""

import time

TASK_TYPE_BASE = {
    "critical_bug_fix": 90,
    "security_patch": 85,
    "bug_fix": 70,
    "refactor": 50,
    "feature": 40,
    "test_generation": 35,
    "documentation": 25,
    "formatting": 10,
    "analysis": 30,
}

MODULE_CRITICALITY = {
    "auth": 15, "security": 15, "payment": 12,
    "core": 10, "api": 8, "database": 8,
    "config": 5, "utils": 3, "tests": 2,
    "docs": 1, "default": 5,
}


def calculate_priority(
    task_type: str = "analysis",
    severity: int = 1,
    wait_start: float | None = None,
    target_module: str = "default",
) -> int:
    """Calculate dynamic priority score (0-100).

    Args:
        task_type: Type of task (from TASK_TYPE_BASE keys)
        severity: Severity level 1-5
        wait_start: Timestamp when task started waiting (for anti-starvation)
        target_module: Module being modified (for criticality weighting)
    """
    base = TASK_TYPE_BASE.get(task_type, 30)
    severity_bonus = min(severity, 5) * 3
    module_weight = MODULE_CRITICALITY.get(target_module, MODULE_CRITICALITY["default"])

    wait_bonus = 0
    if wait_start:
        wait_minutes = (time.time() - wait_start) / 60
        wait_bonus = min(wait_minutes * 2, 15)  # Max +15 from waiting

    return min(100, int(base + severity_bonus + module_weight + wait_bonus))
