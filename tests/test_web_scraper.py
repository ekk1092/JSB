import httpx
from unittest.mock import patch, MagicMock

from server.tools.web_scraper import scrape_job_description_tool, _get_retry_after


def _make_response(status_code=200, text="<html><body>Job text</body></html>", headers=None):
    """Create a mock httpx.Response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.text = text
    response.headers = headers or {}
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=response
        )
    return response


def test_get_retry_after_extracts_seconds():
    """_get_retry_after should parse the Retry-After header as seconds."""
    response = MagicMock(spec=httpx.Response)
    response.headers = {"Retry-After": "5"}
    assert _get_retry_after(response) == 5.0


def test_get_retry_after_returns_none_when_missing():
    """_get_retry_after should return None when the header is absent."""
    response = MagicMock(spec=httpx.Response)
    response.headers = {}
    assert _get_retry_after(response) is None


def test_get_retry_after_returns_none_for_http_date():
    """_get_retry_after should return None for non-numeric (HTTP-date) values."""
    response = MagicMock(spec=httpx.Response)
    response.headers = {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
    assert _get_retry_after(response) is None


def test_scrape_succeeds_on_first_try():
    """Scraping should return text content on a successful 200 response."""
    response = _make_response(status_code=200, text="<html><body><p>Software Engineer at Acme</p></body></html>")
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(return_value=response)

    with patch("server.tools.web_scraper.httpx.Client", return_value=mock_client):
        result = scrape_job_description_tool("https://example.com/job")

    assert "Software Engineer at Acme" in result


def test_scrape_retries_on_429_then_succeeds():
    """Scraping should retry on 429 and succeed when the next attempt returns 200."""
    resp_429 = _make_response(status_code=429, headers={"Retry-After": "0.01"})
    resp_200 = _make_response(status_code=200, text="<html><body>Job details</body></html>")

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(side_effect=[resp_429, resp_200])

    with patch("server.tools.web_scraper.httpx.Client", return_value=mock_client):
        with patch("server.tools.web_scraper.time.sleep"):
            result = scrape_job_description_tool("https://example.com/job")

    assert "Job details" in result
    assert mock_client.get.call_count == 2


def test_scrape_returns_friendly_error_after_exhausting_429_retries():
    """Scraping should return a user-friendly message after all 429 retries are exhausted."""
    resp_429 = _make_response(status_code=429, headers={"Retry-After": "0.01"})

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client.get = MagicMock(return_value=resp_429)

    with patch("server.tools.web_scraper.httpx.Client", return_value=mock_client):
        with patch("server.tools.web_scraper.time.sleep"):
            result = scrape_job_description_tool("https://example.com/job")

    assert "429" in result or "rate-limiting" in result.lower()