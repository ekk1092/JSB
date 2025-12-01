import logging
import httpx
from bs4 import BeautifulSoup

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def scrape_job_description_tool(url: str) -> str:
    """
    Scrapes the job description from a given URL.
    
    Args:
        url: The URL of the job posting.
        
    Returns:
        The text content of the job description, or an error message.
    """
    logger.info(f"Scraping job description from {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        with httpx.Client(follow_redirects=True, headers=headers) as client:
            response = client.get(url)
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
            
    except Exception as e:
        logger.error(f"Error scraping URL: {e}")
        return f"Error scraping URL: {str(e)}"
