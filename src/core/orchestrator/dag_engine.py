"""DAG Engine — topological scheduling and parallel execution of task graphs.

Core responsibilities:
1. Validate DAG structure (no cycles)
2. Schedule nodes via topological sort
3. Execute ready nodes in parallel
4. Manage color state transitions
5. Collect results and propagate to downstream nodes
"""

import asyncio
from datetime import datetime, timezone

import structlog

from src.core.agent.executor import AgentExecutor
from src.core.orchestrator.models import DAGDefinition, DAGNode, NodeColor
from src.core.skill.service import SkillService

logger = structlog.get_logger()


class DAGEngine:
    """Executes a DAG by scheduling and running nodes based on dependency order."""

    def __init__(self, skill_service: SkillService):
        self.skill_service = skill_service
        self.model_override = None

    async def execute(self, dag: DAGDefinition, model_override: str | None = None) -> DAGDefinition:
        """Execute a complete DAG from start to finish.

        Nodes are executed in parallel when their dependencies allow.
        """
        from src.core.telemetry import get_tracer
        from opentelemetry import trace
        
        tracer = get_tracer()
        with tracer.start_as_current_span("DAGEngine.execute") as span:
            span.set_attribute("dag_id", dag.dag_id)
            span.set_attribute("dag_name", dag.name)
            span.set_attribute("total_nodes", len(dag.nodes))
            if model_override:
                span.set_attribute("model_override", model_override)
                
            self.model_override = model_override
            logger.info("DAG execution started", dag_id=dag.dag_id, name=dag.name,
                         total_nodes=len(dag.nodes), model_override=model_override)

            # Validate DAG
            if not self._validate_no_cycles(dag):
                dag.status = "failed"
                self._publish_dag_status(dag)
                logger.error("DAG has cycles", dag_id=dag.dag_id)
                span.set_status(trace.StatusCode.ERROR, "DAG has cycles")
                return dag

            # Determine Routing Tier using AdaptiveRouter
            from src.core.agent.router import AdaptiveRouter
            from src.config import settings
            workspace_path = settings.resolved_workspace_path
            explicit_tier = None
            if hasattr(dag, "constraints") and dag.constraints:
                explicit_tier = dag.constraints.get("routing_tier")
            elif hasattr(dag, "routing_tier") and dag.routing_tier:
                explicit_tier = dag.routing_tier
                
            dag.routing_tier = AdaptiveRouter.determine_tier(
                node_count=len(dag.nodes),
                workspace_path=workspace_path,
                explicit_tier=explicit_tier
            ).value
            span.set_attribute("routing_tier", dag.routing_tier)
            logger.info("DAG Routing Tier determined", dag_id=dag.dag_id, routing_tier=dag.routing_tier)

            # Reset all incomplete/failed nodes to GRAY to allow clean resumption, but preserve ORANGE nodes with approval_id
            for node in dag.nodes:
                if node.color == NodeColor.ORANGE and getattr(node, "approval_id", None):
                    continue
                if node.color != NodeColor.GREEN:
                    node.color = NodeColor.GRAY
                    node.error = None
                    if hasattr(node, "approval_id"):
                        node.approval_id = None

            dag.status = "running"
            self._publish_dag_status(dag)

            # Register session under Central Brain supervision
            from src.core.orchestrator.central_brain import central_brain
            await central_brain.register_session(dag)

            try:
                # Enforce budget safety check
                if not await central_brain.check_budget_safety(dag):
                    dag.status = "failed"
                    self._publish_dag_status(dag)
                    logger.error("DAG failed budget safety check", dag_id=dag.dag_id)
                    span.set_status(trace.StatusCode.ERROR, "DAG failed budget safety check")
                    return dag

                iteration = 0
                max_iterations = len(dag.nodes) + 5  # Safety limit

                while not dag.is_complete() and iteration < max_iterations:
                    iteration += 1
                    ready_nodes = dag.get_ready_nodes()

                    if not ready_nodes:
                        if dag.is_complete():
                            break
                        # No ready nodes but not complete → deadlock or waiting for human
                        if any(n.color in (NodeColor.ORANGE, NodeColor.SUSPENDED) for n in dag.nodes):
                            logger.info("DAG paused — waiting for human approval or interaction", dag_id=dag.dag_id)
                            dag.status = "paused"
                            self._publish_dag_status(dag)
                            span.set_attribute("paused", True)
                            return dag
                        else:
                            logger.error("DAG deadlocked — no ready nodes", dag_id=dag.dag_id)
                            dag.status = "failed"
                            self._publish_dag_status(dag)
                            span.set_status(trace.StatusCode.ERROR, "DAG deadlocked")
                            return dag

                    logger.info(
                        "DAG iteration",
                        iteration=iteration,
                        ready=[n.node_id for n in ready_nodes],
                        dag_id=dag.dag_id,
                    )

                    # Transition ready nodes to BLUE (queued)
                    for node in ready_nodes:
                        self._transition(dag, node, NodeColor.BLUE)

                    # Execute all ready nodes in parallel
                    running_tasks = [asyncio.create_task(self._execute_node(dag, node)) for node in ready_nodes]
                    try:
                        await asyncio.gather(*running_tasks)
                    except asyncio.CancelledError:
                        logger.warning("DAG execution iteration cancelled, cancelling running node tasks", dag_id=dag.dag_id)
                        for t in running_tasks:
                            if not t.done():
                                t.cancel()
                        # Wait for all tasks to finish cancelling to avoid dangling tasks
                        await asyncio.gather(*running_tasks, return_exceptions=True)
                        raise
                    except Exception as e:
                        logger.error("Error during parallel node execution", error=str(e), dag_id=dag.dag_id)
                        for t in running_tasks:
                            if not t.done():
                                t.cancel()
                        await asyncio.gather(*running_tasks, return_exceptions=True)
                        raise

                # Determine final status
                if dag.has_failed():
                    dag.status = "completed_with_errors"
                    span.set_status(trace.StatusCode.ERROR, "Completed with errors")
                else:
                    dag.status = "completed"
                    span.set_status(trace.StatusCode.OK)

                dag.completed_at = datetime.now(timezone.utc).isoformat()
                self._publish_dag_status(dag)
                logger.info("DAG execution finished", dag_id=dag.dag_id, status=dag.status)
                return dag
            finally:
                await central_brain.deregister_session(dag.dag_id)
                import gc
                gc.collect()
                logger.info("DAG session deregistered and garbage collected", dag_id=dag.dag_id)

    async def _execute_node(self, dag: DAGDefinition, node: DAGNode):
        """Execute a single DAG node."""
        from src.core.telemetry import get_tracer
        from opentelemetry import trace
        
        tracer = get_tracer()
        with tracer.start_as_current_span("DAGEngine.execute_node") as span:
            span.set_attribute("node_id", node.node_id)
            span.set_attribute("node_name", node.name)
            span.set_attribute("skill_id", node.skill_id or "auto")
            if getattr(node, "role_id", None):
                span.set_attribute("role_id", node.role_id)
            span.set_attribute("priority", node.priority)
            
            self._transition(dag, node, NodeColor.YELLOW)
            node.started_at = datetime.now(timezone.utc).isoformat()

            try:
                from src.database import async_session
                async with async_session() as session:
                    skill_service = SkillService(session, tenant_id=dag.tenant_id)

                    # Resolve Skill
                    if not node.skill_id or node.skill_id == "auto":
                        from src.core.skill.router import SkillRouter
                        from src.core.memory.rag_manager import rag_manager
                        router = SkillRouter(
                            skill_service.session,
                            embedder=rag_manager.embedder,
                            milvus_client=rag_manager.client,
                        )
                        matches = await router.route(node.description or node.name, top_k=1)
                        if not matches:
                            raise ValueError(f"Auto-routing failed: no suitable skill found for node '{node.node_id}'")
                        skill = matches[0]
                        node.skill_id = skill["skill_id"]
                    else:
                        skill = await skill_service.get_by_id(node.skill_id)
                        if not skill:
                            logger.warning("Skill not found in database, falling back to auto-routing", skill_id=node.skill_id)
                            from src.core.skill.router import SkillRouter
                            from src.core.memory.rag_manager import rag_manager
                            router = SkillRouter(
                                skill_service.session,
                                embedder=rag_manager.embedder,
                                milvus_client=rag_manager.client,
                            )
                            matches = await router.route(node.description or node.name, top_k=1)
                            if not matches:
                                raise ValueError(f"Auto-routing fallback failed: no suitable skill found for node '{node.node_id}'")
                            skill = matches[0]
                            node.skill_id = skill["skill_id"]
                            
                    span.set_attribute("resolved_skill_id", node.skill_id)

                    # A/B Testing routing decision
                    from src.core.evolution.ab_manager import ab_manager
                    resolved_skill_id = node.constraints.get("resolved_skill_id")
                    if not resolved_skill_id:
                        resolved_skill_id = await ab_manager.get_routing_decision(node.skill_id)
                    
                    if resolved_skill_id != node.skill_id:
                        variant_skill = await skill_service.get_by_id(resolved_skill_id)
                        if variant_skill:
                            skill = variant_skill
                            node.constraints["resolved_skill_id"] = resolved_skill_id
                        else:
                            logger.warning("Variant skill not found, falling back to original", variant_id=resolved_skill_id)
                    else:
                        node.constraints["resolved_skill_id"] = node.skill_id

                    # Build context from upstream node results
                    context = self._build_context_from_upstream(dag, node)

                    # Check if approval is required
                    if skill.get("approval_required"):
                        from src.config import settings
                        if settings.auto_approve_l3:
                            logger.info("Auto-approval enabled (auto_approve_l3=True). Bypassing HIL approval.", node_id=node.node_id)
                            self._transition(dag, node, NodeColor.YELLOW)
                        else:
                            from src.core.governance.approval import approval_manager
                            import json
                            
                            appr_id = getattr(node, "approval_id", None)
                            granted = False
                            
                            if appr_id:
                                logger.info("Resuming check on existing approval", node_id=node.node_id, approval_id=appr_id)
                                r = await approval_manager._get_redis()
                                data_str = await r.get(f"agentdeep:approvals:{appr_id}")
                                if data_str:
                                    payload = json.loads(data_str)
                                    if payload.get("status") == "approved":
                                        logger.info("Existing approval was already GRANTED", approval_id=appr_id)
                                        granted = True
                                    elif payload.get("status") == "rejected":
                                        logger.info("Existing approval was already REJECTED", approval_id=appr_id)
                                        granted = False
                                    else:
                                        self._transition(dag, node, NodeColor.ORANGE)
                                        granted = await approval_manager.wait_for_approval(appr_id)
                                else:
                                    logger.warning("Existing approval details lost in Redis, requesting new approval", approval_id=appr_id)
                                    appr_id = None
                                    
                            if not appr_id:
                                self._transition(dag, node, NodeColor.ORANGE)
                                logger.info("Node requires approval before execution", node_id=node.node_id)
                                appr_id = await approval_manager.request_approval(
                                    task_id=f"{dag.dag_id}:{node.node_id}",
                                    agent_id=f"skill:{node.skill_id}",
                                    tool_name="execute_skill",
                                    arguments={"skill_id": node.skill_id, "node_id": node.node_id},
                                    priority=node.priority,
                                    tenant_id=dag.tenant_id,
                                    task_description=f"Executing: {dag.name} (Node: {node.name})",
                                )
                                node.approval_id = appr_id
                                from src.core.orchestrator.persistence import save_dag_to_disk
                                import inspect
                                try:
                                    sig = inspect.signature(save_dag_to_disk)
                                    if len(sig.parameters) == 1:
                                        save_dag_to_disk(dag)
                                    else:
                                        save_dag_to_disk(dag, dag.tenant_id)
                                except Exception:
                                    try:
                                        save_dag_to_disk(dag, dag.tenant_id)
                                    except TypeError:
                                        save_dag_to_disk(dag)
                                granted = await approval_manager.wait_for_approval(appr_id)
                                
                            if not granted:
                                raise RuntimeError("Skill execution rejected by user.")
                            self._transition(dag, node, NodeColor.YELLOW)

                    # Resolve Role from database or auto-assign semantically (bypassed for Tier 1 SMALL)
                    role = None
                    if getattr(dag, "routing_tier", "large") != "small":
                        if hasattr(node, "role_id") and node.role_id:
                            if node.role_id == "auto":
                                from src.config import settings
                                # Tier 3 (Large) gets bidding cycle, Tier 2 (Medium) gets direct route
                                if getattr(dag, "routing_tier", "large") == "large" and settings.contract_net_enabled:
                                    from src.core.agent.contract_net import ContractNetManager
                                    cnp_manager = ContractNetManager(skill_service.session)
                                    logger.info("Executing Contract Net bidding for node", node_id=node.node_id)
                                    role = await cnp_manager.run_bidding_cycle(
                                        task_id=node.node_id,
                                        task_description=node.description or node.name,
                                        skill=skill
                                    )
                                    if role:
                                        node.role_id = role["role_id"]
                                        if not node.constraints:
                                            node.constraints = {}
                                        node.constraints["bid_info"] = role.get("bid_info", {})
                                        logger.info("Contract Net bidding won", role_id=role["role_id"], node_id=node.node_id)

                                if not role:
                                    from src.core.role.router import RoleRouter
                                    from src.core.memory.rag_manager import rag_manager
                                    role_router = RoleRouter(
                                        skill_service.session,
                                        embedder=rag_manager.embedder,
                                    )
                                    role = await role_router.route_role(
                                        query=node.description or node.name,
                                        skill_id=skill["skill_id"],
                                    )
                                    if role:
                                        node.role_id = role["role_id"]  # Update node state with chosen role
                                    else:
                                        raise ValueError(f"Auto-role routing failed: no authorized role found for skill '{skill['skill_id']}'")
                            else:
                                from src.core.role.service import RoleService
                                role_svc = RoleService(skill_service.session)
                                role = await role_svc.get_by_id(node.role_id)
                                if not role:
                                    raise ValueError(f"Role '{node.role_id}' not found")

                    if role:
                        span.set_attribute("role_id", role["role_id"])

                    # Execute via Agent
                    if getattr(dag, "routing_tier", "large") == "small":
                        from src.core.agent.generalist import GeneralistAgent
                        parent_outputs = {}
                        for dep_id in node.dependencies:
                            dep_node = dag.get_node(dep_id)
                            if dep_node and dep_node.result:
                                parent_outputs[dep_id] = dep_node.result.get("output", "")
                        
                        logger.info("Executing node via Generalist Agent", node_id=node.node_id, tenant_id=dag.tenant_id)
                        generalist = GeneralistAgent(model=self.model_override)
                        result = await generalist.execute_node(
                            task_id=node.node_id,
                            node_instruction=node.description or node.name,
                            parent_outputs=parent_outputs,
                            allowed_tools=skill.get("required_tools"),
                            tenant_id=dag.tenant_id,
                        )
                    else:
                        executor = AgentExecutor(model=self.model_override)
                        result = await executor.execute(
                            task_id=node.node_id,
                            task_description=node.description or node.name,
                            skill=skill,
                            context=context,
                            role=role,
                            tenant_id=dag.tenant_id,
                        )

                if result["status"] == "completed":
                    # Run Multi-Layered Verification System
                    from src.core.verification import verify_invariants, run_e2e_tests, verify_visuals_with_vlm
                    
                    logger.info("Running multi-layered verification for node", node_id=node.node_id)
                    
                    # 1. Invariants Check
                    inv_res = await verify_invariants(dag, node)
                    if not inv_res["success"]:
                        result["status"] = "failed"
                        result["error"] = f"Invariant Verification Failed:\n{inv_res['details']}"
                        logger.error("Verification failed at Invariants layer", node_id=node.node_id, error=result["error"])
                    else:
                        # 2. Playwright E2E & Screenshot
                        e2e_res = await run_e2e_tests(dag, node)
                        if not e2e_res["success"]:
                            result["status"] = "failed"
                            result["error"] = f"E2E Interaction Verification Failed:\n{e2e_res['details']}"
                            logger.error("Verification failed at E2E layer", node_id=node.node_id, error=result["error"])
                        else:
                            # 3. VLM Visual Verification
                            vlm_res = await verify_visuals_with_vlm(dag, node, e2e_res.get("screenshot_path"))
                            if not vlm_res["success"]:
                                result["status"] = "failed"
                                result["error"] = f"VLM Visual Audit Failed:\n{vlm_res['details']}"
                                logger.error("Verification failed at VLM layer", node_id=node.node_id, error=result["error"])
                            else:
                                logger.info("All verification layers passed successfully", node_id=node.node_id)
                                if e2e_res.get("screenshot_path"):
                                    if not node.constraints:
                                        node.constraints = {}
                                    node.constraints["verification_screenshot"] = e2e_res["screenshot_path"]

                if result["status"] == "completed":
                    node.result = {
                        "output": result.get("result", ""),
                        "trace": result.get("trace", {}),
                    }
                    self._transition(dag, node, NodeColor.GREEN)
                    span.set_status(trace.StatusCode.OK)
                    
                    # Episodic Memory: If this node previously failed and was healed successfully, save this experience
                    if node.constraints and node.constraints.get("self_healing_attempts", 0) > 0:
                        try:
                            healing_nodes = [
                                n for n in dag.nodes 
                                if n.node_id.startswith(f"heal-{node.node_id}-")
                            ]
                            if healing_nodes:
                                successful_heal = None
                                for hn in healing_nodes:
                                    if hn.color == NodeColor.GREEN:
                                        successful_heal = hn
                                        break
                                
                                if not successful_heal:
                                    successful_heal = healing_nodes[-1]
                                
                                patch_desc = ""
                                if successful_heal.result and isinstance(successful_heal.result, dict):
                                    patch_desc = successful_heal.result.get("output", "")
                                if not patch_desc:
                                    patch_desc = successful_heal.description or successful_heal.name
                                
                                last_error = node.constraints.get("last_error", "Unknown execution error")
                                
                                logger.info(
                                    "Saving successful self-healing experience to episodic memory",
                                    node_id=node.node_id,
                                    error=last_error,
                                    patch=patch_desc
                                )
                                from src.core.memory.rag_manager import rag_manager
                                rag_manager.save_episodic_memory(
                                    task_id=node.node_id,
                                    prompt=node.description or node.name,
                                    error_stack=last_error,
                                    patch=patch_desc,
                                    skill_id=node.skill_id
                                )
                        except Exception as mem_err:
                            logger.error("Failed to save episodic memory after successful self-healing", error=str(mem_err))

                    # A/B Testing: Record success and spent tokens
                    try:
                        from src.core.evolution.ab_manager import ab_manager
                        from src.evolution.evaluator import evaluator
                        
                        resolved_skill_id = node.constraints.get("resolved_skill_id") or node.skill_id
                        spent_tokens = result.get("trace", {}).get("total_tokens", 0)
                        
                        # Dynamically invoke Multi-Judge system to score the variant run
                        eval_score = None
                        is_vetoed = False
                        if ":flywheel:" in resolved_skill_id or settings.ab_testing_enabled:
                            try:
                                trace_steps = result.get("trace", {}).get("steps", [])
                                eval_res = await evaluator.evaluate_trace(
                                    task_description=node.description or node.name,
                                    skill_name=resolved_skill_id,
                                    trace_steps=trace_steps,
                                    agent_output=result.get("result", "")
                                )
                                eval_score = eval_res.get("score")
                                is_vetoed = eval_res.get("security_vetoed", False)
                                logger.info("Multi-Judge scored A/B variant execution", skill_id=resolved_skill_id, score=eval_score, vetoed=is_vetoed)
                            except Exception as ee:
                                logger.warning("Failed to score trace using Multi-Judge evaluator", error=str(ee))

                        # If security veto is triggered, mark run as failed (success=False, score=0.0)
                        if is_vetoed:
                            logger.error("A/B variant execution failed Multi-Tenant Security Veto! Marking success=False", skill_id=resolved_skill_id)
                            await ab_manager.record_run_result(resolved_skill_id, success=False, tokens=spent_tokens, score=0.0)
                        else:
                            await ab_manager.record_run_result(resolved_skill_id, success=True, tokens=spent_tokens, score=eval_score)
                        
                        if ":flywheel:" in resolved_skill_id:
                            parent_id = resolved_skill_id.split(":flywheel:")[0]
                            await ab_manager.evaluate_and_promote(parent_id, resolved_skill_id, skill_service.session)
                    except Exception as ab_err:
                        logger.error("Failed to record A/B success telemetry", error=str(ab_err))
                else:
                    node.error = result.get("error", "Unknown error")
                    span.set_status(trace.StatusCode.ERROR, node.error)
 
                    # A/B Testing: Record failure
                    try:
                        from src.core.evolution.ab_manager import ab_manager
                        resolved_skill_id = node.constraints.get("resolved_skill_id") or node.skill_id
                        spent_tokens = result.get("trace", {}).get("total_tokens", 0)
                        await ab_manager.record_run_result(resolved_skill_id, success=False, tokens=spent_tokens, score=0.0)
                        if ":flywheel:" in resolved_skill_id:
                            parent_id = resolved_skill_id.split(":flywheel:")[0]
                            await ab_manager.evaluate_and_promote(parent_id, resolved_skill_id, skill_service.session)
                    except Exception as ab_err:
                        logger.error("Failed to record A/B failure telemetry", error=str(ab_err))

                    healed = await self._attempt_self_healing(dag, node, result.get("error", ""))
                    if not healed:
                        self._transition(dag, node, NodeColor.SUSPENDED)
                        # Publish workflow.suspended event
                        from src.core.agent.pool import agent_bus
                        try:
                            asyncio.create_task(
                                agent_bus.publish(
                                    topic="workflow.suspended",
                                    sender_id="dag_engine",
                                    payload={
                                        "dag_id": dag.dag_id,
                                        "node_id": node.node_id,
                                        "error": node.error or "Unknown error",
                                        "timestamp": datetime.now(timezone.utc).isoformat()
                                    }
                                )
                            )
                        except Exception:
                            pass

            except asyncio.CancelledError:
                self._transition(dag, node, NodeColor.RED)
                node.error = "Cancelled"
                raise
            except Exception as e:
                node.error = str(e)
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR, str(e))

                # A/B Testing: Record failure
                try:
                    from src.core.evolution.ab_manager import ab_manager
                    resolved_skill_id = node.constraints.get("resolved_skill_id") or node.skill_id
                    await ab_manager.record_run_result(resolved_skill_id, success=False, tokens=0, score=0.0)
                    if ":flywheel:" in resolved_skill_id and 'skill_service' in locals():
                        parent_id = resolved_skill_id.split(":flywheel:")[0]
                        await ab_manager.evaluate_and_promote(parent_id, resolved_skill_id, skill_service.session)
                except Exception as ab_err:
                    logger.error("Failed to record A/B exception failure telemetry", error=str(ab_err))

                healed = await self._attempt_self_healing(dag, node, str(e))
                if not healed:
                    self._transition(dag, node, NodeColor.SUSPENDED)
                    # Publish workflow.suspended event
                    from src.core.agent.pool import agent_bus
                    try:
                        asyncio.create_task(
                            agent_bus.publish(
                                topic="workflow.suspended",
                                sender_id="dag_engine",
                                payload={
                                    "dag_id": dag.dag_id,
                                    "node_id": node.node_id,
                                    "error": node.error or "Unknown error",
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                }
                            )
                        )
                    except Exception:
                        pass
                logger.error("Node execution failed", node_id=node.node_id, error=str(e))

            node.completed_at = datetime.now(timezone.utc).isoformat()

    async def _attempt_self_healing(self, dag: DAGDefinition, node: DAGNode, error: str) -> bool:
        """Analyze failure and insert a dynamic self-healing node if possible."""
        if not node.constraints:
            node.constraints = {}

        # Backup original dependencies if not already backed up
        if "original_dependencies" not in node.constraints and not node.node_id.startswith("heal-"):
            node.constraints["original_dependencies"] = list(node.dependencies)

        from src.config import settings
        max_attempts = node.constraints.get("max_self_healing_attempts")
        if max_attempts is None:
            max_attempts = getattr(dag, "constraints", {}).get("max_self_healing_attempts")
        if max_attempts is None:
            max_attempts = getattr(settings, "max_self_healing_attempts", 3)

        # Check if the node is a healing node to prevent recursive healing loops
        if node.node_id.startswith("heal-"):
            logger.warning("Healing node itself failed, halting self-healing loop", node_id=node.node_id, error=error)
            # Find the original parent node depending on this healing node
            parent_node = None
            for n in dag.nodes:
                prefix = f"heal-{n.node_id}-"
                if node.node_id.startswith(prefix):
                    parent_node = n
                    break
            if parent_node:
                if not parent_node.constraints:
                    parent_node.constraints = {}
                parent_node.color = NodeColor.SUSPENDED
                parent_node.error = f"Healing node {node.node_id} failed: {error}"
                parent_node.constraints["self_healing_attempts"] = max_attempts
                self._rollback_self_healing(dag, parent_node)
            return False

        # Consecutive duplicate error check to prevent loops
        last_error = node.constraints.get("last_error")
        if last_error == error:
            logger.warning("Detected consecutive duplicate error during self-healing, halting loop", node_id=node.node_id, error=error)
            self._rollback_self_healing(dag, node)
            return False

        # Limit attempts to prevent infinite loop
        attempts = node.constraints.get("self_healing_attempts", 0)
        if attempts >= max_attempts:
            logger.warning("Self-healing attempts limit reached", node_id=node.node_id)
            self._rollback_self_healing(dag, node)
            return False

        attempts += 1
        node.constraints["self_healing_attempts"] = attempts

        # Record the error in constraints
        node.constraints["last_error"] = error

        delay = node.constraints.get("self_healing_delay")
        if delay is None:
            delay = getattr(dag, "constraints", {}).get("self_healing_delay")
        if delay is None:
            delay = getattr(settings, "self_healing_delay", 0.0)

        if delay and delay > 0:
            logger.info("Applying self-healing delay backoff", node_id=node.node_id, delay_seconds=delay)
            await asyncio.sleep(delay)

        # Query episodic memory for similar historical errors
        from src.core.memory.rag_manager import rag_manager
        history_context = ""
        try:
            matches = rag_manager.query_episodic_memory(error, limit=2, skill_id=node.skill_id)
            if matches:
                history_parts = []
                for m in matches:
                    score_info = f" (Similarity: {m['score']:.2f})" if "score" in m else ""
                    history_parts.append(
                        f"- 历史报错: {m['error_stack']}\n"
                        f"  任务上下文: {m['prompt']}\n"
                        f"  成功修复策略 (Patch/Command): {m['patch']}{score_info}"
                    )
                history_context = "\n### 历史相似报错及成功修复经验 (仅供参考):\n" + "\n\n".join(history_parts) + "\n"
        except Exception as rag_err:
            logger.error("Failed to query episodic memory for self-healing", error=str(rag_err))

        logger.info("Initiating self-healing diagnostics", node_id=node.node_id, attempt=attempts)

        # Build diagnostic prompt for LLM
        prompt = (
            f"You are the DAG Diagnostics Agent.\n"
            f"The node '{node.name}' (description: '{node.description}') failed with the following error:\n"
            f"'{error}'\n"
            f"{history_context}\n"
            f"Determine if this error can be healed by running a specific shell command (e.g. installing a package, creating a missing directory, etc.) OR by patching/improving the skill's system prompt (e.g., if the agent misunderstood instructions, needs extra validation rules, etc.).\n"
            f"If it can be healed via a shell command, output a JSON response in the following format:\n"
            f"{{\n"
            f"  \"can_heal\": true,\n"
            f"  \"healing_step_name\": \"Install package X\",\n"
            f"  \"healing_step_description\": \"pip install X\",\n"
            f"  \"skill_id\": \"shell_exec\",\n"
            f"  \"arguments\": {{\"command\": \"pip install X\"}}\n"
            f"}}\n"
            f"If it can be healed by patching the system prompt, output a JSON response in the following format:\n"
            f"{{\n"
            f"  \"can_heal\": true,\n"
            f"  \"should_patch_prompt\": true,\n"
            f"  \"patched_prompt\": \"[The complete new, improved system prompt incorporating instructions to avoid the error]\"\n"
            f"}}\n"
            f"If it cannot be healed or you are unsure, output:\n"
            f"{{\n"
            f"  \"can_heal\": false\n"
            f"}}\n"
            f"Return ONLY valid JSON."
        )

        try:
            import litellm
            import json
            from src.config import settings
            # Use configured default model
            model = self.model_override or settings.default_model
            
            response = await litellm.acompletion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            
            result_text = response.choices[0].message.content
            logger.info("Diagnostics result", content=result_text)
            data = json.loads(result_text)
            
            if data.get("can_heal"):
                # Resolve HITL requirement
                hitl_enabled = node.constraints.get("self_healing_hitl")
                if hitl_enabled is None:
                    hitl_enabled = getattr(dag, "constraints", {}).get("self_healing_hitl")
                if hitl_enabled is None:
                    hitl_enabled = getattr(settings, "self_healing_hitl_enabled", False)

                if data.get("should_patch_prompt"):
                    patched_prompt = data.get("patched_prompt")
                    if patched_prompt and node.skill_id:
                        if hitl_enabled:
                            from src.core.governance.approval import approval_manager
                            appr_id = await approval_manager.request_approval(
                                task_id=f"{dag.dag_id}:{node.node_id}:heal_prompt",
                                agent_id=f"skill:{node.skill_id}",
                                tool_name="patch_prompt",
                                arguments={"skill_id": node.skill_id, "node_id": node.node_id, "patched_prompt": patched_prompt},
                                priority=node.priority,
                                tenant_id=dag.tenant_id,
                                task_description=f"Self-Healing: Patch prompt of '{node.name}' to fix error: '{error}'",
                            )
                            node.color = NodeColor.ORANGE
                            self._publish_dag_status(dag)
                            granted = await approval_manager.wait_for_approval(appr_id)
                            if not granted:
                                logger.info("Self-healing prompt patch rejected by user", node_id=node.node_id)
                                self._rollback_self_healing(dag, node)
                                return False

                        from src.database import async_session
                        from src.core.evolution.ab_manager import ab_manager
                        async with async_session() as session:
                            variant = await ab_manager.fork_grey_skill(node.skill_id, patched_prompt, session)
                            if variant:
                                node.constraints["resolved_skill_id"] = variant["skill_id"]
                                logger.info("Self-healing applied prompt patch A/B fork", parent_id=node.skill_id, variant_id=variant["skill_id"])
                        
                        node.color = NodeColor.GRAY
                        self._publish_dag_status(dag)
                        return True
                    else:
                        logger.warning("Diagnostics requested prompt patch but missing patched_prompt or skill_id")
                        self._rollback_self_healing(dag, node)
                        return False

                if data.get("can_heal"):
                    healing_step_name = data.get("healing_step_name", "Self-Healing Step")
                    healing_step_description = data.get("healing_step_description", "")
                    skill_id = data.get("skill_id", "shell_exec")
                    
                    # Create healing node
                    healing_node_id = f"heal-{node.node_id}-{attempts}"
                    
                    if hitl_enabled:
                        from src.core.governance.approval import approval_manager
                        appr_id = await approval_manager.request_approval(
                            task_id=f"{dag.dag_id}:{healing_node_id}",
                            agent_id=f"skill:{skill_id}",
                            tool_name="execute_healing_node",
                            arguments={
                                "healing_node_id": healing_node_id,
                                "healing_step_name": healing_step_name,
                                "healing_step_description": healing_step_description,
                                "skill_id": skill_id,
                            },
                            priority=node.priority,
                            tenant_id=dag.tenant_id,
                            task_description=f"Self-Healing: Run '{healing_step_name}' ({healing_step_description}) to fix node '{node.name}' error",
                        )
                        node.color = NodeColor.ORANGE
                        self._publish_dag_status(dag)
                        granted = await approval_manager.wait_for_approval(appr_id)
                        if not granted:
                            logger.info("Self-healing execution node rejected by user", node_id=node.node_id)
                            self._rollback_self_healing(dag, node)
                            return False

                    healing_node = DAGNode(
                        node_id=healing_node_id,
                        name=healing_step_name,
                        skill_id=skill_id,
                        description=healing_step_description,
                        color=NodeColor.GRAY,
                        dependencies=list(node.dependencies),
                    )
                    
                    # Mutate original node dependencies to depend on the healing node
                    node.dependencies = [healing_node_id]
                    node.color = NodeColor.GRAY
                    
                    # Insert healing node into dag nodes list
                    dag.nodes.insert(dag.nodes.index(node), healing_node)
                    
                    # Add edge to dag.edges
                    from src.core.orchestrator.models import DAGEdge
                    dag.edges.append(DAGEdge(from_node=healing_node_id, to_node=node.node_id))
                    
                    logger.info(
                        "Dynamic DAG Mutation applied: inserted healing node",
                        healing_node_id=healing_node_id,
                        original_node_id=node.node_id
                    )
                    
                    # Publish DAG structure change
                    self._publish_dag_status(dag)
                    return True
                else:
                    logger.info("Diagnostics indicated error cannot be healed", node_id=node.node_id)
                    self._rollback_self_healing(dag, node)
                    return False
                
        except Exception as e:
            logger.error("Self-healing diagnostics failed", node_id=node.node_id, error=str(e))
            self._rollback_self_healing(dag, node)
             
        return False

    def _rollback_self_healing(self, dag: DAGDefinition, original_node: DAGNode):
        """Rollback all dynamically inserted healing nodes for the original node and restore original dependencies."""
        orig_deps = original_node.constraints.get("original_dependencies")
        if orig_deps is None:
            return

        original_node.dependencies = list(orig_deps)
        
        # Identify all heal nodes created for this node
        prefix = f"heal-{original_node.node_id}-"
        heal_node_ids = {n.node_id for n in dag.nodes if n.node_id.startswith(prefix)}
        
        # Remove these heal nodes from dag.nodes
        dag.nodes = [n for n in dag.nodes if n.node_id not in heal_node_ids]
        
        # Remove corresponding edges from dag.edges
        if hasattr(dag, "edges") and dag.edges:
            dag.edges = [e for e in dag.edges if e.from_node not in heal_node_ids and e.to_node not in heal_node_ids]
            
        logger.info("Rolled back dynamic healing nodes and restored dependencies", 
                    node_id=original_node.node_id, 
                    rolled_back_nodes=list(heal_node_ids))

    def _build_context_from_upstream(self, dag: DAGDefinition, node: DAGNode) -> str:
        """Assemble context from completed upstream nodes' results."""
        parts = []
        for dep_id in node.dependencies:
            dep_node = dag.get_node(dep_id)
            if dep_node and dep_node.result:
                output = dep_node.result.get("output", "")
                parts.append(f"## Result from [{dep_node.name}] (node: {dep_id})\n{output}")
        return "\n\n".join(parts) if parts else ""

    def _publish_dag_status(self, dag: DAGDefinition):
        """Publish overall DAG status change to the message bus."""
        from src.core.orchestrator.persistence import save_dag_to_disk
        import inspect
        try:
            sig = inspect.signature(save_dag_to_disk)
            if len(sig.parameters) == 1:
                save_dag_to_disk(dag)
            else:
                save_dag_to_disk(dag, dag.tenant_id)
        except Exception:
            try:
                save_dag_to_disk(dag, dag.tenant_id)
            except TypeError:
                save_dag_to_disk(dag)
        from src.core.agent.pool import agent_bus
        try:
            asyncio.create_task(
                agent_bus.publish(
                    topic="dag_updates",
                    sender_id="dag_engine",
                    payload={
                        "dag_id": dag.dag_id,
                        "node_id": None,
                        "color": None,
                        "dag_status": dag.status,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                )
            )
        except Exception:
            pass

    def _transition(self, dag: DAGDefinition, node: DAGNode, target: NodeColor):
        """Safely transition a node's color state."""
        if target in node.color.can_transition_to:
            old = node.color
            node.color = target
            logger.debug("State transition", node=node.node_id,
                        from_color=old.value, to_color=target.value)

            # Publish state transition to message bus
            from src.core.agent.pool import agent_bus
            try:
                asyncio.create_task(
                    agent_bus.publish(
                        topic="dag_updates",
                        sender_id="dag_engine",
                        payload={
                            "dag_id": dag.dag_id,
                            "node_id": node.node_id,
                            "color": target.value,
                            "role_id": getattr(node, "role_id", None),
                            "dag_status": dag.status,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        }
                    )
                )
            except Exception:
                pass
        else:
            logger.warning(
                "Invalid state transition",
                node=node.node_id,
                from_color=node.color.value,
                to_color=target.value,
            )

    def _validate_no_cycles(self, dag: DAGDefinition) -> bool:
        """Check for cycles using Kahn's algorithm (topological sort)."""
        in_degree: dict[str, int] = {n.node_id: 0 for n in dag.nodes}
        adj: dict[str, list[str]] = {n.node_id: [] for n in dag.nodes}

        for edge in dag.edges:
            adj[edge.from_node].append(edge.to_node)
            in_degree[edge.to_node] = in_degree.get(edge.to_node, 0) + 1

        # Also build from node dependencies
        for node in dag.nodes:
            for dep in node.dependencies:
                if dep in adj:
                    adj[dep].append(node.node_id)
                    in_degree[node.node_id] += 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        visited = 0

        while queue:
            nid = queue.pop(0)
            visited += 1
            for neighbor in adj.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return visited == len(dag.nodes)
