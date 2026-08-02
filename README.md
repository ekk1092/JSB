# Job Assistant (UNCW)

A powerful AI-driven job search assistant that helps candidates find opportunities, tailor resumes, and write cover letters. Built with **FastMCP**, **Streamlit**, and **Azure OpenAI**.

## Features

-   **Job Search**: Find jobs matching your career goals, not just your current role.
-   **Resume Tailoring**: Customize your resume for specific job descriptions.
-   **Cover Letter Generation**: Create personalized cover letters.
-   **Multi-Platform**: Accessible via a **Streamlit Web UI**.
-   **Azure Integration**: Deployed on Azure Container Apps with Azure OpenAI.

## Architecture

The project consists of two main components:

1.  **MCP Server (`server/`)**: The core logic engine built with `FastMCP`. It exposes tools for job searching and document generation via an SSE (Server-Sent Events) endpoint.
2.  **Streamlit Client (`client_streamlit/`)**: A user-friendly web interface for interacting with the assistant.

## Project Structure

```
.
├── server/                 # MCP Server (FastMCP)
│   ├── main.py             # Entry point
│   └── tools/              # Tool definitions (jobs, resume, etc.)
├── client_streamlit/       # Streamlit Web App
│   ├── app.py              # Main application logic
│   └── uncw_logo.png       # Sidebar logo
├── Dockerfile              # Multi-service Dockerfile
├── Deployment.md           # Azure deployment guide
└── requirements.txt        # Dependencies
```

## Local Development

1.  **Clone the repository**:
    ```bash
    git clone <repo-url>
    cd edemJSB
    ```

2.  **Set up environment variables**:
    Create a `.env` file with the following:
    ```env
    AZURE_OPENAI_API_KEY=...
    AZURE_OPENAI_ENDPOINT=...
    AZURE_OPENAI_DEPLOYMENT_NAME=...
    ```

3.  **Install dependencies**:
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

4.  **Run Locally**:
    -   **Server**: `python server/main.py`
    -   **Streamlit**: `streamlit run client_streamlit/app.py`

## Deployment

This project is designed to be deployed on **Azure Container Apps**.

See [Deployment.md](Deployment.md) for a detailed step-by-step guide.

## Technologies

-   **Python 3.11**
-   **FastMCP** (Model Context Protocol)
-   **Streamlit**
-   **Azure OpenAI**
-   **Docker**
-   **Azure Container Apps**
