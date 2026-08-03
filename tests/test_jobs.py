import json
import pandas as pd
from unittest.mock import patch

from server.tools.jobs import search_jobs_tool


def test_search_jobs_returns_json_safe_records():
    """search_jobs_tool must return JSON-serializable records (no datetime/NaN)."""
    df = pd.DataFrame({
        "title": ["Software Engineer"],
        "company": ["Acme"],
        "date_posted": pd.to_datetime(["2026-08-01"]),
        "salary": [120000.0],
        "rating": [float("nan")],
    })

    with patch("server.tools.jobs.scrape_jobs", return_value=df):
        result = search_jobs_tool("engineer", "New York", 1)

    # Must be a list of dicts
    assert isinstance(result, list)
    assert isinstance(result[0], dict)

    # Must be JSON-serializable
    json.dumps(result)

    # datetime -> ISO string, NaN -> null
    assert result[0]["date_posted"] == "2026-08-01T00:00:00.000"
    assert result[0]["rating"] is None


def test_search_jobs_retries_on_failure():
    """search_jobs_tool should retry transient failures and return an error dict."""
    with patch(
        "server.tools.jobs.scrape_jobs",
        side_effect=Exception("network error"),
    ):
        result = search_jobs_tool("engineer", "New York", 1)

    assert isinstance(result, dict)
    assert "error" in result
    assert "network error" in result["error"]


def test_search_jobs_returns_partial_results_when_one_site_fails():
    """search_jobs_tool should keep working when one site fails."""
    df = pd.DataFrame({
        "title": ["Software Engineer"],
        "company": ["Acme"],
        "date_posted": pd.to_datetime(["2026-08-01"]),
        "salary": [120000.0],
        "rating": [float("nan")],
    })

    def fake_scrape_jobs(*, site_name, **kwargs):
        if site_name == "indeed":
            raise Exception("403 forbidden")
        return df

    with patch("server.tools.jobs.scrape_jobs", side_effect=fake_scrape_jobs):
        result = search_jobs_tool("engineer", "New York", 1)

    assert isinstance(result, list)
    assert result[0]["title"] == "Software Engineer"