from mcp.server.fastmcp import FastMCP
import logging
import os

# Support both `python server/main.py` (script) and `import server.main` (module)
try:
    from .tools.jobs import search_jobs_tool
    from .tools.resume import tailor_resume_tool, generate_cover_letter_tool
    from .tools.web_scraper import scrape_job_description_tool
except ImportError:
    from tools.jobs import search_jobs_tool
    from tools.resume import tailor_resume_tool, generate_cover_letter_tool
    from tools.web_scraper import scrape_job_description_tool

# Configure logging
logging.basicConfig(level=logging.INFO)

# Create the MCP Server
mcp = FastMCP("Job Assistant", host="0.0.0.0", port=8080)

@mcp.tool()
def search_jobs(
    search_term: str = "",
    location: str = "",
    results_wanted: int = 10,
    query: str = "",
    no_clearance: bool = False,
    work_type: str = "All"
) -> list:
    """
    Search for jobs on various platforms (Indeed, LinkedIn, Glassdoor, ZipRecruiter).
    Returns a list of job dictionaries with title, company, location, job_url, and description.
    
    IMPORTANT:
    - Use this tool ONLY when the user explicitly requests to search for NEW job listings.
    - DO NOT call this tool when the user is selecting an option or ordinal reference (e.g. 'the 3rd', 'option 2', 'the first position') from previously retrieved jobs in the chat!
    """
    term = search_term if search_term else query
    return search_jobs_tool(term, location, results_wanted, no_clearance=no_clearance, work_type=work_type)

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
    Scrape the full job description text from a job posting URL.
    Returns the extracted text content (up to ~10k characters).
    """
    return scrape_job_description_tool(url)


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").strip().lower()
    mcp.run(transport=transport)
