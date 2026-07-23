import logging
import os
import re
import json
import pandas as pd
from jobspy import scrape_jobs

# Configure logging
logger = logging.getLogger(__name__)


def search_jobs_tool(query: str, location: str = "", limit: int = 10):
    """
    Search job listings across multiple boards using python-jobspy with robust per-site fallback handling.
    Returns a JSON-formatted string of job dictionaries matching the given query and location.
    """
    candidate_sites = ["indeed", "linkedin"]
    if os.getenv("ZIPRECRUITER_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
        candidate_sites.append("zip_recruiter")

    # Format location string: e.g. "Wilmington DE" -> "Wilmington, DE"
    formatted_location = location.strip()
    if formatted_location and "," not in formatted_location:
        formatted_location = re.sub(r"([a-zA-Z\s]+)\s+([a-zA-Z]{2})$", r"\1, \2", formatted_location)

    collected_dfs = []

    def scrape_single_site(site: str, loc: str) -> pd.DataFrame | None:
        try:
            logger.info(f"Scraping '{site}' for query='{query}', location='{loc}'...")
            df = scrape_jobs(
                site_name=[site],
                search_term=query,
                location=loc,
                results_wanted=limit,
                country_indeed="USA"
            )
            if df is not None and not df.empty:
                logger.info(f"Successfully fetched {len(df)} jobs from '{site}'")
                return df
        except Exception as exc:
            logger.warning(f"Scraping '{site}' failed: {exc}")
        return None

    # Step 1: Scrape each site individually with exact location
    for site in candidate_sites:
        df = scrape_single_site(site, formatted_location)
        if df is not None:
            collected_dfs.append(df)

    # Step 2: Fallback to broader location (state/region) if exact location returned 0 results
    if not collected_dfs and formatted_location:
        state_match = re.search(r",\s*([a-zA-Z]{2})$", formatted_location)
        broader_loc = state_match.group(1) if state_match else formatted_location.split(",")[0].strip()
        logger.info(f"0 jobs found for exact location '{formatted_location}'. Retrying with broader location '{broader_loc}'...")
        for site in candidate_sites:
            df = scrape_single_site(site, broader_loc)
            if df is not None:
                collected_dfs.append(df)

    # Step 3: If still empty, attempt query without location constraint (Remote / Nationwide)
    if not collected_dfs:
        logger.info(f"Retrying query '{query}' without location constraint...")
        for site in candidate_sites:
            df = scrape_single_site(site, "")
            if df is not None:
                collected_dfs.append(df)

    if not collected_dfs:
        logger.warning(f"No jobs found for query '{query}' across all sites.")
        return json.dumps([])

    # Merge and deduplicate results across sites
    combined_df = pd.concat(collected_dfs, ignore_index=True)
    
    if "job_url" in combined_df.columns:
        combined_df = combined_df.drop_duplicates(subset=["job_url"], keep="first")
    if "title" in combined_df.columns and "company" in combined_df.columns:
        combined_df = combined_df.drop_duplicates(subset=["title", "company"], keep="first")

    # Sanitize Dataframe: Convert all values to JSON-serializable primitives (strings, ints, floats)
    raw_records = combined_df.to_dict(orient="records")
    clean_records = []

    for row in raw_records:
        clean_row = {}
        for key, val in row.items():
            if pd.isna(val) or val is None or str(val).lower() in ("nan", "nat", "<na>"):
                clean_row[key] = ""
            elif isinstance(val, (int, float, str, bool)):
                clean_row[key] = val
            else:
                clean_row[key] = str(val)
        clean_records.append(clean_row)

    # Return valid double-quoted JSON string
    return json.dumps(clean_records)
