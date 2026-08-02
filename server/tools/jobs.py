import json
import logging
from jobspy import scrape_jobs

# Configure logging
logger = logging.getLogger(__name__)


def search_jobs_tool(query: str, location: str = "", limit: int = 10):
    """
    Search job listings using python-jobspy.
    Returns the most recent job postings that match a given title or keyword.
    """
    jobs = scrape_jobs(
        site_name=["indeed", "linkedin", "zip_recruiter"],
        search_term=query,
        location=location,
        results_wanted=limit
    )
    # jobspy returns a DataFrame with datetime64 and float columns that are not
    # JSON-serializable. Convert to JSON-safe records (ISO dates, NaN -> null).
    return json.loads(
        jobs.to_json(orient="records", date_format="iso", default_handler=str)
    )

