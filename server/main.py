import sys
import os
import logging

# Ensure server directory is in sys.path
SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from mcp.server.fastmcp import FastMCP
from tools.jobs import search_jobs_tool
from tools.resume import tailor_resume_tool, generate_cover_letter_tool
from tools.web_scraper import scrape_job_description_tool

# Configure logging to sys.stderr and backend.log
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(os.path.join(SERVER_DIR, "..", "backend.log"), mode="a", encoding="utf-8")
    ]
)

# Create the MCP Server
mcp = FastMCP("Job Assistant", host="0.0.0.0", port=8080)

@mcp.tool()
def search_jobs(search_term: str, location: str = "", site: str = "", results_wanted: int = 10) -> str:
    """
    Search for jobs on various platforms (Indeed, LinkedIn, etc.).
    Optionally filter by site ('indeed', 'linkedin').
    Returns a JSON string of job dictionaries with title, company, location, job_url, and description.
    
    IMPORTANT: The result ALREADY contains the job description in the 'description' field.
    """
    return search_jobs_tool(search_term, location=location, limit=results_wanted, site=site)

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


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "sse")
    mcp.run(transport=transport)
