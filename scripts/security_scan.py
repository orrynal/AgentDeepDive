#!/usr/bin/env python3
import sys
import subprocess
import re
import math

# Regular expressions for common sensitive structures
SECRETS_PATTERNS = {
    "AWS Access Key ID": r"([^A-Z0-9]|^)(AKIA|ASCA|ACCA|PTFE)[A-Z0-9]{16}([^A-Z0-9]|$)",
    "Slack Token": r"xox[bapr]-[0-9a-zA-Z]{10,48}",
    "GitHub PAT": r"gh[opr]_[0-9a-zA-Z]{36}",
    "Google API Key": r"AIza[0-9A-Za-z\\-_]{35}",
    "Generic Private Key": r"-----BEGIN[ A-Z0-9-_]+PRIVATE KEY-----",
    "Generic Secret Entropy/Assignment": r"(?i)(api_key|secret|password|passwd|private_key|token|auth_key|credentials)\s*[:=]\s*['\"]([^'\"]+)['\"]"
}

# Values that are explicitly safe to ignore (common test mock placeholders)
SAFE_PLACEHOLDERS = {
    "mock", "test", "your-", "dummy", "placeholder", "fake", "example", 
    "local", "default", "temp", "secret-value", "password-value"
}

def calculate_entropy(s: str) -> float:
    """Calculate the Shannon entropy of a string to detect high-entropy keys."""
    if not s:
        return 0.0
    entropy = 0.0
    for x in set(s):
        p_x = float(s.count(x)) / len(s)
        entropy -= p_x * math.log(p_x, 2)
    return entropy

def is_safe_value(val: str) -> bool:
    """Determine if a secret value is just a mock/placeholder."""
    val_lower = val.lower()
    if len(val) < 8:  # Too short to be a secure secret key
        return True
    for safe in SAFE_PLACEHOLDERS:
        if safe in val_lower:
            return True
    return False

def scan_diff() -> bool:
    """Scan staged file diffs for potential secrets and credentials."""
    print("Executing AgentDeepDive commit-stage security scan...")
    
    # Get list of staged files
    try:
        files = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only"], 
            text=True
        ).splitlines()
    except subprocess.CalledProcessError:
        print("Error checking staged files. Skipping scan.")
        return True

    violations = []
    
    for filename in files:
        if not filename.strip():
            continue
        # Skip security scanner itself and lockfiles/dependency files
        if "security_scan.py" in filename or "package-lock.json" in filename or "poetry.lock" in filename:
            continue
            
        try:
            # Get only the added/modified lines for this file in the staged change
            diff_lines = subprocess.check_output(
                ["git", "diff", "--cached", "-U0", filename],
                text=True
            ).splitlines()
        except subprocess.CalledProcessError:
            continue

        line_num = 0
        for line in diff_lines:
            # We are only interested in added lines starting with '+'
            if not line.startswith("+") or line.startswith("+++"):
                continue
                
            content = line[1:].strip()
            
            # Check against patterns
            for name, pattern in SECRETS_PATTERNS.items():
                match = re.search(pattern, content)
                if match:
                    # For assignment patterns, inspect the actual value assigned
                    if name == "Generic Secret Entropy/Assignment":
                        secret_val = match.group(2)
                        # Filter out placeholders, short strings, and low-entropy strings
                        if is_safe_value(secret_val):
                            continue
                        entropy = calculate_entropy(secret_val)
                        if entropy < 3.0:  # Structured text rather than random key
                            continue
                        
                        violations.append({
                            "file": filename,
                            "rule": f"Potential Secret Assignment (entropy: {entropy:.2f})",
                            "line": content
                        })
                    else:
                        # For direct high-risk patterns (like private keys or tokens)
                        violations.append({
                            "file": filename,
                            "rule": name,
                            "line": content
                        })
                        
    if violations:
        print("\n[!] SECURITY ALERT: Potential Secrets/Credentials Detected in Staged Changes!")
        print("Please check the following detections before committing:\n")
        for v in violations:
            print(f" File: {v['file']}")
            print(f" Rule: {v['rule']}")
            print(f" Line: {v['line']}")
            print("-" * 50)
        print("\nCommit aborted to protect sensitive information.")
        print("If these are true mock values, rewrite them to include 'mock', 'fake', or 'test' in the string.")
        return False

    print("Success: No active credentials or private keys detected in staged changes.")
    return True

if __name__ == "__main__":
    if not scan_diff():
        sys.exit(1)
    sys.exit(0)
