import logging
import os
from jobspy import scrape_jobs
import pandas as pd

# Configure logging
logger = logging.getLogger(__name__)


def search_jobs_tool(query: str, location: str = "", limit: int = 10):
    """
    Search job listings using python-jobspy.
    Returns the most recent job postings that match a given title or keyword.
    """
    site_names = ["indeed", "linkedin"]
    if os.getenv("ZIPRECRUITER_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
        site_names.append("zip_recruiter")

    try:
        jobs = scrape_jobs(
            site_name=site_names,
            search_term=query,
            location=location,
            results_wanted=limit
        )
    except Exception as exc:
        message = str(exc).lower()
        if "ziprecruiter" in message or "forbidden" in message or "403" in message:
            logger.warning("ZipRecruiter blocked the request; retrying without it.")
            jobs = scrape_jobs(
                site_name=[site for site in site_names if site != "zip_recruiter"],
                search_term=query,
                location=location,
                results_wanted=limit
            )
        else:
            raise

    return jobs.to_dict(orient="records")

