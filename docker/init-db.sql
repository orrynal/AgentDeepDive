-- AgentDeepDive Database Initialization
-- This script runs automatically when PostgreSQL container starts for the first time

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Skills Table ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS skills (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    skill_id VARCHAR(128) UNIQUE NOT NULL,
    name VARCHAR(256) NOT NULL,
    version VARCHAR(32) NOT NULL DEFAULT '1.0.0',
    description TEXT,
    tags TEXT[] DEFAULT '{}',
    trigger_patterns TEXT[] DEFAULT '{}',
    context_budget INTEGER DEFAULT 8000,
    required_tools TEXT[] DEFAULT '{}',
    input_schema JSONB DEFAULT '{}',
    output_schema JSONB DEFAULT '{}',
    system_prompt TEXT,
    risk_level VARCHAR(16) DEFAULT 'low',
    approval_required BOOLEAN DEFAULT FALSE,
    estimated_tokens INTEGER DEFAULT 10000,
    estimated_duration_sec INTEGER DEFAULT 120,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Tasks Table ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id VARCHAR(128) UNIQUE NOT NULL,
    parent_task_id VARCHAR(128),
    skill_id VARCHAR(128) REFERENCES skills(skill_id),
    status VARCHAR(32) DEFAULT 'pending',
    color VARCHAR(16) DEFAULT 'gray',
    priority INTEGER DEFAULT 50,
    input_data JSONB DEFAULT '{}',
    output_data JSONB,
    error_message TEXT,
    dependencies TEXT[] DEFAULT '{}',
    constraints JSONB DEFAULT '{}',
    assigned_agent VARCHAR(128),
    tokens_used_input INTEGER DEFAULT 0,
    tokens_used_output INTEGER DEFAULT 0,
    model_used VARCHAR(64),
    cost_usd NUMERIC(10, 6) DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Execution Traces Table ──────────────────────────────
CREATE TABLE IF NOT EXISTS execution_traces (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trace_id VARCHAR(128) UNIQUE NOT NULL,
    task_id VARCHAR(128) REFERENCES tasks(task_id),
    agent_id VARCHAR(128) NOT NULL,
    step_number INTEGER NOT NULL,
    action VARCHAR(64) NOT NULL,
    input_summary TEXT,
    output_summary TEXT,
    reasoning TEXT,
    error TEXT,
    duration_ms INTEGER,
    tokens_used INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── DAG Definitions Table ───────────────────────────────
CREATE TABLE IF NOT EXISTS dag_definitions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dag_id VARCHAR(128) UNIQUE NOT NULL,
    name VARCHAR(256) NOT NULL,
    description TEXT,
    nodes JSONB NOT NULL DEFAULT '[]',
    edges JSONB NOT NULL DEFAULT '[]',
    status VARCHAR(32) DEFAULT 'draft',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Budget Tracking Table ───────────────────────────────
CREATE TABLE IF NOT EXISTS budget_records (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    period VARCHAR(7) NOT NULL,  -- e.g., '2026-06'
    model VARCHAR(64) NOT NULL,
    task_type VARCHAR(64),
    tokens_input INTEGER DEFAULT 0,
    tokens_output INTEGER DEFAULT 0,
    cost_usd NUMERIC(10, 6) DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Evaluation Results Table ────────────────────────────
CREATE TABLE IF NOT EXISTS evaluations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    eval_id VARCHAR(128) UNIQUE NOT NULL,
    trace_id VARCHAR(128),
    task_id VARCHAR(128),
    scores JSONB DEFAULT '{}',
    final_score NUMERIC(4, 3),
    verdict VARCHAR(32),
    failure_category VARCHAR(64),
    diagnosis JSONB,
    human_calibration JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Indexes ─────────────────────────────────────────────
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_color ON tasks(color);
CREATE INDEX idx_tasks_parent ON tasks(parent_task_id);
CREATE INDEX idx_traces_task ON execution_traces(task_id);
CREATE INDEX idx_traces_agent ON execution_traces(agent_id);
CREATE INDEX idx_budget_period ON budget_records(period);
CREATE INDEX idx_evaluations_task ON evaluations(task_id);
CREATE INDEX idx_skills_tags ON skills USING GIN(tags);
