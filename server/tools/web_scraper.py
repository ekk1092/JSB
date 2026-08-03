import logging
import time
import httpx
from bs4 import BeautifulSoup

# Configure logging
logger = logging.getLogger(__name__)

# Retry configuration for HTTP 429 (Too Many Requests) from job boards.
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 2.0

# A realistic, modern browser User-Agent to reduce the chance of being blocked.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _get_retry_after(response: httpx.Response) -> float | None:
    """Extract the Retry-After header value (seconds) if present."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    # Retry-After can be a delay in seconds or an HTTP-date
    try:
        return float(raw)
    except ValueError:
        return None


def scrape_job_description_tool(url: str) -> str:
    """
    Scrapes the job description from a given URL.

    Handles HTTP 429 (Too Many Requests) by retrying with exponential backoff,
    respecting the Retry-After header when provided by the server.

    Args:
        url: The URL of the job posting.

    Returns:
        The text content of the job description, or an error message.
    """
    logger.info(f"Scraping job description from {url}")

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with httpx.Client(follow_redirects=True, headers=DEFAULT_HEADERS, timeout=30) as client:
                response = client.get(url)

                # Handle 429 Too Many Requests with retry
                if response.status_code == 429:
                    retry_after = _get_retry_after(response)
                    wait = retry_after if retry_after else (BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                    logger.warning(
                        "Scrape received 429 (attempt %d/%d). Retrying in %.1fs",
                        attempt, MAX_RETRIES, wait,
                    )
                    if attempt < MAX_RETRIES:
                        time.sleep(wait)
                        continue
                    else:
                        return (
                            "The job board is rate-limiting requests (HTTP 429). "
                            "Please try again in a few minutes."
                        )

                response.raise_for_status()

                soup = BeautifulSoup(response.text, "html.parser")

                # Remove script and style elements
                for script in soup(["script", "style"]):
                    script.decompose()

                # Get text
                text = soup.get_text(separator="\n")

                # Break into lines and remove leading/trailing space on each
                lines = (line.strip() for line in text.splitlines())
                # Break multi-headlines into a line each
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                # Drop blank lines
                text = '\n'.join(chunk for chunk in chunks if chunk)

                # Limit length to avoid context window issues (approx 10k chars)
                return text[:10000]

        except httpx.HTTPStatusError as e:
            last_error = e
            logger.warning(f"Scrape attempt {attempt}/{MAX_RETRIES} HTTP error: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(BASE_BACKOFF_SECONDS * attempt)
            else:
                return f"Error scraping URL (HTTP {e.response.status_code}): {str(e)}"

        except Exception as e:
            last_error = e
            logger.warning(f"Scrape attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(BASE_BACKOFF_SECONDS * attempt)
            else:
                return f"Error scraping URL: {str(e)}"

    return f"Error scraping URL after {MAX_RETRIES} attempts: {last_error}"