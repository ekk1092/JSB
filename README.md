# Job Assistant (UNCW)

A powerful AI-driven job search assistant that helps candidates find opportunities, tailor resumes, and write cover letters. Built with **FastMCP**, **Streamlit**, and **NVIDIA's OpenAI-compatible API**.

![Deployed App Preview](/Users/tggnmgb/.gemini/antigravity/brain/f005f5ee-c229-4bc0-82d9-1418f30a0a01/deployed_app_view_1764599606834.png)

## Features

-   **Job Search**: Find jobs matching your career goals, not just your current role.
-   **Resume Tailoring**: Customize your resume for specific job descriptions.
-   **Cover Letter Generation**: Create personalized cover letters.
-   **NVIDIA Integration**: Uses NVIDIA's OpenAI-compatible API for LLM calls.

## Architecture

The project consists of three main components:

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
├── Deployment.md           # Deployment guide
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
     NGC_API_KEY=...
        NVIDIA_MODEL=nvidia/nemotron-mini-4b-instruct
    ```

3.  **Install dependencies**:
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -r server/requirements.txt
    pip install -r client_streamlit/requirements.txt
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
-   **NVIDIA OpenAI-compatible API**
-   **Docker**
-   **Azure Container Apps**
