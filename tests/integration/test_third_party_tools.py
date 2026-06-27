import pytest
import httpx
from src.core.agent.tools import _web_search_ddg, _web_read_jina

@pytest.mark.anyio
async def test_web_search_ddg(monkeypatch):
    class MockResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code

    mock_html = """
    <table>
        <tr>
            <td>
                <a class="result-link" href="/l/?uddg=https://python.org">Python Programming</a>
            </td>
        </tr>
        <tr>
            <td class="result-snippet">Python is a programming language.</td>
        </tr>
    </table>
    """

    def mock_post(*args, **kwargs):
        return MockResponse(mock_html)

    monkeypatch.setattr(httpx, "post", mock_post)

    result = _web_search_ddg("python", max_results=2)
    assert "Title:" in result
    assert "URL:" in result
    assert "Snippet:" in result
    assert "No search results found" not in result

@pytest.mark.anyio
async def test_web_read_jina(monkeypatch):
    class MockResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code

    def mock_get(*args, **kwargs):
        return MockResponse("Example Domain - Markdown page from Jina Reader")

    monkeypatch.setattr(httpx, "get", mock_get)

    result = _web_read_jina("https://example.com")
    assert "Example Domain" in result
