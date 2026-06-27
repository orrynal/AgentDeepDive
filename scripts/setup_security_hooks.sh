#!/bin/bash
# Install local pre-commit hook to trigger the Python security scanner
set -e

HOOK_DIR=".git/hooks"
PRE_COMMIT_HOOK="$HOOK_DIR/pre-commit"

if [ ! -d "$HOOK_DIR" ]; then
    echo "Error: .git directory not found. Please ensure you run this from the project root."
    exit 1
fi

echo "Installing AgentDeepDive pre-commit security hook..."

cat << 'EOF' > "$PRE_COMMIT_HOOK"
#!/bin/bash
# AgentDeepDive Staged Change Security Scan Hook
python3 scripts/security_scan.py
EOF

chmod +x "$PRE_COMMIT_HOOK"
chmod +x scripts/security_scan.py

echo "Security pre-commit hook installed successfully at $PRE_COMMIT_HOOK!"
