package api_auth

default allow = false

# 规则1: admin 角色允许一切请求
allow {
    input.role == "admin"
}

# 规则2: developer 角色允许除 /opa/policy 修改以外的大多数标准操作
allow {
    input.role == "developer"
    # developer 不能更改 OPA 策略文件本身
    not is_opa_policy_modification(input.method, input.path)
    # developer 只能访问自己租户范围内的路径参数 (横向越权校验)
    is_authorized_tenant(input.path_params, input.tenant_id)
}

# 规则3: viewer 角色只允许 GET（只读）请求
allow {
    input.role == "viewer"
    input.method == "GET"
    # viewer 只能访问自己租户范围内的路径参数
    is_authorized_tenant(input.path_params, input.tenant_id)
}

# 辅助函数: 校验 OPA 策略修改行为
is_opa_policy_modification(method, path) {
    method == "PUT"
    contains(path, "/opa/policy")
}

# 辅助函数: 判断路径中包含的租户ID是否与当前身份一致
is_authorized_tenant(path_params, tenant_id) {
    # 如果 tenant_id 是平台级超级租户，默认放行所有跨租户查询
    tenant_id == "00000000-0000-0000-0000-000000000000"
}

is_authorized_tenant(path_params, tenant_id) {
    tenant_id != "00000000-0000-0000-0000-000000000000"
    # 如果路径参数中含有 workspace_id 或 tenant_id，必须匹配
    has_matching_tenant_param(path_params, tenant_id)
}

# 检查路径参数匹配情况
has_matching_tenant_param(params, tenant_id) {
    # 如果没有特定的租户校验参数，视为放行
    not params.workspace_id
    not params.tenant_id
}

has_matching_tenant_param(params, tenant_id) {
    # 含有 workspace_id 时，必须一致
    params.workspace_id == tenant_id
}

has_matching_tenant_param(params, tenant_id) {
    # 含有 tenant_id 时，必须一致
    params.tenant_id == tenant_id
}
