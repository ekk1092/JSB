import pytest
from unittest.mock import patch, MagicMock
from server.tools.web_scraper import scrape_job_description_tool
from server.tools.jobs import search_jobs_tool


def test_scrape_job_description_success():
    mock_html = "<html><body><h1>Software Engineer</h1><p>We are hiring!</p></body></html>"
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = mock_html
        mock_response.raise_for_status.return_value = None
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = scrape_job_description_tool("https://example.com/job/123")
        assert "Software Engineer" in result
        assert "We are hiring!" in result


def test_scrape_job_description_error():
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get.side_effect = Exception("Connection timeout")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        result = scrape_job_description_tool("https://example.com/job/error")
        assert "Error scraping URL" in result


def test_search_jobs_tool_empty():
    with patch("server.tools.jobs.scrape_jobs") as mock_scrape:
        mock_scrape.return_value = MagicMock(empty=True)
        results = search_jobs_tool("Software Engineer")
        assert results == []


def test_parse_job_search_request():
    from client_streamlit.app import parse_job_search_request
    parsed = parse_job_search_request("Help me finding a job in Data science field in Wilmington De")
    assert parsed["search_term"] == "Data science"
    assert parsed["location"] == "Wilmington De"
