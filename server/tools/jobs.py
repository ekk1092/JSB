import logging
import os
import re
import json
import urllib.parse
import httpx
import pandas as pd
from bs4 import BeautifulSoup
from jobspy import scrape_jobs

# Configure logging
logger = logging.getLogger(__name__)

CHROME_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
}


def scrape_indeed_rss(query: str, location: str, limit: int = 10) -> pd.DataFrame | None:
    """
    Fallback scraper for Indeed using its public RSS feed endpoints.
    """
    q_encoded = urllib.parse.quote(query)
    l_encoded = urllib.parse.quote(location)
    urls = [
        f"https://rss.indeed.com/rss?q={q_encoded}&l={l_encoded}",
        f"https://www.indeed.com/rss?q={q_encoded}&l={l_encoded}"
    ]

    for url in urls:
        try:
            logger.info(f"Attempting Indeed RSS feed fallback ({url}) for query='{query}', location='{location}'...")
            with httpx.Client(follow_redirects=True, headers=CHROME_HEADERS, timeout=10.0) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "xml")
                    items = soup.find_all("item")
                    records = []
                    for item in items[:limit]:
                        title_elem = item.find("title")
                        company_elem = item.find("source")
                        link_elem = item.find("link")
                        date_elem = item.find("pubDate")
                        desc_elem = item.find("description")

                        title = title_elem.text.strip() if title_elem else ""
                        company = company_elem.text.strip() if company_elem else "Indeed"
                        job_url = link_elem.text.strip() if link_elem else ""
                        date_posted = date_elem.text.strip() if date_elem else ""
                        desc = desc_elem.text.strip() if desc_elem else ""
                        if desc:
                            desc = BeautifulSoup(desc, "html.parser").get_text(separator=" ").strip()

                        records.append({
                            "title": title,
                            "company": company,
                            "location": location or "USA",
                            "job_url": job_url,
                            "date_posted": date_posted,
                            "description": desc[:500],
                            "site": "indeed"
                        })

                    if records:
                        logger.info(f"Successfully fetched {len(records)} jobs from Indeed RSS feed!")
                        return pd.DataFrame(records)
                else:
                    logger.warning(f"Indeed RSS ({url}) responded with status code {resp.status_code}")
        except Exception as exc:
            logger.warning(f"Indeed RSS fallback error for {url}: {exc}")

    return None


def scrape_indeed_via_duckduckgo(query: str, location: str, limit: int = 10) -> pd.DataFrame | None:
    """
    Search engine fallback indexing site:indeed.com listings via DuckDuckGo (HTML & Lite).
    Handles status codes 200 and 202 Accepted.
    """
    search_query = f'site:indeed.com/viewjob "{query}"'
    if location:
        search_query += f' "{location}"'

    urls = [
        f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(search_query)}",
        f"https://lite.duckduckgo.com/lite/?q={urllib.parse.quote(search_query)}"
    ]

    for url in urls:
        try:
            logger.info(f"Attempting Indeed search via DuckDuckGo fallback ({url}) for '{query}'...")
            with httpx.Client(follow_redirects=True, headers=CHROME_HEADERS, timeout=10.0) as client:
                resp = client.get(url)
                if resp.status_code in (200, 202):
                    soup = BeautifulSoup(resp.text, "html.parser")
                    links = soup.find_all("a")
                    records = []

                    for a in links:
                        href = a.get("href", "")
                        if "uddg=" in href:
                            match = re.search(r"uddg=([^&]+)", href)
                            if match:
                                href = urllib.parse.unquote(match.group(1))

                        if "indeed.com" in href and any(sub in href for sub in ["viewjob", "/rc/clk", "/cmp/", "/jobs", "/pagead/"]):
                            title = a.get_text(strip=True) or query
                            title_clean = re.sub(r"\s*\|\s*Indeed\.com.*$", "", title, flags=re.IGNORECASE)
                            title_clean = re.sub(r"^https?://.*$", query.title(), title_clean)
                            if not title_clean or len(title_clean) < 3:
                                title_clean = f"{query.title()} Position"

                            records.append({
                                "title": title_clean,
                                "company": "Indeed Job Listing",
                                "location": location or "USA",
                                "job_url": href,
                                "date_posted": "Recent",
                                "description": f"Indeed posting for {title_clean} in {location or 'USA'}",
                                "site": "indeed"
                            })
                            if len(records) >= limit:
                                break

                    if records:
                        logger.info(f"Successfully fetched {len(records)} Indeed jobs via DuckDuckGo fallback!")
                        return pd.DataFrame(records)
                else:
                    logger.warning(f"DuckDuckGo search ({url}) responded with status code {resp.status_code}")
        except Exception as exc:
            logger.warning(f"DuckDuckGo Indeed fallback error for {url}: {exc}")

    return None


def scrape_indeed_via_google(query: str, location: str, limit: int = 10) -> pd.DataFrame | None:
    """
    Search engine fallback indexing site:indeed.com/viewjob listings via Google Search.
    """
    search_query = f'site:indeed.com/viewjob "{query}"'
    if location:
        search_query += f' "{location}"'

    url = f"https://www.google.com/search?q={urllib.parse.quote(search_query)}"

    try:
        logger.info(f"Attempting Indeed search via Google Search fallback for '{query}'...")
        with httpx.Client(follow_redirects=True, headers=CHROME_HEADERS, timeout=10.0) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                links = soup.find_all("a")
                records = []

                for a in links:
                    href = a.get("href", "")
                    if "/url?q=" in href:
                        match = re.search(r"/url\?q=([^&]+)", href)
                        if match:
                            href = urllib.parse.unquote(match.group(1))

                    if "indeed.com" in href and any(sub in href for sub in ["viewjob", "/rc/clk", "/cmp/", "/jobs"]):
                        title = a.get_text(strip=True) or query
                        title_clean = re.sub(r"\s*\|\s*Indeed\.com.*$", "", title, flags=re.IGNORECASE)
                        title_clean = re.sub(r"^https?://.*$", query.title(), title_clean)
                        if not title_clean or len(title_clean) < 3:
                            title_clean = f"{query.title()} Position"

                        records.append({
                            "title": title_clean,
                            "company": "Indeed Job Listing",
                            "location": location or "USA",
                            "job_url": href,
                            "date_posted": "Recent",
                            "description": f"Indeed posting for {title_clean}",
                            "site": "indeed"
                        })
                        if len(records) >= limit:
                            break

                if records:
                    logger.info(f"Successfully fetched {len(records)} Indeed jobs via Google Search fallback!")
                    return pd.DataFrame(records)
    except Exception as exc:
        logger.warning(f"Google Indeed fallback error: {exc}")

    return None


def search_jobs_tool(query: str, location: str = "", limit: int = 10, site: str = ""):
    """
    Search job listings across multiple boards using python-jobspy with robust per-site fallback handling.
    Respects explicit target site requests ('indeed', 'linkedin') and includes multi-layer fallbacks for Indeed.
    Returns a JSON-formatted string of job dictionaries matching the given query and location.
    """
    requested_site = site.lower().strip()
    if not requested_site:
        if "indeed" in query.lower():
            requested_site = "indeed"
        elif "linkedin" in query.lower():
            requested_site = "linkedin"

    if requested_site in ["indeed", "linkedin"]:
        candidate_sites = [requested_site]
    else:
        candidate_sites = ["indeed", "linkedin"]
        if os.getenv("ZIPRECRUITER_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
            candidate_sites.append("zip_recruiter")

    # Format location string: e.g. "Wilmington DE" -> "Wilmington, DE"
    formatted_location = location.strip()
    if formatted_location and "," not in formatted_location:
        formatted_location = re.sub(r"([a-zA-Z\s]+)\s+([a-zA-Z]{2})$", r"\1, \2", formatted_location)

    collected_dfs = []

    def scrape_single_site(s: str, loc: str) -> pd.DataFrame | None:
        try:
            logger.info(f"Scraping '{s}' for query='{query}', location='{loc}'...")
            proxy = os.getenv("PROXY_URL")
            df = scrape_jobs(
                site_name=[s],
                search_term=query,
                location=loc,
                results_wanted=limit,
                country_indeed="USA",
                proxy=proxy if proxy else None
            )
            if df is not None and not df.empty:
                logger.info(f"Successfully fetched {len(df)} jobs from '{s}'")
                return df
        except Exception as exc:
            logger.warning(f"Scraping '{s}' failed: {exc}")

        # Fallback layers for Indeed if standard scrape is 403 blocked
        if s == "indeed":
            rss_df = scrape_indeed_rss(query, loc, limit)
            if rss_df is not None and not rss_df.empty:
                return rss_df
            
            ddg_df = scrape_indeed_via_duckduckgo(query, loc, limit)
            if ddg_df is not None and not ddg_df.empty:
                return ddg_df

            google_df = scrape_indeed_via_google(query, loc, limit)
            if google_df is not None and not google_df.empty:
                return google_df

        return None

    # Step 1: Scrape each site individually with exact location
    for s in candidate_sites:
        df = scrape_single_site(s, formatted_location)
        if df is not None:
            collected_dfs.append(df)

    # Step 2: Fallback to broader location (state/region) if exact location returned 0 results
    if not collected_dfs and formatted_location:
        state_match = re.search(r",\s*([a-zA-Z]{2})$", formatted_location)
        broader_loc = state_match.group(1) if state_match else formatted_location.split(",")[0].strip()
        logger.info(f"0 jobs found for exact location '{formatted_location}'. Retrying with broader location '{broader_loc}'...")
        for s in candidate_sites:
            df = scrape_single_site(s, broader_loc)
            if df is not None:
                collected_dfs.append(df)

    # Step 3: If still empty, attempt query without location constraint (Remote / Nationwide)
    if not collected_dfs:
        logger.info(f"Retrying query '{query}' without location constraint...")
        for s in candidate_sites:
            df = scrape_single_site(s, "")
            if df is not None:
                collected_dfs.append(df)

    if not collected_dfs:
        logger.warning(f"No jobs found for query '{query}' across candidate sites: {candidate_sites}")
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
