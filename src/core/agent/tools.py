"""Tool Registry — defines tools that Agents can use.

Each tool is a callable with a name, description, and parameter schema.
Tools are registered centrally and assigned to Agents based on Skill requirements.
"""

import os
import subprocess
from pathlib import Path
from typing import Any
import contextvars

import structlog
from src.config import settings

logger = structlog.get_logger()

# Context variable to track the active task_id in the execution thread
current_task_id = contextvars.ContextVar("current_task_id", default="")
current_agent_id = contextvars.ContextVar("current_agent_id", default="")




class Tool:
    """A single tool that an Agent can invoke."""

    def __init__(self, name: str, description: str, func, parameters: dict | None = None):
        self.name = name
        self.description = description
        self.func = func
        self.parameters = parameters or {}

    async def execute(self, **kwargs) -> dict[str, Any]:
        """Execute the tool with given parameters."""
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, lambda: self.func(**kwargs))
            return {"status": "success", "output": result}
        except Exception as e:
            logger.error("Tool execution failed", tool=self.name, error=str(e))
            return {"status": "error", "error": str(e)}

    def to_llm_schema(self) -> dict:
        """Convert to LLM function-calling schema format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# ── Built-in Tool Implementations ────────────────────

def _file_read(path: str, max_lines: int = 500, start_line: int = 1) -> str:
    """Read a file's content starting from a specific 1-indexed line."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not p.is_file():
        raise ValueError(f"Not a file: {path}")

    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    start_idx = max(0, start_line - 1)
    target_lines = lines[start_idx : start_idx + max_lines]
    
    output = "\n".join(target_lines)
    if start_idx + max_lines < len(lines):
        remaining = len(lines) - (start_idx + max_lines)
        output += f"\n... ({remaining} more lines)"
    return output


def _directory_list(path: str, max_depth: int = 2) -> str:
    """List directory contents recursively up to max_depth."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Directory not found: {path}")

    lines = []
    def _walk(current: Path, depth: int, prefix: str = ""):
        if depth > max_depth:
            return
        try:
            entries = sorted(current.iterdir(), key=lambda e: (not e.is_dir(), e.name))
        except PermissionError:
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            marker = "📁 " if entry.is_dir() else "📄 "
            lines.append(f"{prefix}{marker}{entry.name}")
            if entry.is_dir():
                _walk(entry, depth + 1, prefix + "  ")

    _walk(p, 0)
    return "\n".join(lines[:200])


def _file_write(path: str, content: str) -> str:
    """Write content to a file (creates parent dirs if needed)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Written {len(content)} bytes to {path}"


def _file_patch(path: str, target: str, replacement: str) -> str:
    """Replace a specific target text block with replacement text in a file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not p.is_file():
        raise ValueError(f"Not a file: {path}")

    content = p.read_text(encoding="utf-8")
    if target not in content:
        raise ValueError(f"Target text block not found in file: {path}")
    
    count = content.count(target)
    if count > 1:
        raise ValueError(f"Target text block is not unique (found {count} occurrences) in file: {path}. Please provide a larger unique block to replace.")

    new_content = content.replace(target, replacement, 1)
    p.write_text(new_content, encoding="utf-8")
    return f"Successfully patched file {path}. Replaced 1 occurrence of target text."


def _shell_exec(command: str, cwd: str = ".", timeout: int = 30, _retry_count: int = 0) -> str:
    """Execute a shell command with timeout. Safe Sandboxed Routing supported."""
    from src.config import settings
    from src.core.workspace.runtime import sandbox_runtime_manager
    import asyncio

    workspace = settings.resolved_workspace_path
    abs_cwd = os.path.abspath(os.path.join(workspace, cwd))
    try:
        common = os.path.commonpath([abs_cwd, workspace])
        if common != workspace:
            abs_cwd = workspace
    except Exception:
        abs_cwd = workspace
    cwd = abs_cwd

    # Safety: block dangerous commands
    blocked = ["rm -rf", "mkfs", "dd if=", "> /dev/", "chmod 777"]
    for b in blocked:
        if b in command:
            raise ValueError(f"Blocked dangerous command: {command}")

    # Set up Redis client for real-time publishing
    task_id = current_task_id.get() or "unknown"
    agent_id = current_agent_id.get() or "unknown"
    r_pub = None
    if task_id and task_id != "unknown":
        try:
            from src.core.redis_pool import get_redis_client
            r_pub = get_redis_client()
        except Exception as ex:
            logger.warning("Failed to connect sync Redis for streaming", error=str(ex))

    def log_callback(line: str):
        if r_pub and task_id and task_id != "unknown":
            try:
                import json
                r_pub.publish(
                    "agentdeep:bus:terminal_updates",
                    json.dumps({
                        "sender_id": "shell_exec",
                        "topic": "terminal_updates",
                        "payload": {
                            "task_id": task_id,
                            "chunk": line
                        }
                    })
                )
            except Exception as ex:
                logger.debug("Failed to publish terminal update chunk", error=str(ex))

    # Safely execute async function in sync wrapper
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    if loop.is_running():
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as executor:
            def run_in_thread():
                new_loop = asyncio.new_event_loop()
                try:
                    return new_loop.run_until_complete(
                        sandbox_runtime_manager.execute_command(
                            command, cwd, task_id, agent_id, timeout, log_callback
                        )
                    )
                finally:
                    new_loop.close()
            returncode, output = executor.submit(run_in_thread).result()
    else:
        try:
            returncode, output = loop.run_until_complete(
                sandbox_runtime_manager.execute_command(
                    command, cwd, task_id, agent_id, timeout, log_callback
                )
            )
        finally:
            pass

    # Self-healing environment: check if execution failed due to missing package
    if returncode != 0 and _retry_count < 2:
        import re
        
        # 1. Python missing module
        py_match = re.search(r"ModuleNotFoundError: No module named '([^']+)'", output)
        if py_match:
            pkg = py_match.group(1)
            logger.info("Self-Healing: Detected missing python module, trying to install", module=pkg)
            
            if settings.docker_sandbox_enabled or settings.k8s_sandbox_enabled:
                new_command = f"pip install {pkg} && {command}"
                logger.info("Self-Healing: Prepending pip install in sandbox retry", new_command=new_command)
                return _shell_exec(new_command, cwd=cwd, timeout=timeout, _retry_count=_retry_count + 1)
            else:
                venv_dir = Path(__file__).parent.parent.parent.parent / ".venv"
                venv_bin = venv_dir / "bin"
                pip_cmd = str(venv_bin / "pip") if venv_bin.exists() else "pip"
                install_res = subprocess.run(
                    [pip_cmd, "install", pkg], capture_output=True, text=True, timeout=60
                )
                if install_res.returncode == 0:
                    logger.info("Self-Healing: Successfully installed module, retrying command", module=pkg)
                    return _shell_exec(command, cwd=cwd, timeout=timeout, _retry_count=_retry_count + 1)
                else:
                    logger.error("Self-Healing: Failed to install module", module=pkg, error=install_res.stderr)

        # 2. Node.js missing module
        node_match = re.search(r"Error: Cannot find module '([^']+)'", output)
        if node_match:
            pkg = node_match.group(1)
            logger.info("Self-Healing: Detected missing Node.js package, trying to install", package=pkg)
            
            if settings.docker_sandbox_enabled or settings.k8s_sandbox_enabled:
                new_command = f"npm install {pkg} && {command}"
                logger.info("Self-Healing: Prepending npm install in sandbox retry", new_command=new_command)
                return _shell_exec(new_command, cwd=cwd, timeout=timeout, _retry_count=_retry_count + 1)
            else:
                install_res = subprocess.run(
                    ["npm", "install", pkg], cwd=cwd, capture_output=True, text=True, timeout=60
                )
                if install_res.returncode == 0:
                    logger.info("Self-Healing: Successfully installed Node.js package, retrying command", package=pkg)
                    return _shell_exec(command, cwd=cwd, timeout=timeout, _retry_count=_retry_count + 1)
                else:
                    logger.error("Self-Healing: Failed to install Node.js package", package=pkg, error=install_res.stderr)

    if returncode != 0:
        output += f"\n(exit code: {returncode})"
    return output[:5000]  # Cap output size


def _git_checkout_branch(branch_name: str, create: bool = False, cwd: str = ".") -> str:
    """Checkout or create a Git branch."""
    cmd = ["git", "checkout"]
    if create:
        cmd.append("-b")
    cmd.append(branch_name)
    
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=15)
    if res.returncode != 0:
        return f"Error checking out branch: {res.stderr}"
    return f"Successfully checked out branch: {branch_name}"


def _git_commit(message: str, add_all: bool = True, cwd: str = ".") -> str:
    """Commit changes to the current Git branch."""
    if add_all:
        add_res = subprocess.run(["git", "add", "-A"], cwd=cwd, capture_output=True, text=True, timeout=15)
        if add_res.returncode != 0:
            return f"Error adding files to commit: {add_res.stderr}"
            
    res = subprocess.run(["git", "commit", "-m", message], cwd=cwd, capture_output=True, text=True, timeout=15)
    if res.returncode != 0:
        return f"Error committing changes: {res.stderr}"
    return f"Successfully committed changes: {res.stdout.strip()}"


def _git_push(remote: str = "origin", branch: str = "main", cwd: str = ".") -> str:
    """Push commits to a remote Git repository."""
    res = subprocess.run(["git", "push", remote, branch], cwd=cwd, capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        return f"Error pushing changes: {res.stderr}"
    return f"Successfully pushed changes to {remote}/{branch}"


def _github_create_pull_request(
    title: str, body: str, head_branch: str, base_branch: str = "main"
) -> str:
    """Create a pull request on GitHub."""
    import httpx
    
    token = settings.github_token
    repo = settings.github_repo
    
    if not token or not repo:
        return "Error: GitHub Integration not configured (AGENTDEEP_GITHUB_TOKEN or AGENTDEEP_GITHUB_REPO is missing)"
        
    if "/" not in repo:
        return f"Error: Invalid AGENTDEEP_GITHUB_REPO format '{repo}'. Expected 'owner/repo'"
        
    url = f"https://api.github.org/repos/{repo}/pulls"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {
        "title": title,
        "body": body,
        "head": head_branch,
        "base": base_branch
    }
    
    try:
        resp = httpx.post(url, headers=headers, json=data, timeout=15)
        if resp.status_code == 201:
            pr_data = resp.json()
            return f"Successfully created Pull Request: {pr_data.get('html_url')}"
        else:
            return f"Error creating Pull Request (HTTP {resp.status_code}): {resp.text}"
    except Exception as ex:
        return f"Exception during Pull Request creation: {str(ex)}"


def _query_knowledge_base(query: str, limit: int = 3) -> str:
    """Query semantic codebase specifications and guidelines."""
    from src.core.memory.rag_manager import rag_manager
    return rag_manager.query_knowledge_base(query, limit=limit)


def _web_search_ddg(query: str, max_results: int = 5) -> str:
    """Search the web for a given query using DuckDuckGo Lite.
    
    Returns a formatted string containing titles, URLs, and snippets of top search results.
    """
    import httpx
    from bs4 import BeautifulSoup
    
    url = "https://lite.duckduckgo.com/lite/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    data = {"q": query}
    
    try:
        resp = httpx.post(url, headers=headers, data=data, timeout=15)
        if resp.status_code != 200:
            return f"Error: DuckDuckGo search failed with status code {resp.status_code}"
            
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        links = soup.find_all("a", class_="result-link")
        snippets = soup.find_all("td", class_="result-snippet")
        
        count = min(len(links), len(snippets), max_results)
        if count == 0:
            for i, snip in enumerate(snippets[:max_results]):
                parent_tr = snip.find_parent("tr")
                if parent_tr:
                    prev_tr = parent_tr.find_previous_sibling("tr")
                    if prev_tr:
                        link_a = prev_tr.find("a", class_="result-link")
                        if link_a:
                            title = link_a.get_text(strip=True)
                            href = link_a.get("href", "")
                            if href.startswith("//duckduckgo.com/l/?uddg="):
                                from urllib.parse import parse_qs, urlparse
                                parsed = urlparse("https:" + href)
                                qs = parse_qs(parsed.query)
                                if "uddg" in qs:
                                    href = qs["uddg"][0]
                            elif href.startswith("/l/?uddg="):
                                from urllib.parse import parse_qs, urlparse
                                parsed = urlparse("https://duckduckgo.com" + href)
                                qs = parse_qs(parsed.query)
                                if "uddg" in qs:
                                    href = qs["uddg"][0]
                            snippet = snip.get_text(strip=True)
                            results.append(f"[{i+1}] Title: {title}\nURL: {href}\nSnippet: {snippet}\n")
        else:
            for i in range(count):
                link_a = links[i]
                title = link_a.get_text(strip=True)
                href = link_a.get("href", "")
                if href.startswith("//duckduckgo.com/l/?uddg="):
                    from urllib.parse import parse_qs, urlparse
                    parsed = urlparse("https:" + href)
                    qs = parse_qs(parsed.query)
                    if "uddg" in qs:
                        href = qs["uddg"][0]
                elif href.startswith("/l/?uddg="):
                    from urllib.parse import parse_qs, urlparse
                    parsed = urlparse("https://duckduckgo.com" + href)
                    qs = parse_qs(parsed.query)
                    if "uddg" in qs:
                        href = qs["uddg"][0]
                snippet = snippets[i].get_text(strip=True)
                results.append(f"[{i+1}] Title: {title}\nURL: {href}\nSnippet: {snippet}\n")
                
        if not results:
            return "No search results found."
            
        return "\n".join(results)
        
    except Exception as e:
        logger.error("web_search_ddg failed", query=query, error=str(e))
        return f"Error executing search: {str(e)}"


def _web_read_jina(url: str) -> str:
    """Read and convert a webpage to Markdown using Jina Reader API.
    
    Returns clean markdown content of the webpage.
    """
    import httpx
    
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
        
    jina_url = f"https://r.jina.ai/{url}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        resp = httpx.get(jina_url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return f"Error: Jina Reader failed with status code {resp.status_code}\nResponse: {resp.text[:200]}"
            
        content = resp.text
        if len(content) > 6000:
            content = content[:6000] + "\n\n... (content truncated for length)"
        return content
    except Exception as e:
        logger.error("web_read_jina failed", url=url, error=str(e))
        return f"Error reading webpage: {str(e)}"


# ── Browser Use Tools Implementation ──────────────────

class BrowserSessionManager:
    """Manages a single global browser page session for Agent tools."""

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.page = None

    def get_page(self):
        """Lazy init and return current browser page."""
        if self.page is not None:
            try:
                if not self.page.is_closed():
                    return self.page
            except Exception:
                pass
            self.close()

        try:
            from playwright.sync_api import sync_playwright
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=True)
            self.page = self.browser.new_page()
            self.page.set_default_timeout(15000)
            return self.page
        except Exception as e:
            logger.error("Failed to initialize Playwright browser session", error=str(e))
            raise RuntimeError(f"Playwright initialization failed: {e}")

    def close(self):
        """Close browser session."""
        try:
            if self.page:
                self.page.close()
        except Exception:
            pass
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        self.page = None
        self.browser = None
        self.playwright = None


browser_session = BrowserSessionManager()


def _web_browser_navigate(url: str) -> str:
    """Navigate to a specified URL and return page details (title and sample content)."""
    try:
        page = browser_session.get_page()
        page.goto(url, wait_until="networkidle")
        title = page.title()
        content = page.content()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        if len(text) > 1000:
            text = text[:1000] + "\n... (content truncated)"
        return f"Successfully navigated to {url}\nTitle: {title}\nContent Snippet:\n{text}"
    except Exception as e:
        logger.error("web_browser_navigate failed", url=url, error=str(e))
        return f"Error navigating to {url}: {str(e)}"


def _web_browser_click(selector: str) -> str:
    """Click an element matching the given selector."""
    try:
        page = browser_session.get_page()
        page.click(selector)
        return f"Successfully clicked selector '{selector}'"
    except Exception as e:
        logger.error("web_browser_click failed", selector=selector, error=str(e))
        return f"Error clicking selector '{selector}': {str(e)}"


def _web_browser_input(selector: str, text: str) -> str:
    """Type text into an element matching the given selector."""
    try:
        page = browser_session.get_page()
        page.fill(selector, text)
        return f"Successfully filled selector '{selector}' with text"
    except Exception as e:
        logger.error("web_browser_input failed", selector=selector, error=str(e))
        return f"Error filling selector '{selector}': {str(e)}"


def _web_browser_screenshot(path: str = "workspace_screenshot.png") -> str:
    """Take a screenshot of the current page and save to path."""
    try:
        page = browser_session.get_page()
        abs_path = os.path.abspath(path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        page.screenshot(path=abs_path)
        return f"Successfully saved page screenshot to {abs_path}"
    except Exception as e:
        logger.error("web_browser_screenshot failed", path=path, error=str(e))
        return f"Error taking screenshot: {str(e)}"


def _web_browser_close() -> str:
    """Close the current browser session."""
    browser_session.close()
    return "Browser session successfully closed."


# ── Tool Registry ────────────────────────────────────

class ToolRegistry:
    """Central registry of all available tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self._register_builtins()

    def _register_builtins(self):
        """Register all built-in tools."""
        self.register(Tool(
            name="file_read",
            description="Read the contents of a file at the given path",
            func=_file_read,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file"},
                    "max_lines": {"type": "integer", "description": "Max lines to read", "default": 500},
                    "start_line": {"type": "integer", "description": "1-based starting line number to read from", "default": 1},
                },
                "required": ["path"],
            },
        ))
        self.register(Tool(
            name="directory_list",
            description="List the contents of a directory recursively",
            func=_directory_list,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the directory"},
                    "max_depth": {"type": "integer", "description": "Max recursion depth", "default": 2},
                },
                "required": ["path"],
            },
        ))
        self.register(Tool(
            name="file_write",
            description="Write content to a file (creates parent directories if needed)",
            func=_file_write,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to write to"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        ))
        self.register(Tool(
            name="file_patch",
            description="Replace a unique target block of text with replacement text in an existing file. Use this instead of file_write for editing large files to avoid output token limits.",
            func=_file_patch,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file to modify"},
                    "target": {"type": "string", "description": "The exact block of text in the file to search for and replace"},
                    "replacement": {"type": "string", "description": "The text to replace the target block with"},
                },
                "required": ["path", "target", "replacement"],
            },
        ))
        self.register(Tool(
            name="shell_exec",
            description="Execute a shell command and return stdout/stderr",
            func=_shell_exec,
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "cwd": {"type": "string", "description": "Working directory", "default": "."},
                    "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
                },
                "required": ["command"],
            },
        ))
        self.register(Tool(
            name="git_checkout_branch",
            description="Checkout or create a Git branch",
            func=_git_checkout_branch,
            parameters={
                "type": "object",
                "properties": {
                    "branch_name": {"type": "string", "description": "Name of the branch"},
                    "create": {"type": "boolean", "description": "Create branch if it doesn't exist", "default": False},
                    "cwd": {"type": "string", "description": "Working directory", "default": "."},
                },
                "required": ["branch_name"],
            },
        ))
        self.register(Tool(
            name="git_commit",
            description="Commit tracked and untracked changes on the current Git branch",
            func=_git_commit,
            parameters={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message"},
                    "add_all": {"type": "boolean", "description": "Add all changes before commit", "default": True},
                    "cwd": {"type": "string", "description": "Working directory", "default": "."},
                },
                "required": ["message"],
            },
        ))
        self.register(Tool(
            name="git_push",
            description="Push the current Git branch to a remote repository",
            func=_git_push,
            parameters={
                "type": "object",
                "properties": {
                    "remote": {"type": "string", "description": "Remote name", "default": "origin"},
                    "branch": {"type": "string", "description": "Branch name", "default": "main"},
                    "cwd": {"type": "string", "description": "Working directory", "default": "."},
                },
            },
        ))
        self.register(Tool(
            name="github_create_pull_request",
            description="Create a Pull Request on GitHub",
            func=_github_create_pull_request,
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Pull Request title"},
                    "body": {"type": "string", "description": "Pull Request description body"},
                    "head_branch": {"type": "string", "description": "The branch where changes are implemented"},
                    "base_branch": {"type": "string", "description": "The branch you want to merge into", "default": "main"},
                },
                "required": ["title", "body", "head_branch"],
            },
        ))
        self.register(Tool(
            name="query_knowledge_base",
            description="Query the semantic codebase specifications and blueprints for this repository",
            func=_query_knowledge_base,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Semantic query describing the spec or design needed"},
                    "limit": {"type": "integer", "description": "Max snippets to retrieve", "default": 3},
                },
                "required": ["query"],
            },
        ))
        self.register(Tool(
            name="web_browser_navigate",
            description="Navigate to a specified URL and return page details (title and sample content)",
            func=_web_browser_navigate,
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to navigate to"},
                },
                "required": ["url"],
            },
        ))
        self.register(Tool(
            name="web_browser_click",
            description="Click an element matching the given CSS selector",
            func=_web_browser_click,
            parameters={
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the element to click"},
                },
                "required": ["selector"],
            },
        ))
        self.register(Tool(
            name="web_browser_input",
            description="Type text into an element matching the given CSS selector",
            func=_web_browser_input,
            parameters={
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the input element"},
                    "text": {"type": "string", "description": "The text to type"},
                },
                "required": ["selector", "text"],
            },
        ))
        self.register(Tool(
            name="web_browser_screenshot",
            description="Take a screenshot of the current browser page",
            func=_web_browser_screenshot,
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Filename or path to save the screenshot", "default": "workspace_screenshot.png"},
                },
            },
        ))
        self.register(Tool(
            name="web_browser_close",
            description="Close the active browser session",
            func=_web_browser_close,
            parameters={
                "type": "object",
                "properties": {},
            },
        ))
        self.register(Tool(
            name="web_search_ddg",
            description="Search the web for a given query using DuckDuckGo search engine",
            func=_web_search_ddg,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query term"},
                    "max_results": {"type": "integer", "description": "Maximum number of search results to return", "default": 5},
                },
                "required": ["query"],
            },
        ))
        self.register(Tool(
            name="web_read_jina",
            description="Fetch page markdown contents from a URL using Jina Reader API",
            func=_web_read_jina,
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Webpage URL to fetch content from"},
                },
                "required": ["url"],
            },
        ))

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_tools_for_skill(self, required_tools: list[str]) -> list[Tool]:
        """Get tool instances for a Skill's required_tools list."""
        return [self._tools[name] for name in required_tools if name in self._tools]

    def get_llm_schemas(self, tool_names: list[str] | None = None) -> list[dict]:
        """Get LLM function-calling schemas for specified tools (or all)."""
        tools = self._tools.values() if not tool_names else self.get_tools_for_skill(tool_names)
        return [t.to_llm_schema() for t in tools]


# Global singleton
tool_registry = ToolRegistry()
