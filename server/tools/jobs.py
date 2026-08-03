import json
import logging
import time
from jobspy import scrape_jobs

# Configure logging
logger = logging.getLogger(__name__)

# Retry configuration for transient job-board failures
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2
DEFAULT_SITES = ["linkedin"]


def _scrape_single_site(site_name: str, query: str, location: str, limit: int):
    jobs = scrape_jobs(
        site_name=site_name,
        search_term=query,
        location=location,
        results_wanted=limit,
    )
    return json.loads(
        jobs.to_json(orient="records", date_format="iso", default_handler=str)
    )


def search_jobs_tool(query: str, location: str = "", limit: int = 10):
    """
    Search job listings using python-jobspy.
    Returns the most recent job postings that match a given title or keyword.
    Retries transient failures up to MAX_RETRIES times with backoff.
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            records = []
            errors = []

            for site_name in DEFAULT_SITES:
                try:
                    records.extend(_scrape_single_site(site_name, query, location, limit))
                except Exception as site_error:
                    errors.append(f"{site_name}: {site_error}")
                    logger.warning(
                        "Job search site %s failed on attempt %s/%s: %s",
                        site_name,
                        attempt,
                        MAX_RETRIES,
                        site_error,
                    )

            if records:
                return records

            if errors:
                raise RuntimeError("; ".join(errors))
            raise RuntimeError("No job sites returned any results")
        except Exception as e:
            last_error = e
            logger.warning(f"Job search attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    logger.error(f"Job search failed after {MAX_RETRIES} attempts: {last_error}")
    return {"error": f"Job search failed after {MAX_RETRIES} attempts: {last_error}"}

