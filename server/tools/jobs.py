import logging
from jobspy import scrape_jobs
import pandas as pd

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
    return jobs.to_dict(orient="records")

