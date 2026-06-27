"""AgentDeepDive global configuration."""

import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── Application ──────────────────────────────────
    app_name: str = "AgentDeepDive"
    app_version: str = "0.1.0-alpha"
    api_key: str = ""  # PC to Mobile/dashboard authorization token (Bearer/X-API-Key)
    telegram_webhook_secret: str = ""  # X-Telegram-Bot-Api-Secret-Token validation
    debug: bool = True
    log_level: str = "INFO"
    jwt_secret: str = ""
    system_mode: str = "full"  # "full" or "lightweight"
    cors_origins: list[str] = ["*"]



    # ── PostgreSQL ───────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "agentdeep"
    postgres_user: str = "agentdeep"
    postgres_password: str = ""
    database_url_override: str | None = None

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        if self.system_mode == "lightweight":
            return "sqlite+aiosqlite:///agentdeep.db"
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Redis ────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    redis_ssl: bool = False
    redis_ssl_cert_reqs: str = "none"  # "none", "optional", "required"

    # ── Celery ───────────────────────────────────────
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_enabled: bool = True

    @property
    def redis_url(self) -> str:
        if self.redis_host.startswith("redis://") or self.redis_host.startswith("rediss://"):
            return self.redis_host
        scheme = "rediss" if self.redis_ssl else "redis"
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"{scheme}://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # ── Milvus ───────────────────────────────────────
    milvus_host: str = "localhost"
    milvus_port: int = 19530

    # ── LLM ──────────────────────────────────────────
    default_model: str = "claude-sonnet-4-20250514"
    fallback_model: str = "gpt-4o"
    local_model: str = ""  # e.g., "ollama/qwen2:72b"
    litellm_api_key: str = ""  # Set via LITELLM_API_KEY env var
    agnes_api_key: str = ""
    agnes_default_model: str = "agnes-2.0-flash"
    ux_visual_model: str = "agnes-image-2.1-flash"

    # ── Cloud LLM Providers ──────────────────────────
    openai_api_key: str = ""
    openai_api_base: str = ""
    anthropic_api_key: str = ""
    cohere_api_key: str = ""
    gemini_api_key: str = ""

    # ── Third-party SaaS Integrations ─────────────────
    notion_integration_token: str = ""
    airtable_api_key: str = ""
    airtable_base_id: str = ""
    supabase_url: str = ""
    supabase_key: str = ""

    # ── Budget ───────────────────────────────────────
    monthly_budget_usd: float = 500.0
    per_task_budget_usd: float = 2.0

    # ── Observability ────────────────────────────────
    otlp_endpoint: str = "http://localhost:4317"
    enable_tracing: bool = True

    # ── Multi-Channel HITL Approvals ──────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    slack_webhook_url: str = ""
    feishu_webhook_url: str = ""
    dingtalk_webhook_url: str = ""
    n8n_callback_url: str = ""
    app_external_url: str = "http://localhost:8000"

    # ── Channel Integration Extensions ────────────────
    discord_bot_token: str = ""
    discord_channel_id: str = ""
    discord_public_key: str = ""
    wechat_corp_id: str = ""
    wechat_corp_secret: str = ""
    wechat_agent_id: int = 0
    wechat_webhook_url: str = ""
    wechat_token: str = ""
    wechat_encoding_aes_key: str = ""
    qq_bot_appid: str = ""
    qq_bot_token: str = ""
    qq_channel_id: str = ""
    twitter_bearer_token: str = ""
    twitter_admin_userid: str = ""
    twitter_consumer_secret: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_admin_phone: str = ""
    whatsapp_verify_token: str = ""

    # ── Approval Governance ──────────────────────────
    auto_approve_l3: bool = False
    auto_approve_l4: bool = False
    opa_enabled: bool = False
    opa_url: str = "http://localhost:8181"
    guardrails_whitelist_enabled: bool = False
    max_self_healing_attempts: int = 3
    self_healing_delay: float = 0.0
    self_healing_hitl_enabled: bool = False
    guardrails_whitelist_commands: list[str] = [
        r"^ls(?:\s+.*)?$",
        r"^pwd$",
        r"^git(?:\s+.*)?$",
        r"^pytest(?:\s+.*)?$",
        r"^poetry\s+run\s+pytest(?:\s+.*)?$",
        r"^npm(?:\s+.*)?$",
        r"^python(?:\s+.*)?$",
        r"^python3(?:\s+.*)?$",
    ]

    # ── Contract Net Protocol (FIPA-ACL) ──────────────
    contract_net_enabled: bool = False
    contract_net_llm_bidding: bool = True

    # ── A/B Testing & Flywheel ────────────────────────
    ab_testing_enabled: bool = True
    ab_routing_weight: float = 0.2
    ab_min_eval_runs: int = 5

    # ── Three-Tiered Adaptive Routing ─────────────────
    adaptive_routing_enabled: bool = True
    adaptive_max_nodes_small: int = 5
    adaptive_max_files_small: int = 20
    adaptive_max_nodes_medium: int = 15
    adaptive_max_files_medium: int = 100

    # ── Docker Sandbox ───────────────────────────────
    docker_sandbox_enabled: bool = False
    docker_image: str = "python:3.11-slim"
    docker_cpu_limit: float = 1.0
    docker_memory_limit: str = "512m"
    docker_pids_limit: int = 100
    docker_security_no_new_privs: bool = True

    # ── Kubernetes Sandbox ────────────────────────────
    k8s_sandbox_enabled: bool = False
    k8s_namespace: str = "agentdeep"
    k8s_gvisor_enabled: bool = False
    k8s_runtime_class_name: str = "gvisor"
    k8s_volume_claim_name: str = ""
    k8s_host_path: str = ""
    k8s_cpu_limit: str = "1.0"
    k8s_memory_limit: str = "512Mi"
    k8s_cpu_request: str = "0.5"
    k8s_memory_request: str = "256Mi"

    # ── GitHub VCS Integration ───────────────────────
    github_token: str = ""
    github_repo: str = ""  # Format: "owner/repo"

    # ── Project Storage Workspace ─────────────────────
    project_workspace_path: str = ""

    @property
    def resolved_workspace_path(self) -> str:
        import os
        import platform
        if self.project_workspace_path:
            resolved = os.path.abspath(os.path.expanduser(self.project_workspace_path))
            os.makedirs(resolved, exist_ok=True)
            return resolved
        
        home = os.path.expanduser("~")
        if platform.system() == "Windows":
            fallback = os.path.join(home, "Desktop", "AgentDeepDiveProjects")
        else:
            fallback = os.path.join(home, "AgentDeepDiveProjects")
        
        os.makedirs(fallback, exist_ok=True)
        return os.path.abspath(fallback)
    model_config = {
        "env_prefix": "AGENTDEEP_",
        "env_file": str(Path(__file__).resolve().parent.parent / ".env"),
        "extra": "ignore"
    }

    def model_post_init(self, __context):
        # 1. Ensure JWT secret is set
        if not self.jwt_secret:
            import secrets
            self.jwt_secret = secrets.token_hex(32)

        # 2. Lightweight mode configuration overrides
        if self.system_mode == "lightweight":
            self.opa_enabled = False
            self.celery_enabled = False
        else:
            env_celery = os.getenv("AGENTDEEP_CELERY_ENABLED")
            if env_celery is not None:
                self.celery_enabled = env_celery.lower() in ("true", "1", "yes")
            
        # 3. Support ENABLE_FIPA_BIDDING to override contract_net_enabled
        env_fipa = os.getenv("ENABLE_FIPA_BIDDING")
        if env_fipa is not None:
            self.contract_net_enabled = env_fipa.lower() in ("true", "1", "yes")

        # 4. Fallback to standard Redis environment variables if AGENTDEEP_ ones are empty
        if not self.redis_password:
            self.redis_password = os.getenv("REDIS_PASSWORD") or os.getenv("REDIS_PASS") or ""
        env_redis_ssl = os.getenv("REDIS_SSL")
        if env_redis_ssl is not None:
            self.redis_ssl = env_redis_ssl.lower() in ("true", "1", "yes")
        env_redis_ssl_reqs = os.getenv("REDIS_SSL_CERT_REQS")
        if env_redis_ssl_reqs:
            self.redis_ssl_cert_reqs = env_redis_ssl_reqs.lower()


# Singleton
settings = Settings()

def apply_keys_to_env():
    import os
    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.openai_api_base:
        os.environ["OPENAI_API_BASE"] = settings.openai_api_base
    if settings.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    if settings.cohere_api_key:
        os.environ["COHERE_API_KEY"] = settings.cohere_api_key
    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    try:
        import litellm
        litellm.suppress_warnings = True
        if settings.openai_api_key:
            litellm.api_key = settings.openai_api_key
        if settings.openai_api_base:
            litellm.api_base = settings.openai_api_base
    except ImportError:
        pass

apply_keys_to_env()

# Register official CustomLLM provider for agnes models in litellm
try:
    import litellm
    from litellm import CustomLLM

    class AgnesLLM(CustomLLM):
        def completion(self, *args, **kwargs) -> litellm.ModelResponse:
            model = kwargs.get("model", "")
            if model.startswith("agnes/"):
                model = model[len("agnes/"):]
            kwargs["model"] = f"openai/{model}"
            if not kwargs.get("api_base"):
                kwargs["api_base"] = "https://api.agnes-ai.com/api/v1"
            if not kwargs.get("api_key"):
                kwargs["api_key"] = settings.agnes_api_key
            return litellm.completion(*args, **kwargs)

        async def acompletion(self, *args, **kwargs) -> litellm.ModelResponse:
            model = kwargs.get("model", "")
            if model.startswith("agnes/"):
                model = model[len("agnes/"):]
            kwargs["model"] = f"openai/{model}"
            if not kwargs.get("api_base"):
                kwargs["api_base"] = "https://api.agnes-ai.com/api/v1"
            if not kwargs.get("api_key"):
                kwargs["api_key"] = settings.agnes_api_key
            return await litellm.acompletion(*args, **kwargs)

    # Register custom provider in litellm
    litellm.custom_provider_map = getattr(litellm, "custom_provider_map", None) or []
    litellm.custom_provider_map.append({
        "provider": "agnes",
        "custom_handler": AgnesLLM()
    })

    # Register model aliases for all known agnes models
    litellm.model_alias_map = getattr(litellm, "model_alias_map", None) or {}
    for m in ["agnes-2.0-flash", "agnes-1.5-flash", "agnes-image-2.1-flash", "agnes-video-v2.0"]:
        litellm.model_alias_map[m] = f"agnes/{m}"
except ImportError:
    pass

