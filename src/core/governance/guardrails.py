"""Guardrail Engine for Agent tool execution constraints.

Performs pre-execution analysis on tool inputs to enforce security policies (L0-L4).
"""

import os
import re
from typing import Any
import structlog

logger = structlog.get_logger()

# Sensitive/destructive shell command patterns (L4 - Forbidden)
FORBIDDEN_COMMAND_PATTERNS = [
    r"\brm\s+-[rf]*\s+(/|\*|\.|\.\.)(?:\s|$)",  # rm -rf / or similar
    r"\bsudo\b",                           # no sudo allowed
    r"\bmkfs\b",                           # no formatting
    r"\bdd\b",                             # dd command
    r"\bchown\b",                          # permission alterations
    r"\bchmod\b",
    r"\beval\b",                           # dynamic eval
    r"/dev/tcp/",                          # network tcp socket redirection
    r"/dev/udp/",                          # network udp socket redirection
    r"\bnc\b",                             # netcat
    r"\bnetcat\b",
    r"\bnmap\b",                           # network scanner
    r"\bnslookup\b",                       # dns query/exfiltration
    r"\bdig\b",
    r"\bhost\b",
]

# Sensitive/risky command patterns (L3 - Requires Approval)
RISKY_COMMAND_PATTERNS = [
    r"\brm\s+",            # any file removal
    r"\bmv\s+",            # move/rename
    r"\bcurl\b",           # network call
    r"\bwget\b",
    r"\bssh\b",
    r"\bpython\b.*-m\s+pip",  # installing libraries
    r"\bpoetry\b",
    r"\bnpm\b",
]

# Sensitive write paths requiring approval (L3)
SENSITIVE_WRITE_PATHS = [
    r"\.env$",
    r"src/config\.py$",
    r"pyproject\.toml$",
    r"alembic\.ini$",
]


class GuardrailEngine:
    """Evaluates security risk of tool executions and enforces policies."""

    def __init__(self):
        self._policy_uploaded = False

    def _upload_policy_to_opa(self) -> bool:
        """Uploads all Rego policies in the policies/ directory to the OPA server if enabled and running."""
        from src.config import settings
        if not settings.opa_enabled:
            return False

        policies_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "policies"
        )
        if not os.path.exists(policies_dir):
            logger.error("OPA policies directory not found", path=policies_dir)
            return False

        import urllib.request
        
        all_success = True
        for file_name in os.listdir(policies_dir):
            if not file_name.endswith(".rego"):
                continue
                
            policy_id = os.path.splitext(file_name)[0]
            policy_path = os.path.join(policies_dir, file_name)
            
            try:
                with open(policy_path, "r", encoding="utf-8") as f:
                    policy_content = f.read()
                
                url = f"{settings.opa_url.rstrip('/')}/v1/policies/{policy_id}"
                if not (url.startswith("http://") or url.startswith("https://")):
                    logger.error("Invalid OPA URL protocol scheme", url=url)
                    all_success = False
                    continue
                    
                req = urllib.request.Request(
                    url,
                    data=policy_content.encode("utf-8"),
                    headers={"Content-Type": "text/plain"},
                    method="PUT"
                )
                with urllib.request.urlopen(req, timeout=2.0) as response:  # nosec B310
                    if response.status not in [200, 201]:
                        logger.error("Failed to upload policy to OPA", policy_id=policy_id, status=response.status)
                        all_success = False
                    else:
                        logger.info("Successfully uploaded policy to OPA", policy_id=policy_id)
            except Exception as e:
                logger.warning("Could not upload policy to OPA. Is OPA running?", policy_id=policy_id, error=str(e))
                all_success = False
                
        return all_success

    def _evaluate_via_opa(self, tool_name: str, arguments: dict[str, Any], tenant_id: str = None, role: str = None) -> str | None:
        """Evaluate a tool execution using Open Policy Agent."""
        from src.config import settings
        if not settings.opa_enabled:
            return None

        if not self._policy_uploaded:
            self._policy_uploaded = self._upload_policy_to_opa()

        try:
            import urllib.request
            import json

            # If tenant_id is provided, construct tenant-specific workspace path
            if tenant_id and tenant_id != "00000000-0000-0000-0000-000000000000":
                workspace = os.path.join(settings.resolved_workspace_path, "tenants", tenant_id)
            else:
                workspace = settings.resolved_workspace_path

            ast_risk = None
            if tool_name == "shell_exec":
                command = arguments.get("command", "") or arguments.get("CommandLine", "") or arguments.get("cmd", "")
                ast_risk = self._evaluate_shell_command_ast(command)

            target_path = ""
            if tool_name in ["file_write", "file_read"]:
                target_path = arguments.get("target_path", "") or arguments.get("TargetFile", "") or arguments.get("path", "")
                target_path = self._sanitize_path(target_path)
                if target_path.startswith("/"):
                    target_path = os.path.abspath(target_path)

            input_data = {
                "input": {
                    "tool_name": tool_name,
                    "arguments": {
                        "target_path": target_path,
                        "command": arguments.get("command", "") or arguments.get("CommandLine", "") or arguments.get("cmd", "")
                    },
                    "workspace_path": workspace,
                    "whitelist_enabled": settings.guardrails_whitelist_enabled,
                    "whitelist_commands": settings.guardrails_whitelist_commands,
                    "parsed_command": {
                        "ast_risk": ast_risk
                    },
                    "tenant_id": tenant_id or "00000000-0000-0000-0000-000000000000",
                    "role": role or "viewer"
                }
            }

            url = f"{settings.opa_url.rstrip('/')}/v1/data/guardrails/risk_level"
            if not (url.startswith("http://") or url.startswith("https://")):
                logger.warning("Invalid OPA URL protocol scheme", url=url)
                return None
            req = urllib.request.Request(
                url,
                data=json.dumps(input_data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=2.0) as response:  # nosec B310
                if response.status == 200:
                    result = json.loads(response.read().decode("utf-8"))
                    decision = result.get("result")
                    if decision:
                        logger.info("OPA evaluated tool risk", tool_name=tool_name, decision=decision)
                        return str(decision)
        except Exception as e:
            logger.warning("OPA evaluation failed, falling back to local guardrails", error=str(e))

        return None

    def evaluate_api_permission(
        self,
        method: str,
        path: str,
        tenant_id: str,
        role: str,
        path_params: dict[str, str]
    ) -> bool:
        """Evaluate a REST API request against OPA api_auth rules."""
        from src.config import settings
        if not settings.opa_enabled:
            return True

        if not self._policy_uploaded:
            self._policy_uploaded = self._upload_policy_to_opa()

        try:
            import urllib.request
            import json

            input_data = {
                "input": {
                    "method": method,
                    "path": path,
                    "tenant_id": tenant_id or "00000000-0000-0000-0000-000000000000",
                    "role": role or "viewer",
                    "path_params": path_params or {}
                }
            }

            url = f"{settings.opa_url.rstrip('/')}/v1/data/api_auth/allow"
            if not (url.startswith("http://") or url.startswith("https://")):
                logger.warning("Invalid OPA URL protocol scheme", url=url)
                return False
            req = urllib.request.Request(
                url,
                data=json.dumps(input_data).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=2.0) as response:  # nosec B310
                if response.status == 200:
                    result = json.loads(response.read().decode("utf-8"))
                    decision = result.get("result")
                    return bool(decision)
        except Exception as e:
            logger.error("OPA API authorization evaluation failed", error=str(e))
            # Fail-closed in case of evaluation failure when OPA is explicitly enabled
            return False

        return False

    def _sanitize_path(self, path: str) -> str:
        """Sanitize path to decode Unicode escapes, URL encodings, prevent Null bytes, and normalize separators."""
        if not path:
            return ""
            
        path = path.replace("\x00", "")
        import urllib.parse
        
        for _ in range(3):
            old_path = path
            try:
                path = urllib.parse.unquote(path)
            except Exception:
                pass
            try:
                path = path.encode('utf-8', errors='ignore').decode('unicode-escape')
            except Exception:
                pass
            path = path.replace("\x00", "")
            if path == old_path:
                break
                
        return path.replace("\\", "/")

    def evaluate(self, tool_name: str, arguments: dict[str, Any], tenant_id: str = None, role: str = None) -> str:
        """Evaluate a tool execution and return risk level: L0, L1, L2, L3, L4."""
        # 0. Try OPA if enabled
        opa_decision = self._evaluate_via_opa(tool_name, arguments, tenant_id=tenant_id, role=role)
        if opa_decision is not None:
            return opa_decision

        # 1. Directory Listing / Read Tools -> L0 (No risk)
        if tool_name in ["directory_list", "file_read"]:
            return "L0"

        # 2. File Write Tools
        if tool_name == "file_write":
            target_path = arguments.get("target_path", "") or arguments.get("TargetFile", "") or arguments.get("path", "")
            target_path = self._sanitize_path(target_path)
            
            # Path traversal check (L4 - Forbidden)
            if ".." in target_path or target_path.startswith("~"):
                logger.warning("Guardrail block: Path traversal attempt", path=target_path)
                return "L4"
                
            if target_path.startswith("/"):
                from src.config import settings
                workspace = settings.resolved_workspace_path
                try:
                    import os
                    common = os.path.commonpath([os.path.abspath(target_path), workspace])
                    if common != workspace:
                        logger.warning("Guardrail block: Path outside workspace", path=target_path, workspace=workspace)
                        return "L4"
                except Exception:
                    logger.warning("Guardrail block: Path resolution failed", path=target_path)
                    return "L4"

            # Check sensitive write paths (L3 - Requires Approval)
            for pattern in SENSITIVE_WRITE_PATHS:
                if re.search(pattern, target_path):
                    logger.info("Guardrail trigger: Sensitive path write requiring approval", path=target_path)
                    return "L3"

            return "L1"

        # 3. Shell Exec Tool
        if tool_name == "shell_exec":
            command = arguments.get("command", "") or arguments.get("CommandLine", "")

            # Check Whitelist Mode first if enabled
            from src.config import settings
            if settings.guardrails_whitelist_enabled:
                matched_whitelist = False
                for pattern in settings.guardrails_whitelist_commands:
                    try:
                        if re.search(pattern, command, re.IGNORECASE):
                            matched_whitelist = True
                            break
                    except Exception as e:
                        logger.error("Invalid regex in guardrails_whitelist_commands", pattern=pattern, error=str(e))
                if not matched_whitelist:
                    logger.warning("Guardrail block: Command not allowed by whitelist policy", command=command)
                    return "L4"

            # Advanced AST & shlex Token analysis
            ast_risk = self._evaluate_shell_command_ast(command)
            if ast_risk == "L4":
                return "L4"

            # Check forbidden patterns (L4)
            for pattern in FORBIDDEN_COMMAND_PATTERNS:
                if re.search(pattern, command, re.IGNORECASE):
                    logger.warning("Guardrail block: Forbidden command pattern matched", command=command, pattern=pattern)
                    return "L4"

            # Check risky patterns (L3)
            regex_risk = "L2"
            for pattern in RISKY_COMMAND_PATTERNS:
                if re.search(pattern, command, re.IGNORECASE):
                    logger.info("Guardrail trigger: Risky command pattern matched requiring approval", command=command, pattern=pattern)
                    regex_risk = "L3"

            if ast_risk == "L3" or regex_risk == "L3":
                return "L3"

            return "L2"

        # Default fallback for other tools
        return "L1"

    def _evaluate_shell_command_ast(self, command: str) -> str | None:
        """Parse command and sub-commands recursively using AST & token scanning."""
        import shlex
        
        try:
            lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            tokens = list(lexer)
        except Exception as e:
            logger.warning("Guardrail block: Malformed shell command quotes/parsing error", command=command, error=str(e))
            return "L4"
            
        if not tokens:
            return None
            
        # Split tokens into segments by conjunctions/operators: ;, &&, ||, |, &, \n
        segments = []
        current_segment = []
        operators = [";", "&&", "||", "|", "&", "\n"]
        for token in tokens:
            if token in operators:
                if current_segment:
                    segments.append(current_segment)
                    current_segment = []
            else:
                current_segment.append(token)
        if current_segment:
            segments.append(current_segment)

        for segment in segments:
            if not segment:
                continue
            
            first_token = segment[0]
            cmd_name = os.path.basename(first_token)
            
            # Check variable command execution e.g. $CMD or ${CMD}
            if first_token.startswith("$") or first_token.startswith("${"):
                logger.warning("Guardrail block: Variable command execution attempt", token=first_token)
                return "L4"
            
            # Check standard forbidden commands
            if cmd_name in ["sudo", "mkfs", "dd", "chown", "chmod", "nc", "netcat", "nmap", "nslookup", "dig", "host"]:
                logger.warning("Guardrail block: Forbidden command token", token=first_token)
                return "L4"

            # Check other tokens in the segment for suspicious patterns
            for i, token in enumerate(segment):
                # Check for inline subcommand execution pattern e.g. `cmd` or $(cmd)
                if "`" in token or "$(" in token:
                    logger.info("Guardrail trigger: Inline subcommand execution matched", token=token)
                    return "L3"
                    
                # Check for redirection to sensitive file paths or outside workspace
                if token in [">", ">>", "<"] and i + 1 < len(segment):
                    target_file = segment[i+1]
                    cleaned_target = self._sanitize_path(target_file)
                    if cleaned_target.startswith("/") or ".." in cleaned_target:
                        from src.config import settings
                        workspace = settings.resolved_workspace_path
                        try:
                            abs_target = os.path.abspath(os.path.join(workspace, cleaned_target))
                            common = os.path.commonpath([abs_target, workspace])
                            if common != workspace:
                                logger.warning("Guardrail block: Redirecting output outside workspace", path=target_file)
                                return "L4"
                        except Exception:
                            return "L4"

            # Check network commands requiring approval
            if cmd_name in ["curl", "wget", "ssh"]:
                logger.info("Guardrail trigger: Network/remote command token requiring approval", token=first_token)
                return "L3"

            if cmd_name == "rm":
                # Check for destructive options or targets
                has_rf = False
                targets = []
                for j in range(1, len(segment)):
                    t = segment[j]
                    if t.startswith("-"):
                        if "r" in t or "f" in t:
                            has_rf = True
                    else:
                        targets.append(t)
                for target in targets:
                    cleaned_target = self._sanitize_path(target)
                    if cleaned_target in ["/", "*", ".", ".."] or cleaned_target.startswith("../"):
                        logger.warning("Guardrail block: Destructive rm target", target=target)
                        return "L4"
                return "L3"

            if cmd_name == "find" and "-delete" in segment:
                logger.warning("Guardrail block: Destructive find -delete matched")
                return "L4"

            # Check recursive shells
            if cmd_name in ["sh", "bash", "zsh", "dash"]:
                has_c = False
                sub_shell_cmd = None
                for j in range(1, len(segment)):
                    if segment[j] == "-c" and j + 1 < len(segment):
                        has_c = True
                        sub_shell_cmd = segment[j+1]
                        break
                if has_c and sub_shell_cmd is not None:
                    sub_risk = self._evaluate_shell_command_ast(sub_shell_cmd)
                    if sub_risk in ["L3", "L4"]:
                        return sub_risk
                else:
                    # Interactive or stdin shell launch, block as L4
                    logger.warning("Guardrail block: Shell execution without safe command script", token=first_token)
                    return "L4"

            # Check Python execution
            if cmd_name in ["python", "python3", "py"]:
                for j in range(1, len(segment)):
                    if segment[j] == "-c" and j + 1 < len(segment):
                        py_script = segment[j+1]
                        py_risk = self._evaluate_python_script_ast(py_script)
                        if py_risk in ["L3", "L4"]:
                            return py_risk
        return None

    def _evaluate_python_script_ast(self, script: str) -> str | None:
        """Parse Python inline script AST and block dangerous operations."""
        try:
            import ast
            parsed_ast = ast.parse(script)
            for node in ast.walk(parsed_ast):
                # 1. Imports
                if isinstance(node, ast.Import):
                    for name in node.names:
                        if name.name in ["os", "subprocess", "shutil", "sys", "pty", "importlib", "ctypes", "socket"]:
                            logger.warning("Guardrail block: Forbidden module import in python script", module=name.name)
                            return "L4"
                elif isinstance(node, ast.ImportFrom):
                    if node.module in ["os", "subprocess", "shutil", "sys", "pty", "importlib", "ctypes", "socket"]:
                        logger.warning("Guardrail block: Forbidden module import in python script", module=node.module)
                        return "L4"
                
                # 2. Function calls
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        if node.func.id in ["eval", "exec", "__import__", "open", "compile", "getattr", "setattr", "globals", "locals"]:
                            logger.warning("Guardrail block: Forbidden function call in python script", func=node.func.id)
                            return "L4"
                    elif isinstance(node.func, ast.Attribute):
                        if node.func.attr in ["system", "popen", "rmtree", "chmod", "chown", "remove", "unlink"]:
                            logger.warning("Guardrail block: Forbidden function attribute call in python script", func=node.func.attr)
                            return "L4"

                # 3. Subscript lookups
                elif isinstance(node, ast.Subscript):
                    slice_val = None
                    if hasattr(node, "slice"):
                        if isinstance(node.slice, ast.Constant):
                            slice_val = node.slice.value
                        elif isinstance(node.slice, ast.Index) and isinstance(node.slice.value, ast.Constant):
                            slice_val = node.slice.value.value
                    
                    if isinstance(slice_val, str) and slice_val in ["exec", "eval", "__import__", "open", "system", "popen", "os", "subprocess", "sys"]:
                        logger.warning("Guardrail block: Forbidden subscript lookup in python script", name=slice_val)
                        return "L4"
        except SyntaxError:
            logger.warning("Guardrail block: Python syntax error in inline script", script=script)
            return "L4"
        return None


guardrail_engine = GuardrailEngine()
