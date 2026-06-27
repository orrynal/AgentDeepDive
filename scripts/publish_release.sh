#!/bin/bash
# scripts/publish_release.sh
# Automates the compilation of the clean release branch from main, 
# ensuring all sensitive documents are physically filtered and excluded.
# Design conforms strictly to docs/plans/git_history_cleaning_and_release_plan.md.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0;0m' # No Color

echo -e "${BLUE}=== Starting AgentDeepDive Release Publish Pipeline ===${NC}"

# 1. Ensure we are inside a git repository
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo -e "${RED}Error: Not in a git repository.${NC}"
    exit 1
fi

# Get the root directory of the repository
REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

# 2. Check if current branch is main
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ]; then
    echo -e "${RED}Error: You must run this script from the 'main' branch.${NC}"
    echo -e "${YELLOW}Currently on branch: $CURRENT_BRANCH${NC}"
    exit 1
fi

# 3. Check for uncommitted changes on main
if ! git diff-index --quiet HEAD --; then
    echo -e "${YELLOW}Warning: You have uncommitted changes in 'main'.${NC}"
    echo -e "${YELLOW}Please commit or stash your changes before proceeding.${NC}"
    exit 1
fi

# 4. Backup branches just in case
echo -e "${BLUE}Backing up current branches...${NC}"
git branch -f main-backup main
if git show-ref --verify --quiet refs/heads/release; then
    git branch -f release-backup release
fi

# 5. Create a clean temporary orphan branch
echo -e "${BLUE}Creating temporary clean orphan branch...${NC}"
# Delete temp branch if it already exists
git branch -D release-temp >/dev/null 2>&1 || true
git checkout --orphan release-temp

# 6. Check out code from main
echo -e "${BLUE}Importing latest file tree from main...${NC}"
git checkout main -- .

# 7. Physically purge blacklist files
echo -e "${BLUE}Purging sensitive blacklist files from temporary release branch...${NC}"

# Define files to delete
blacklist_files=(
    "docs/project_audit_report_20260622.md"
    "docs/project_audit_report_20260624.md"
    "docs/audit_report_resolution_status.md"
    "docs/project_code_audit_report.md"
    "docs/project_review.md"
    "docs/project_review_v2.md"
    "docs/project_review_v3.md"
    "docs/project_review_v4.md"
    "docs/discussion_log.md"
    "docs/issues_now.md"
    "docs/issues_all.md"
    "docs/issues_new.md"
    "docs/project_progress_log.md"
    "docs/project_progress_log_new.md"
    "docs/architecture_flowchart.md"
    "docs/comparison_harnessx_vs_agentdeepdive.md"
    "docs/implementation_plan.md"
    "docs/cli_analysis_and_implementation_plan.md"
    "docs/manus_lessons_implementation_plan.md"
    "docs/multi_tenant_rbac_design.md"
    "docs/multi_tenant_rbac_implementation_plan.md"
    "docs/role_system_implementation_plan.md"
    "docs/webui_design.md"
    "docs/future_roadmap_analysis.md"
    "docs/agent_deep_dive_part1.md"
    "docs/agent_deep_dive_part2.md"
    "docs/agent_planning_guide.md"
    "docs/agent_architecture_review.md"
    "docs/interactive_terminal_design.md"
    "scripts/find_unused_packages.py"
)

# Define directories to delete
blacklist_dirs=(
    "docs/plans"
    "docs/architecture"
    "docs/en/architecture"
)

for file in "${blacklist_files[@]}"; do
    if [ -f "$file" ]; then
        echo "Deleting private file: $file"
        rm -f "$file"
    fi
done

for dir in "${blacklist_dirs[@]}"; do
    if [ -d "$dir" ]; then
        echo "Deleting private directory: $dir"
        rm -rf "$dir"
    fi
done

# 8. Ensure release specific .gitignore is configured correctly
echo -e "${BLUE}Verifying .gitignore structure...${NC}"
# Make sure private files are in the .gitignore of the release branch
if ! grep -q "Private & Sensitive documentation" .gitignore; then
    echo -e "${YELLOW}Warning: Release blacklist comments not found in .gitignore, adding them...${NC}"
    cat >> .gitignore << 'EOF'

# Private & Sensitive documentation (strictly isolated locally)
docs/project_audit_report_*.md
docs/audit_report_resolution_status.md
docs/project_code_audit_report.md
docs/project_review*.md
docs/discussion_log.md
docs/issues_*.md
docs/project_progress_log*.md
docs/plans/
docs/architecture/
docs/en/architecture/
docs/architecture_flowchart.md
docs/comparison_harnessx_vs_agentdeepdive.md
docs/implementation_plan.md
docs/cli_analysis_and_implementation_plan.md
docs/manus_lessons_implementation_plan.md
docs/multi_tenant_rbac_*.md
docs/role_system_implementation_plan.md
docs/webui_design.md
docs/future_roadmap_analysis.md
docs/agent_deep_dive_part*.md
docs/agent_planning_guide.md
docs/agent_architecture_review.md
docs/interactive_terminal_design.md
EOF
fi

# 9. Commit the clean release
echo -e "${BLUE}Staging and committing squashed release...${NC}"
git add -A
# Remove any cached untracked items that shouldn't be here
git rm -r --cached . > /dev/null 2>&1 || true
git add .

git commit --no-verify -m "release: AgentDeepDive v0.1.0-alpha -- production-ready squashed release"

# 10. Swap branches and return to main
echo -e "${BLUE}Swapping release-temp to release branch...${NC}"
git branch -M release

echo -e "${BLUE}Returning to main branch...${NC}"
git checkout main

echo -e "${GREEN}=== Release Branch Successfully Prepared ===${NC}"
echo -e "Your local '${YELLOW}release${NC}' branch is now updated and clean of all sensitive documents."
echo -e "You can push it to the public repository using the following command:"
echo -e "  ${GREEN}git push origin release:main --force${NC}"
echo -e "================================================="
