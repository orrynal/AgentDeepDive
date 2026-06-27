#!/bin/bash
# Install Sandbox Cleanup Daemon to Crontab

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DAEMON_SCRIPT="${PROJECT_DIR}/scripts/sandbox_cleanup_daemon.py"
PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"

if [ ! -f "${PYTHON_BIN}" ]; then
    PYTHON_BIN="python3"
fi

# 1. Ensure the script is executable
chmod +x "${DAEMON_SCRIPT}"

# 2. Check if already installed in crontab
CRON_JOB="* * * * * ${PYTHON_BIN} ${DAEMON_SCRIPT} > /dev/null 2>&1"

if crontab -l 2>/dev/null | grep -F "${DAEMON_SCRIPT}" >/dev/null; then
    echo "Sandbox Cleanup Cron job is already installed."
else
    # Append the cron job to existing crontab
    (crontab -l 2>/dev/null; echo "${CRON_JOB}") | crontab -
    echo "Successfully installed Sandbox Cleanup Cron job to execute every minute."
fi
