import os
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
import structlog

logger = structlog.get_logger()

async def run_e2e_tests(dag, node) -> dict:
    """Launches Playwright headless browser to run E2E steps and captures a screenshot.
    
    Returns a dict with {"success": bool, "details": str, "screenshot_path": str | None}.
    """
    verification_config = node.constraints.get("verification", {})
    e2e_script = verification_config.get("e2e", None)
    app_url = verification_config.get("app_url", "http://localhost:5174")  # Default to dashboard URL
    
    if not e2e_script and not verification_config.get("vlm_checks"):
        # If no E2E or VLM checks are requested, skip
        return {"success": True, "details": "No E2E test scripts defined.", "screenshot_path": None}

    logger.info("Starting E2E test runner", node_id=node.node_id, app_url=app_url)
    
    # Ensure verification screenshots directory exists in the public assets of the dashboard
    from src.config import settings
    screenshot_dir = Path(settings.resolved_workspace_path) / "dashboard" / "public" / "verification"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_filename = f"screenshot-{dag.dag_id}-{node.node_id}.png"
    screenshot_path = screenshot_dir / screenshot_filename
    
    success = True
    details = []
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1280, "height": 720})
            page = await context.new_page()
            
            # Navigate to the target application
            try:
                await page.goto(app_url, timeout=10000)
                await page.wait_for_timeout(2000)  # Wait for animations/load
                details.append(f"Successfully navigated to {app_url}")
            except Exception as navigation_err:
                success = False
                details.append(f"Failed to navigate to {app_url}: {str(navigation_err)}")
                await browser.close()
                return {"success": False, "details": "\n".join(details), "screenshot_path": None}
                
            # If an E2E script is defined as python/JS actions, we can run basic interactions
            # For simplicity, we can also execute custom Playwright steps defined in JSON
            steps = verification_config.get("steps", [])
            for idx, step in enumerate(steps):
                action = step.get("action")
                selector = step.get("selector")
                value = step.get("value")
                
                try:
                    if action == "click":
                        await page.click(selector, timeout=5000)
                        details.append(f"Step [{idx}] Clicked selector '{selector}'")
                    elif action == "type":
                        await page.fill(selector, value, timeout=5000)
                        details.append(f"Step [{idx}] Typed '{value}' into selector '{selector}'")
                    elif action == "wait":
                        await page.wait_for_selector(selector, timeout=5000)
                        details.append(f"Step [{idx}] Waited for selector '{selector}'")
                    await page.wait_for_timeout(500)
                except Exception as step_err:
                    success = False
                    details.append(f"Step [{idx}] Failed action '{action}' on '{selector}': {str(step_err)}")
                    
            # Capture the final state screenshot
            await page.screenshot(path=str(screenshot_path))
            details.append(f"Captured screenshot saved to dashboard: /verification/{screenshot_filename}")
            await browser.close()
            
    except Exception as playwright_err:
        success = False
        details.append(f"Playwright execution failed: {str(playwright_err)}")
        
    return {
        "success": success,
        "details": "\n".join(details),
        "screenshot_path": f"/verification/{screenshot_filename}" if screenshot_path.exists() else None
    }
