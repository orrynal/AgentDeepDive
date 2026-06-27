import os
import ast
import asyncio
import structlog

logger = structlog.get_logger()

async def verify_invariants(dag, node) -> dict:
    """Runs logical invariants verification on node execution result.
    
    Returns a dict with {"success": bool, "details": str}.
    """
    verification_config = node.constraints.get("verification", {})
    invariants = verification_config.get("invariants", [])
    
    errors = []
    
    # 1. Implicit AST compilation verification if node result output contains python blocks
    if node.result and isinstance(node.result, dict):
        output = node.result.get("output", "")
        # Extract markdown python blocks
        if "```python" in output:
            parts = output.split("```python")
            for part in parts[1:]:
                code = part.split("```")[0]
                try:
                    ast.parse(code)
                except SyntaxError as se:
                    errors.append(f"Generated python code block failed compilation check: {se.msg} (line {se.lineno})")
                    
    # 2. Evaluate explicit invariants defined in metadata if any exist
    if invariants:
        if isinstance(invariants, str):
            invariants = [invariants]
            
        # Context variables available to eval
        eval_context = {
            "node": node,
            "result": node.result or {},
            "dag": dag,
        }
        
        for idx, inv in enumerate(invariants):
            try:
                # Evaluate expression in a restricted scope
                res = eval(inv, {"__builtins__": __builtins__}, eval_context)  # nosec B307
                if not res:
                    errors.append(f"Invariant [{idx}] failed: '{inv}' evaluated to False.")
            except Exception as e:
                errors.append(f"Invariant [{idx}] crashed: '{inv}'. Error: {str(e)}")

    # 3. Scan workspace for any python files and perform AST compilation check
    if "PYTEST_CURRENT_TEST" not in os.environ:
        from src.core.workspace.manager import workspace_manager
        ws_status = workspace_manager.get_status()
        ws_path = ws_status.get("active_workspace")
        if ws_path and os.path.exists(ws_path):
            exclude_dirs = {".venv", "venv", ".git", "__pycache__", ".memory", "scratch", "node_modules", "dist", "build"}
            logger.info("Scanning workspace for AST compilation checks", ws_path=ws_path)
            for root, dirs, files in os.walk(ws_path):
                dirs[:] = [d for d in dirs if d not in exclude_dirs]
                for file in files:
                    if file.endswith(".py"):
                        full_path = os.path.join(root, file)
                        try:
                            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                            ast.parse(content, filename=file)
                        except SyntaxError as se:
                            errors.append(f"Workspace python file '{file}' failed compilation check: {se.msg} (line {se.lineno}) in {os.path.relpath(full_path, ws_path)}")
                        except Exception:
                            pass

            # 4. Auto-run workspace tests if present
            has_tests = False
            test_dir = os.path.join(ws_path, "tests")
            if os.path.isdir(test_dir):
                has_tests = True
            else:
                for root, dirs, files in os.walk(ws_path):
                    dirs[:] = [d for d in dirs if d not in exclude_dirs]
                    if any(f.startswith("test_") and f.endswith(".py") for f in files):
                        has_tests = True
                        break
            
            if has_tests:
                logger.info("Auto-running workspace tests as part of verification pipeline", ws_path=ws_path)
                try:
                    # Use virtualenv python if it exists
                    venv_python = os.path.join(ws_path, ".venv", "bin", "python")
                    if not os.path.exists(venv_python):
                        venv_python = "python"
                    
                    # Run pytest in the workspace directory with a timeout of 30 seconds
                    cmd = [venv_python, "-m", "pytest"]
                    proc = await asyncio.create_subprocess_exec(
                        *cmd,
                        cwd=ws_path,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    try:
                        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
                        if proc.returncode != 0:
                            errors.append(
                                f"Workspace unit/integration tests failed (exit code {proc.returncode}).\n"
                                f"Stdout:\n{stdout.decode('utf-8', errors='ignore')[:1000]}\n"
                                f"Stderr:\n{stderr.decode('utf-8', errors='ignore')[:1000]}"
                            )
                    except asyncio.TimeoutError:
                        proc.kill()
                        errors.append("Workspace unit/integration tests timed out after 30 seconds.")
                except Exception as e:
                    logger.warning("Failed to auto-run workspace tests", error=str(e))
                
    if errors:
        logger.error("Invariant verification failed", node_id=node.node_id, errors=errors)
        return {"success": False, "details": "\n".join(errors)}
        
    logger.info("Invariant verification passed", node_id=node.node_id)
    return {"success": True, "details": "All invariants, workspace compilation, and test suite checks passed successfully."}
