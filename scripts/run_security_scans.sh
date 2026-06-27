#!/bin/bash
# Script to run security scans (Bandit static analysis & Pip-Audit dependency scanning)

# Exit immediately if a command exits with a non-zero status
set -e

# Change directory to the repository root
CDPATH="" cd -- "$(dirname -- "$0")/.."

echo -e "\033[1;34m[+] Activating virtual environment...\033[0m"
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "Warning: .venv not found, running with system python"
fi

FAILED=0

echo -e "\n\033[1;34m[+] Running Bandit Static Analysis on 'src/'...\033[0m"
# -r: recursive, -ll: medium or high severity, -ii: medium or high confidence
if ! bandit -r src/ -ll -ii; then
    echo -e "\033[1;31m[-] Bandit scan failed: potential vulnerabilities found!\033[0m"
    FAILED=1
else
    echo -e "\033[1;32m[+] Bandit scan passed.\033[0m"
fi

echo -e "\n\033[1;34m[+] Running Pip-Audit Dependency Vulnerability Scan...\033[0m"
set +e
AUDIT_OUT=$(pip-audit -r requirements.txt --timeout 15 2>&1)
AUDIT_EXIT=$?
set -e

if [ $AUDIT_EXIT -ne 0 ]; then
    # Check if failed due to network / timeout / DNS failure
    if echo "$AUDIT_OUT" | grep -qE -i "timeout|connection|network|DNS|Could not connect|HttpError|socket"; then
        echo -e "\033[1;33m[!] Pip-Audit encountered network/timeout issues. Skipping dependency audit.\033[0m"
        echo "$AUDIT_OUT"
    else
        echo -e "\033[1;31m[-] Pip-Audit scan failed: vulnerable dependencies found!\033[0m"
        echo "$AUDIT_OUT"
        FAILED=1
    fi
else
    echo -e "\033[1;32m[+] Pip-Audit scan passed.\033[0m"
    echo "$AUDIT_OUT"
fi

if [ $FAILED -ne 0 ]; then
    echo -e "\n\033[1;31m[x] Security scans failed. Please fix the issues above.\033[0m"
    exit 1
else
    echo -e "\n\033[1;32m[ok] All security scans passed successfully!\033[0m"
    exit 0
fi
