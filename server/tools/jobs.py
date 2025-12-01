import logging
from jobspy import scrape_jobs
import pandas as pd

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def search_jobs_tool(search_term: str, location: str = "remote", results_wanted: int = 10) -> str:
    """
    Searches for jobs using python-jobspy.
    
    Args:
        search_term: The job title or keyword to search for.
        location: The location to search in (default: "remote").
        results_wanted: Number of results to return (default: 10).
        
    Returns:
        A string representation of the found jobs (CSV format).
    """
    logger.info(f"Searching for {search_term} in {location}")
    
    try:
        jobs: pd.DataFrame = scrape_jobs(
            site_name=["indeed", "linkedin", "zip_recruiter", "glassdoor"],
            search_term=search_term,
            location=location,
            results_wanted=results_wanted,
            hours_old=72, # Last 3 days
            country_urlpatterns={"indeed": "https://www.indeed.com"},
        )
        
        if jobs.empty:
            return "No jobs found."
            
        # Select relevant columns
        columns = ["title", "company", "location", "job_url", "description"]
        # Filter for columns that exist in the dataframe
        existing_columns = [col for col in columns if col in jobs.columns]
        jobs_filtered = jobs[existing_columns]
        
        return jobs_filtered.to_csv(index=False)
        
    except Exception as e:
        logger.error(f"Error searching for jobs: {str(e)}")
        return f"Error searching for jobs: {str(e)}"
