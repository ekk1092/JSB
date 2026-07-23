import streamlit as st
import asyncio
import os
import sys
import threading
import tempfile
import uuid
import ast
from pathlib import Path
from datetime import datetime
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI
from dotenv import load_dotenv
import io
import base64
import json
from prompts import build_enhanced_system_prompt

# Load environment variables
load_dotenv()

# Page configuration
st.set_page_config(page_title="Job Assistant", layout="wide")

# Initialize NVIDIA OpenAI-Compatible Client
client = OpenAI(
    api_key=os.getenv("NGC_API_KEY"),
    base_url="https://integrate.api.nvidia.com/v1",
)
model_name = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct")

# -----------------------------------------------------------------------------
# 1. Threaded Event Loop
# -----------------------------------------------------------------------------
@st.cache_resource
def get_event_loop():
    loop = asyncio.new_event_loop()
    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()
    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    return loop

def run_async(coro):
    loop = get_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()

# -----------------------------------------------------------------------------
# Session State Initialization
# -----------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "resume_text" not in st.session_state:
    st.session_state.resume_text = None

if "resume_path" not in st.session_state:
    st.session_state.resume_path = None

# persistent file state
for key in ["last_generated_content", "last_generated_type", "last_generated_filename"]:
    if key not in st.session_state:
        st.session_state[key] = None

# -----------------------------------------------------------------------------
# CLEAR BUTTON CALLBACK
# -----------------------------------------------------------------------------
def clear_generated_state():
    st.session_state.last_generated_content = None
    st.session_state.last_generated_type = None
    st.session_state.last_generated_filename = None


def should_include_resume_context(user_input: str) -> bool:
    lowered = user_input.lower()
    return any(
        phrase in lowered
        for phrase in ["resume", "cover letter", "tailor", "rewrite my resume", "generate a resume"]
    )


def build_model_messages(system_prompt: str, chat_messages: list[dict], max_turns: int = 4) -> list[dict]:
    # Keep only the most recent turns so the prompt stays under the model's 4k context window.
    recent_messages = chat_messages[-(max_turns * 2):]
    return [{"role": "system", "content": system_prompt}] + recent_messages


def parse_job_search_request(user_input: str) -> dict[str, str]:
    import re
    lowered = user_input.lower().strip()
    location_markers = [" in ", " near ", " around "]
    location = ""
    search_text = user_input.strip()

    for marker in location_markers:
        if marker in lowered:
            idx = lowered.rfind(marker)
            search_text = user_input[:idx].strip()
            location = user_input[idx + len(marker):].strip().rstrip("?.!,")
            break

    cleaned = search_text
    fillers = [
        r"\bhelp me (find|finding|search|look for)\b",
        r"\b(find|search|look)\s+(me|for)?\b",
        r"\b(give me|show me)\b",
        r"\b(a|the)?\s*jobs?\b",
        r"\bin\b",
        r"\bfield\b",
        r"\brole\b",
    ]
    for pattern in fillers:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,?.!")

    return {
        "search_term": cleaned if len(cleaned) > 1 else search_text,
        "location": location,
    }


def parse_job_search_results(content: str) -> list[dict]:
    text = content.strip()

    for loader in (json.loads, ast.literal_eval):
        try:
            data = loader(text)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except Exception:
            continue

    return []


def format_job_search_results(job_results: list[dict], search_term: str, location: str) -> str:
    if not job_results:
        location_text = f" in {location}" if location else ""
        return f"No job results found for **{search_term}**{location_text}."

    lines = [f"### Job matches for **{search_term}**"]
    if location:
        lines.append(f"**Location:** {location}")
    lines.append("")

    for idx, job in enumerate(job_results[:10], 1):
        title = job.get("title") or job.get("job_title") or "Untitled role"
        company = job.get("company") or "Unknown company"
        job_location = job.get("location") or "Unknown location"
        posted = job.get("date_posted") or "Unknown date"
        url = job.get("job_url") or job.get("url") or job.get("link") or ""

        lines.append(f"**{idx}. {title}**")
        lines.append(f"Company: {company}")
        lines.append(f"Location: {job_location}")
        lines.append(f"Posted: {posted}")
        if url:
            lines.append(f"Link: {url}")
        lines.append("")

    return "\n".join(lines).strip()

# -----------------------------------------------------------------------------
# SIDEBAR — UPLOAD + PERSISTENT DOWNLOAD
# -----------------------------------------------------------------------------
with st.sidebar:
    # Robust logo path resolution
    possible_paths = [
        Path(__file__).parent / "uncw_logo.png",                # When run directly
        Path.cwd() / "client_streamlit" / "uncw_logo.png",      # When run from root
        Path("uncw_logo.png")                                   # Fallback
    ]
    
    logo_path = None
    for p in possible_paths:
        if p.exists():
            logo_path = p
            break
            
    if logo_path:
        st.image(str(logo_path), width='stretch')

    st.title("Resume Upload")
    uploaded_file = st.file_uploader("Upload your resume", type=["txt", "md", "pdf", "docx", "doc"])

    if uploaded_file:
        try:
            tmp_dir = Path(tempfile.gettempdir())
            safe_name = f"{uuid.uuid4()}_{uploaded_file.name}"
            resume_abs_path = tmp_dir / safe_name

            with open(resume_abs_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            st.session_state.resume_path = str(resume_abs_path)

            ext = uploaded_file.name.split(".")[-1].lower()
            text = ""

            if ext in ["txt", "md"]:
                text = uploaded_file.getvalue().decode("utf-8")
            elif ext == "pdf":
                import pypdf
                pdf_reader = pypdf.PdfReader(io.BytesIO(uploaded_file.getvalue()))
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            elif ext in ["docx", "doc"]:
                import docx
                doc_obj = docx.Document(io.BytesIO(uploaded_file.getvalue()))
                for para in doc_obj.paragraphs:
                    text += para.text + "\n"

            st.session_state.resume_text = text
            st.success("✅ Resume uploaded!")

        except Exception as e:
            st.error(f"Error: {e}")

    # -------------------------------------------------------------
    # ⭐ PERSISTENT DOWNLOAD SECTION
    # -------------------------------------------------------------
    st.markdown("---")
    st.subheader("Generated Documents")

    if st.session_state.last_generated_content:
        label = st.session_state.last_generated_type.replace("_", " ").title()
        filename = st.session_state.last_generated_filename or f"{label}.docx"

        st.download_button(
            label=f"⬇ Download {label}",
            data=st.session_state.last_generated_content,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="persistent_download_button"
        )
    else:
        st.caption("No generated documents yet.")

    # -------------------------------------------------------------
    # 🪵 BACKEND LOGS SECTION
    # -------------------------------------------------------------
    st.markdown("---")
    st.subheader("🖥️ Backend Logs")
    with st.expander("View Server Logs"):
        log_file = Path(__file__).parent.parent / "backend.log"
        if log_file.exists():
            log_content = log_file.read_text(encoding="utf-8")
            if log_content.strip():
                # Display last 50 lines of backend.log
                recent_logs = "\n".join(log_content.splitlines()[-50:])
                st.code(recent_logs, language="text")
            else:
                st.caption("Log file is empty.")
        else:
            st.caption("No logs recorded yet.")
        if st.button("Refresh Logs"):
            st.rerun()

# -----------------------------------------------------------------------------
# MAIN CHAT UI
# -----------------------------------------------------------------------------
st.title("💼 Job Assistant")
st.write("I can help you search for jobs, tailor resumes, and write cover letters.")

# Show chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# -----------------------------------------------------------------------------
# ASYNC LOGIC
# -----------------------------------------------------------------------------
async def run_chat_logic(user_input, chat_messages, resume_text):
    mcp_server_url = os.getenv("MCP_SERVER_URL")

    if mcp_server_url:
        from mcp.client.sse import sse_client
        url = mcp_server_url if mcp_server_url.endswith("/sse") else f"{mcp_server_url.rstrip('/')}/sse"
        client_context = sse_client(url)
    else:
        server_script = Path(__file__).parent.parent / "server" / "main.py"
        if not server_script.exists():
            server_script = Path("server/main.py")

        project_root = Path(__file__).parent.parent
        venv_python = project_root / ".venv" / "bin" / "python"
        if not venv_python.exists():
            venv_python = project_root / ".venv" / "Scripts" / "python.exe"

        python_executable = str(venv_python.absolute()) if venv_python.exists() else sys.executable

        server_params = StdioServerParameters(
            command=python_executable,
            args=[str(server_script.resolve())],
            env={**os.environ.copy(), "MCP_TRANSPORT": "stdio"}
        )
        client_context = stdio_client(server_params)

    async with client_context as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()

            openai_tools = [{
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema
                }
            } for tool in tools.tools]

            include_resume_context = should_include_resume_context(user_input)
            resume_context = resume_text if include_resume_context else None

            system_prompt = build_enhanced_system_prompt(
                resume_context,
                openai_tools
            )

            messages = build_model_messages(system_prompt, chat_messages)

            search_intent = any(
                phrase in user_input.lower()
                for phrase in ["show me", "find jobs", "search jobs", "jobs in", "job in", "job listings"]
            )

            if search_intent:
                search_args = parse_job_search_request(user_input)
                result = await session.call_tool(
                    "search_jobs",
                    arguments={
                        "search_term": search_args["search_term"],
                        "location": search_args["location"],
                        "results_wanted": 10,
                    },
                )

                content = ""
                if hasattr(result, "content") and isinstance(result.content, list):
                    parts = []
                    for item in result.content:
                        if hasattr(item, "text"):
                            parts.append(item.text)
                        else:
                            parts.append(str(item))
                    content = "\n".join(parts)
                else:
                    content = str(result)

                parsed_jobs = parse_job_search_results(content)
                formatted = format_job_search_results(
                    parsed_jobs,
                    search_args["search_term"],
                    search_args["location"],
                )

                return formatted, [{"name": "search_jobs", "content": formatted}]

            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=openai_tools,
                tool_choice={"type": "function", "function": {"name": "search_jobs"}} if search_intent else "auto"
            )

            response_message = response.choices[0].message
            tool_outputs = []
            final_response = ""

            if response_message.tool_calls:
                messages.append(response_message)

                for call in response_message.tool_calls:
                    import json
                    args = json.loads(call.function.arguments)
                    result = await session.call_tool(call.function.name, arguments=args)

                    parts = []
                    if hasattr(result, "content") and isinstance(result.content, list):
                        for item in result.content:
                            if hasattr(item, "text"):
                                parts.append(item.text)
                            else:
                                parts.append(str(item))
                        content = "\n".join(parts)
                    else:
                        content = str(result)

                    tool_outputs.append({"name": call.function.name, "content": content})

                    messages.append({
                        "tool_call_id": call.id,
                        "role": "tool",
                        "name": call.function.name,
                        "content": content
                    })

                second = client.chat.completions.create(model=model_name, messages=messages)
                final_response = second.choices[0].message.content

            else:
                final_response = response_message.content

            return final_response, tool_outputs

# -----------------------------------------------------------------------------
# CHAT INPUT HANDLER
# -----------------------------------------------------------------------------
if prompt := st.chat_input("How can I help you?"):
    # 👉 DO NOT clear generated files — we want persistent downloads
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                final_response, tool_outputs = run_async(
                    run_chat_logic(
                        prompt,
                        list(st.session_state.messages),
                        st.session_state.get("resume_text")
                    )
                )

                for output in tool_outputs:
                    content = output["content"]

                    if output["name"] in ["tailor_resume", "generate_cover_letter"]:
                        import json
                        data = json.loads(content)

                        if "error" in data:
                            st.error(f"Generation failed: {data['error']}")
                        
                        if "preview" in data:
                            st.markdown(data["preview"])

                        if "file_content" in data:
                            file_bytes = base64.b64decode(data["file_content"])
                            st.session_state.last_generated_content = file_bytes
                            st.session_state.last_generated_type = (
                                "resume" if output["name"] == "tailor_resume" else "cover_letter"
                            )
                            st.session_state.last_generated_filename = data.get("filename")
                            
                            # Ensure the assistant's response is added to chat history before rerun
                            import re
                            # Remove raw paths
                            clean = re.sub(r"/tmp/[^\s]+\.docx", "", final_response)
                            # Remove markdown links to docx files
                            clean = re.sub(r"\[.*?\]\(.*\.docx\)", "", clean)
                            # Remove trailing "Download" text if it remains
                            clean = clean.replace("Download Cover Letter", "").replace("Download Resume", "")
                            # Ensure direction points to sidebar
                            clean = clean.replace("button below", "button in the sidebar")
                            
                            st.session_state.messages.append({"role": "assistant", "content": clean})
                            
                            st.rerun()

                    elif output["name"] not in ["search_jobs", "scrape_job_description"]:
                        st.markdown(content)

                # Remove file path noise
                import re
                clean = re.sub(r"/tmp/[^\s]+\.docx", "", final_response)
                st.markdown(clean)

                st.session_state.messages.append({"role": "assistant", "content": clean})

            except Exception as e:
                import traceback
                st.error(f"Error: {str(e)}\n\n{traceback.format_exc()}")
