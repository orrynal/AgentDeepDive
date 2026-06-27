# Contributing to AgentDeepDive

[中文](CONTRIBUTING.zh.md) | English

Thank you for your interest in contributing to AgentDeepDive! As an enterprise-grade multi-agent orchestration platform for large-scale engineering, we welcome contributions of all kinds—from documentation improvements and bug fixes to core engine enhancements and security sandbox hardenings.

By participating in this project, you agree to abide by our Code of Conduct and follow these guidelines.

---

## 1. Development Workflow & Environment Setup

To start developing on AgentDeepDive:

### Step 1.1: Clone and Setup Workspace
Clone the repository and initialize the Python virtual environment (Python 3.11+ is required):
```bash
git clone <repository_url> agentdeepdive
cd agentdeepdive
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

### Step 1.2: Local Infrastructure Services
If you are developing features requiring container isolation, spin up the local PostgreSQL, Redis, Milvus, and Jaeger stack:
```bash
agentdeep infra up
agentdeep db upgrade head
```
For lightweight, zero-container offline debugging, simply run commands with the `-l` or `--lightweight` flag:
```bash
agentdeep run "your test prompt" -l
```

---

## 2. Coding Standards & Testing Guide

We maintain strict code quality and security verification baselines:

### 2.1 Code Style & Linters
We use `ruff` for formatting and linting. Before committing, ensure your code complies:
```bash
# Run formatter check
ruff format --check src/ tests/
# Run linter
ruff check src/ tests/
```

### 2.2 Test Suite Execution
Never submit a Pull Request without running the unit and integration tests. Ensure all tests pass:
```bash
pytest tests/unit/
```
For features involving the isolation sandbox, test with:
```bash
pytest tests/integration/
```

---

## 3. Custom Skills & OPA Policies Guidelines

If you are contributing new capability modules:

### 3.1 Submitting New Agent Skills
* Place your custom skill YAML inside `skills/<skill_name>/skill.yaml`.
* Define an explicit `skill_id` (e.g., `my-custom-skill-v1`).
* Restrict the tool privileges in `required_tools` to the minimum necessary set.
* Assign an appropriate `risk_level` (`low`, `medium`, or `high`).

### 3.2 Updating OPA Rego Policies
* Core governance rules are written in `src/core/governance/policies/guardrails.rego`.
* If you introduce a new system tool, add corresponding risk evaluation branches in the Rego policy.
* Test your rules against the input schema described in the [OPA Security Manual](docs/guides/security_opa_manual.md).

---

## 4. Git Branching & Commit Message Conventions

We strictly enforce the **Angular Commit Message Convention** to auto-generate changelogs and maintain version control integrity:

### 4.1 Commit Message Format
Each commit message must consist of a header containing a **type** and a **subject**:
```text
<type>: <short summary of changes>
```

### 4.2 Allowed Types
* `feat`: A new feature or capability module.
* `fix`: A bug fix.
* `docs`: Documentation changes only (e.g., updates to README, INSTALL, or Guides).
* `test`: Adding missing tests or correcting existing tests.
* `refactor`: A code change that neither fixes a bug nor adds a feature.
* `security`: Changes addressing security hardening, OPA, or sandbox escapes.
* `style`: Changes that do not affect the meaning of the code (formatting, missing semi-colons, etc.).

*Example:* `feat: integrate Telegram bot channel for L3 HITL approvals`

---

## 5. Pull Request Checklist

When submitting a Pull Request (PR):
1. **Create a feature branch** from `main` (e.g., `feature/hitl-slack-integration`).
2. **Add tests** for any new features or bug fixes.
3. **Update documentation** if you modified skills, environment variables, or CLI parameters.
4. Verify all linters (`ruff`) and tests (`pytest`) pass locally.
5. Submit the PR, describe the implementation logic in detail, and link to any relevant GitHub issues.
