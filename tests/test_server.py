from server.main import mcp


def test_all_tools_registered():
    """The MCP server must expose all four tools."""
    tools = mcp._tool_manager.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "search_jobs",
        "tailor_resume",
        "generate_cover_letter",
        "scrape_job_description",
    }