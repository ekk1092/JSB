from mcp.server.fastmcp import FastMCP
from tools.jobs import search_jobs_tool
from tools.resume import tailor_resume_tool, generate_cover_letter_tool
from tools.web_scraper import scrape_job_description_tool
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

# Create the MCP Server
mcp = FastMCP("Job Assistant", host="0.0.0.0", port=8080)

@mcp.tool()
def search_jobs(search_term: str, location: str = "", results_wanted: int = 10) -> list:
    """
    Search for jobs on various platforms (Indeed, LinkedIn, etc.).
    Returns a list of job dictionaries with title, company, location, job_url, and description.
    
    IMPORTANT: The result ALREADY contains the job description in the 'description' field.
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


if __name__ == "__main__":
    import os
    transport = os.getenv("MCP_TRANSPORT", "sse")
    if transport == "stdio":
        mcp.run(transport='stdio')
    else:
        mcp.run(transport='sse')
