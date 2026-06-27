import os
import pytest
from src.core.agent.tools import (
    _web_browser_navigate,
    _web_browser_click,
    _web_browser_input,
    _web_browser_screenshot,
    _web_browser_close,
    tool_registry
)

def test_browser_use_tools():
    # 1. Write a temporary HTML file for offline navigation testing
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        f.write(b"<html><head><title>Example Domain</title></head><body><h1>Example Domain</h1><p>Successfully navigated</p></body></html>")
        temp_path = f.name

    try:
        file_url = f"file://{temp_path}"
        
        # Test navigation to local temp HTML
        res = _web_browser_navigate(file_url)
        assert "Example Domain" in res
        assert "Successfully navigated" in res

        # 2. Test taking a screenshot
        screenshot_path = "test_screenshot.png"
        if os.path.exists(screenshot_path):
            os.remove(screenshot_path)

        res_ss = _web_browser_screenshot(screenshot_path)
        assert "Successfully saved page screenshot" in res_ss
        assert os.path.exists(screenshot_path)

        # Clean up screenshot
        if os.path.exists(screenshot_path):
            os.remove(screenshot_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    # 3. Test closing the browser
    res_close = _web_browser_close()
    assert "closed" in res_close.lower()

def test_registry_registration():
    # Verify tools are in registry
    assert tool_registry.get("web_browser_navigate") is not None
    assert tool_registry.get("web_browser_click") is not None
    assert tool_registry.get("web_browser_input") is not None
    assert tool_registry.get("web_browser_screenshot") is not None
    assert tool_registry.get("web_browser_close") is not None
