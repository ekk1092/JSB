from mcp.server.fastmcp import FastMCP
from tools.jobs import search_jobs_tool
from tools.resume import tailor_resume_tool, generate_cover_letter_tool
from tools.web_scraper import scrape_job_description_tool

import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)

# Create the MCP Server
mcp = FastMCP("Job Assistant", host="0.0.0.0", port=8080)

@mcp.tool()
def search_jobs(search_term: str, location: str = "remote", results_wanted: int = 10) -> str:
    """
    Search for jobs on various platforms (Indeed, LinkedIn, etc.).
    Returns a CSV string of job listings.
    """
    return search_jobs_tool(search_term, location, results_wanted)

@mcp.tool()
def tailor_resume(resume_text: str, job_description: str) -> str:
    """
    Tailor a resume to match a specific job description.
    Returns the tailored resume in Markdown format.
    """
    return tailor_resume_tool(resume_text, job_description)

@mcp.tool()
def generate_cover_letter(resume_text: str, job_description: str) -> str:
    """
    Generate a cover letter based on a resume and job description.
    Returns the cover letter in Markdown format.
    """
    return generate_cover_letter_tool(resume_text, job_description)


@mcp.tool()
def scrape_job_description(url: str) -> str:
    """
    Scrape the job description from a URL.
    Useful when the user provides a link to a job posting (e.g. Indeed, LinkedIn).
    """
    return scrape_job_description_tool(url)

if __name__ == "__main__":
   mcp.run(transport='sse')
