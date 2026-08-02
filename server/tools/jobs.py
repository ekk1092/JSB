import json
import logging
import time
from jobspy import scrape_jobs

# Configure logging
logger = logging.getLogger(__name__)

# Retry configuration for transient job-board failures
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


def search_jobs_tool(query: str, location: str = "", limit: int = 10):
    """
    Search job listings using python-jobspy.
    Returns the most recent job postings that match a given title or keyword.
    Retries transient failures up to MAX_RETRIES times with backoff.
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
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
        except Exception as e:
            last_error = e
            logger.warning(f"Job search attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    logger.error(f"Job search failed after {MAX_RETRIES} attempts: {last_error}")
    return {"error": f"Job search failed after {MAX_RETRIES} attempts: {last_error}"}

