import json
import logging
import re
import time
from jobspy import scrape_jobs

# Configure logging
logger = logging.getLogger(__name__)

# Retry configuration for transient job-board failures
MAX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1
CANDIDATE_SITES = ["linkedin", "indeed", "glassdoor", "zip_recruiter"]


def _sanitize_location(location: str) -> str:
    if not location:
        return ""
    loc = location.lower().strip()
    vague_phrases = [
        "my area", "in my area", "near me", "my location",
        "current location", "local", "area", "around me", "here"
    ]
    for phrase in vague_phrases:
        loc = loc.replace(phrase, "")
    loc = re.sub(r"^\s*(in|at|near|around)\s*", "", loc, flags=re.IGNORECASE).strip()
    return loc


def _sanitize_query(query: str) -> str:
    if not query or not re.search(r"[a-zA-Z0-9]", query):
        return "Data Analyst"

    q = query.strip()

    # Remove negative constraint or conversational phrases
    constraint_patterns = [
        r"don'?t\s+give\s+me\s+jobs\s+that\s+need\s+clearance",
        r"don'?t\s+give\s+me\s+jobs\s+with\s+clearance",
        r"no\s+(security\s+)?clearance",
        r"without\s+(security\s+)?clearance",
        r"i\s+don'?t\s+have\s+(us\s+)?citizenship",
        r"no\s+(us\s+)?citizenship",
        r"need(s)?\s+clearance",
        r"clearance",
        r"citizenship",
    ]
    for pattern in constraint_patterns:
        q = re.sub(pattern, "", q, flags=re.IGNORECASE).strip()

    # Replace conversational prefixes
    prefixes = [
        r"^(give|find|show|get)\s+(me\s+)?(recent\s+)?jobs\s+(in|for)\s+",
        r"^(recent\s+)?jobs\s+(in|for)\s+",
        r"^jobs\s+(in|for)\s+",
        r"^jobs\s*",
    ]
    for p in prefixes:
        q = re.sub(p, "", q, flags=re.IGNORECASE).strip()

    # Map generic sector, ordinal selections, or emptied phrases to searchable role titles
    is_ordinal = bool(re.match(r"^(the\s+)?(\d+(st|nd|rd|th)?|first|second|third|fourth|fifth|last|one|two|three)(\s+(one|option|position|role|job))?$", q, flags=re.IGNORECASE))
    if not q or is_ordinal or q.lower() in ["data sector", "the data sector", "data", "it", "tech", "role", "option 1", "option 2", "option 3"]:
        return "Data Analyst"

    return q


def _scrape_single_site(site_name: str, query: str, location: str, limit: int):
    jobs = scrape_jobs(
        site_name=site_name,
        search_term=query,
        location=location,
        results_wanted=limit,
    )
    if jobs is None or jobs.empty:
        return []
    jobs = jobs.fillna("")
    records = json.loads(
        jobs.to_json(orient="records", date_format="iso", default_handler=str)
    )
    for r in records:
        if not r.get("job_url"):
            r["job_url"] = r.get("url") or r.get("job_url_direct") or ""
        for key in ["title", "company", "location", "description"]:
            if isinstance(r.get(key), str):
                r[key] = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", r[key])
    return records


def search_jobs_tool(
    query: str,
    location: str = "",
    limit: int = 10,
    no_clearance: bool = False,
    work_type: str = "All"
) -> list:
    """
    Search job listings using python-jobspy with multi-site fallback, sanitization, and preference filtering.
    Returns a list of job dictionaries with title, company, location, job_url, description.
    """
    clean_query = _sanitize_query(query)
    clean_location = _sanitize_location(location)

    logger.info("Searching jobs for query='%s' (raw='%s'), location='%s' (raw='%s'), no_clearance=%s, work_type='%s'",
                clean_query, query, clean_location, location, no_clearance, work_type)

    records = []
    errors = []

    # Attempt candidate sites until we find job listings
    for site_name in CANDIDATE_SITES:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                site_records = _scrape_single_site(site_name, clean_query, clean_location, limit)
                if site_records:
                    logger.info("Successfully fetched %d jobs from '%s'", len(site_records), site_name)
                    records.extend(site_records)
                    break
            except Exception as site_error:
                logger.warning("Scraping '%s' failed (attempt %d/%d): %s", site_name, attempt, MAX_RETRIES, site_error)
                errors.append(f"{site_name}: {site_error}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS)
        
        if len(records) >= limit:
            break

    # Fallback retry if primary search returned 0 records
    if not records:
        logger.info("Retrying query '%s' with broadened fallback search...", clean_query)
        fallback_loc = "" if clean_location else ""
        for site_name in CANDIDATE_SITES:
            try:
                site_records = _scrape_single_site(site_name, clean_query, fallback_loc, limit)
                if site_records:
                    records.extend(site_records)
                    break
            except Exception as fallback_err:
                logger.warning("Fallback scraping '%s' failed: %s", site_name, fallback_err)

    if not records:
        logger.warning("No jobs found for query '%s' across candidate sites.", clean_query)
        return []

    # Apply Preference Filters
    filtered_records = []
    for r in records:
        text_comb = f"{r.get('title', '')} {r.get('description', '')}".lower()
        
        # Security Clearance Filter
        if no_clearance and any(k in text_comb for k in ["clearance required", "security clearance", "secret clearance", "ts/sci", "top secret"]):
            continue
            
        # Work Type Filter
        if work_type == "Remote":
            is_remote_flag = r.get("is_remote") or "remote" in r.get("location", "").lower() or "remote" in text_comb
            if not is_remote_flag:
                continue
        elif work_type == "Hybrid":
            if "hybrid" not in text_comb and "hybrid" not in r.get("location", "").lower():
                continue
        elif work_type == "On-site":
            if "remote" in text_comb or "hybrid" in text_comb or r.get("is_remote"):
                continue

        filtered_records.append(r)

    # Return filtered set, falling back to unfiltered if filter was overly restrictive
    return filtered_records if filtered_records else records



