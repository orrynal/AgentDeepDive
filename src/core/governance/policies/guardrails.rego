package guardrails

default risk_level = "L1"

# Role based constraints (viewer cannot write or execute)
risk_level = "L4" {
    input.role == "viewer"
    input.tool_name == "file_write"
}

risk_level = "L4" {
    input.role == "viewer"
    input.tool_name == "shell_exec"
}

# 1. Directory list and file read are L0
risk_level = "L0" {
    input.tool_name == "directory_list"
}
risk_level = "L0" {
    input.tool_name == "file_read"
}

# 2. File write rules
risk_level = "L4" {
    input.tool_name == "file_write"
    is_path_traversal(input.arguments.target_path)
}

risk_level = "L4" {
    input.tool_name == "file_write"
    is_path_outside_workspace(input.arguments.target_path, input.workspace_path)
}

risk_level = "L3" {
    input.tool_name == "file_write"
    is_sensitive_write_path(input.arguments.target_path)
}

risk_level = "L1" {
    input.tool_name == "file_write"
    not is_path_traversal(input.arguments.target_path)
    not is_path_outside_workspace(input.arguments.target_path, input.workspace_path)
    not is_sensitive_write_path(input.arguments.target_path)
}

# Helper functions for file write
is_path_traversal(path) {
    contains(path, "..")
}
is_path_traversal(path) {
    startswith(path, "~")
}

is_path_outside_workspace(path, workspace) {
    # If path starts with slash but not with workspace prefix
    startswith(path, "/")
    not startswith(path, workspace)
}

is_sensitive_write_path(path) {
    re_match(".*\\.env$", path)
}
is_sensitive_write_path(path) {
    re_match(".*src/config\\.py$", path)
}
is_sensitive_write_path(path) {
    re_match(".*pyproject\\.toml$", path)
}
is_sensitive_write_path(path) {
    re_match(".*alembic\\.ini$", path)
}

# 3. Shell execution rules
risk_level = "L4" {
    input.tool_name == "shell_exec"
    input.whitelist_enabled == true
    not matches_whitelist(input.arguments.command, input.whitelist_commands)
}

risk_level = "L4" {
    input.tool_name == "shell_exec"
    is_forbidden_command(input.arguments.command)
}

risk_level = "L4" {
    input.tool_name == "shell_exec"
    input.parsed_command.ast_risk == "L4"
}

risk_level = "L3" {
    input.tool_name == "shell_exec"
    not is_forbidden_command(input.arguments.command)
    input.parsed_command.ast_risk != "L4"
    is_risky_command(input.arguments.command)
}

risk_level = "L3" {
    input.tool_name == "shell_exec"
    not is_forbidden_command(input.arguments.command)
    input.parsed_command.ast_risk == "L3"
}

risk_level = "L2" {
    input.tool_name == "shell_exec"
    # if whitelist is enabled, must match whitelist
    # otherwise default to L2 if not forbidden / risky
    not is_forbidden_command(input.arguments.command)
    not is_risky_command(input.arguments.command)
    input.parsed_command.ast_risk != "L4"
    input.parsed_command.ast_risk != "L3"
    input.whitelist_enabled == false
}

risk_level = "L2" {
    input.tool_name == "shell_exec"
    not is_forbidden_command(input.arguments.command)
    not is_risky_command(input.arguments.command)
    input.parsed_command.ast_risk != "L4"
    input.parsed_command.ast_risk != "L3"
    input.whitelist_enabled == true
    matches_whitelist(input.arguments.command, input.whitelist_commands)
}

matches_whitelist(cmd, list) {
    re_match(list[_], cmd)
}

# Command checks
is_forbidden_command(cmd) {
    # forbidden command patterns (L4)
    re_match(".*\\b(sudo|mkfs|dd|chown|chmod|eval|nc|netcat|nmap|nslookup|dig|host)\\b.*", cmd)
}
is_forbidden_command(cmd) {
    re_match(".*(dev/tcp|dev/udp).*", cmd)
}
is_forbidden_command(cmd) {
    re_match(".*\\brm\\s+-[rf]*\\s+(/|\\*|\\.|\\.\\.)(?:\\s|$).*", cmd)
}

is_risky_command(cmd) {
    # risky command patterns (L3)
    re_match(".*\\b(rm|mv|curl|wget|ssh|poetry|npm)\\b.*", cmd)
}
is_risky_command(cmd) {
    re_match(".*\\bpython\\b.*-m\\s+pip.*", cmd)
}
