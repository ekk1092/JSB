import os
import sys
import io
import re
import ast
import json
import uuid
import asyncio
import threading
import tempfile
from pathlib import Path
from datetime import datetime
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from prompts import build_enhanced_system_prompt

# -----------------------------------------------------------------------------
# ENVIRONMENT & CONFIGURATION
# -----------------------------------------------------------------------------
load_dotenv()

st.set_page_config(
    page_title="Job Assistant — AI Career Advisor",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# LLM Client Initialization (OpenAI-compatible / NVIDIA NIM)
client = OpenAI(
    api_key=os.getenv("NGC_API_KEY"),
    base_url=os.getenv("NGC_BASE_URL", "https://integrate.api.nvidia.com/v1"),
)
model_name = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct")

# -----------------------------------------------------------------------------
# THREADED ASYNC EVENT LOOP
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
# SESSION STATE INITIALIZATION
# -----------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "resume_text" not in st.session_state:
    st.session_state.resume_text = None

if "resume_path" not in st.session_state:
    st.session_state.resume_path = None

if "last_generated_content" not in st.session_state:
    st.session_state.last_generated_content = None

if "last_generated_type" not in st.session_state:
    st.session_state.last_generated_type = None

if "last_generated_filename" not in st.session_state:
    st.session_state.last_generated_filename = None

# -----------------------------------------------------------------------------
# HELPER FUNCTIONS & UTILITIES
# -----------------------------------------------------------------------------
def should_include_resume_context(user_input: str) -> bool:
    lowered = user_input.lower()
    return any(
        phrase in lowered
        for phrase in ["resume", "cover letter", "tailor", "rewrite my resume", "generate a resume"]
    )

def build_model_messages(system_prompt: str, chat_messages: list[dict], max_turns: int = 4) -> list[dict]:
    recent_messages = chat_messages[-(max_turns * 2):]
    return [{"role": "system", "content": system_prompt}] + recent_messages

def parse_job_search_request(user_input: str, previous_messages: list[dict] = None) -> dict[str, str]:
    lowered = user_input.lower().strip()
    location_markers = [" in ", " near ", " around "]
    location = ""
    search_text = user_input.strip()

    target_site = ""
    if "indeed" in lowered:
        target_site = "indeed"
    elif "linkedin" in lowered:
        target_site = "linkedin"
    elif "glassdoor" in lowered:
        target_site = "glassdoor"

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
        r"\b(from|on|only)\s+(linkedin|indeed|glassdoor|ziprecruiter)\b",
        r"\b(only)\b",
        r"\b(a|the)?\s*jobs?\b",
        r"\bin\b",
        r"\bfield\b",
        r"\brole\b",
    ]
    for pattern in fillers:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,?.!")

    # Fallback to previous conversation context for short follow-up prompts like "only on Indeed"
    if (len(cleaned) <= 2 or cleaned.lower() in ["indeed", "linkedin", "glassdoor"]) and previous_messages:
        for msg in reversed(previous_messages):
            if msg.get("role") == "user":
                prev_text = msg.get("content", "")
                if prev_text and prev_text.strip() != user_input.strip():
                    prev_parsed = parse_job_search_request(prev_text)
                    if prev_parsed.get("search_term") and len(prev_parsed["search_term"]) > 2:
                        cleaned = prev_parsed["search_term"]
                        if not location:
                            location = prev_parsed.get("location", "")
                        break

    return {
        "search_term": cleaned if len(cleaned) > 1 else search_text,
        "location": location,
        "site": target_site,
    }

def repair_and_parse_toolcall_json(raw_json_str: str) -> dict | None:
    text = raw_json_str.strip()
    text = re.sub(r"</tool_?call>.*$", "", text, flags=re.DOTALL).strip()
    
    try:
        return json.loads(text)
    except Exception:
        pass

    # Repair truncated JSON strings (e.g. missing trailing fields or brackets)
    cleaned = re.sub(r",?\s*\"[^\"]*\"?\s*:?\s*$", "", text).strip()
    open_braces = cleaned.count("{") - cleaned.count("}")
    open_brackets = cleaned.count("[") - cleaned.count("]")
    cleaned += "]" * max(0, open_brackets) + "}" * max(0, open_braces)

    try:
        return json.loads(cleaned)
    except Exception:
        return None

def parse_job_search_results(content: str) -> list[dict]:
    if not content:
        return []
    text = content.strip()

    # Pre-clean non-JSON python object representations
    cleaned_text = re.sub(r"datetime\.date\((\d+),\s*(\d+),\s*(\d+)\)", r'"\1-\2-\3"', text)
    cleaned_text = re.sub(r"Timestamp\('([^']+)'\)", r'"\1"', cleaned_text)
    cleaned_text = re.sub(r"\bnan\b", '""', cleaned_text)
    cleaned_text = re.sub(r"\bNone\b", '""', cleaned_text)

    for loader in (json.loads, ast.literal_eval):
        try:
            data = loader(cleaned_text)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
        except Exception:
            continue

    # Fallback: handle single-quoted python dictionary representations if returned
    try:
        data = ast.literal_eval(cleaned_text.replace('nan', '""'))
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        pass

    return []

def format_job_search_results(job_results: list[dict], search_term: str, location: str) -> str:
    if not job_results:
        location_text = f" in **{location}**" if location else ""
        return (
            f"No immediate job results found for **{search_term}**{location_text}.\n\n"
            f"💡 **Suggestions to try:**\n"
            f"- Try related keywords like `Data Analyst`, `Data Engineer`, or `Machine Learning Engineer`.\n"
            f"- Search for remote roles: `Data Scientist Remote`.\n"
            f"- Expand location search to `Delaware` or nearby `Philadelphia, PA`."
        )

    lines = [f"### 🎯 Job Matches for **{search_term}**"]
    if location:
        lines.append(f"📍 **Location:** {location}")
    lines.append("")

    for idx, job in enumerate(job_results[:10], 1):
        title = job.get("title") or job.get("job_title") or "Untitled Role"
        company = job.get("company") or "Unknown Company"
        job_location = job.get("location") or "Unknown Location"
        posted = job.get("date_posted") or "Recent"
        url = job.get("job_url") or job.get("url") or job.get("link") or ""

        lines.append(f"**{idx}. {title}** — *{company}*")
        lines.append(f"• **Location:** {job_location} | **Posted:** {posted}")
        if url:
            lines.append(f"• [Apply / View Job Listing]({url})")
        lines.append("")

    return "\n".join(lines).strip()

# -----------------------------------------------------------------------------
# ASYNC BACKEND DISPATCH (MCP SERVER INTERACTION)
# -----------------------------------------------------------------------------
async def run_chat_logic(user_input: str, chat_messages: list[dict], resume_text: str | None):
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

            include_resume = should_include_resume_context(user_input)
            resume_ctx = resume_text if include_resume else None

            system_prompt = build_enhanced_system_prompt(resume_ctx, openai_tools)
            messages = build_model_messages(system_prompt, chat_messages)

            search_intent = any(
                phrase in user_input.lower()
                for phrase in ["show me", "find", "search", "looking for", "job", "jobs", "hiring", "openings", "indeed", "linkedin", "only"]
            )

            if search_intent:
                search_args = parse_job_search_request(user_input, chat_messages)
                result = await session.call_tool(
                    "search_jobs",
                    arguments={
                        "search_term": search_args["search_term"],
                        "location": search_args["location"],
                        "site": search_args.get("site", ""),
                        "results_wanted": 10,
                    },
                )

                content = ""
                if hasattr(result, "content") and isinstance(result.content, list):
                    parts = [item.text if hasattr(item, "text") else str(item) for item in result.content]
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
                tool_choice="auto"
            )

            response_message = response.choices[0].message
            tool_outputs = []
            final_response = ""

            if response_message.tool_calls:
                messages.append(response_message)

                for call in response_message.tool_calls:
                    args = json.loads(call.function.arguments)
                    result = await session.call_tool(call.function.name, arguments=args)

                    parts = [item.text if hasattr(item, "text") else str(item) for item in (result.content if hasattr(result, "content") and isinstance(result.content, list) else [result])]
                    content = "\n".join(parts)

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
                content = response_message.content or ""
                raw_call = re.search(r"<tool_?call>\s*(\{.*)", content, re.DOTALL)
                if raw_call:
                    raw_json_str = raw_call.group(1).strip()
                    data = repair_and_parse_toolcall_json(raw_json_str)
                    if data:
                        tool_name = data.get("name")
                        args = data.get("arguments", {})
                        if tool_name:
                            result = await session.call_tool(tool_name, arguments=args)
                            parts = [item.text if hasattr(item, "text") else str(item) for item in (result.content if hasattr(result, "content") and isinstance(result.content, list) else [result])]
                            tool_text = "\n".join(parts)

                            if tool_name == "search_jobs":
                                parsed_jobs = parse_job_search_results(tool_text)
                                formatted = format_job_search_results(
                                    parsed_jobs,
                                    args.get("search_term", "Jobs"),
                                    args.get("location", "")
                                )
                                return formatted, [{"name": "search_jobs", "content": formatted}]

                            return tool_text, [{"name": tool_name, "content": tool_text}]

                final_response = content

            return final_response, tool_outputs

# -----------------------------------------------------------------------------
# SIDEBAR — UPLOAD, DOCUMENTS & LOGS
# -----------------------------------------------------------------------------
with st.sidebar:
    # App Logo
    logo_path = None
    for p in [Path(__file__).parent.parent / "uncw.png", Path("uncw.png")]:
        if p.exists():
            logo_path = p
            break
    if logo_path:
        st.image(str(logo_path), width="stretch")

    st.title("💼 Job Assistant")
    st.caption("AI-Powered Job Search, Resume Tailoring & Cover Letters")

    # Resume Upload Section
    with st.container(border=True):
        st.subheader("📄 Resume Upload")
        uploaded_file = st.file_uploader(
            "Upload your current resume",
            type=["txt", "md", "pdf", "docx", "doc"],
            help="Upload your resume to enable automated tailoring and cover letter generation."
        )

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
                st.success("✅ Resume parsed & attached to session!")

            except Exception as e:
                st.error(f"Error parsing resume: {e}")

    # Persistent Document Download Section
    st.subheader("📥 Generated Documents")
    if st.session_state.last_generated_content:
        label = st.session_state.last_generated_type.replace("_", " ").title()
        filename = st.session_state.last_generated_filename or f"{label}.docx"

        st.download_button(
            label=f":material/download: Download {label}",
            data=st.session_state.last_generated_content,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="persistent_download_button",
            type="primary"
        )
    else:
        st.caption("No generated `.docx` documents yet.")

    # Server Logs Collapsible
    st.markdown("---")
    st.subheader("🖥️ Server Health & Logs")
    with st.expander(":material/terminal: View Backend Logs"):
        log_file = Path(__file__).parent.parent / "backend.log"
        if log_file.exists():
            log_content = log_file.read_text(encoding="utf-8")
            if log_content.strip():
                recent_logs = "\n".join(log_content.splitlines()[-50:])
                st.code(recent_logs, language="text")
            else:
                st.caption("Log file is currently empty.")
        else:
            st.caption("No backend logs recorded yet.")
        if st.button(":material/refresh: Refresh Logs"):
            st.rerun()

# -----------------------------------------------------------------------------
# MAIN CHAT UI & ONBOARDING SUGGESTIONS
# -----------------------------------------------------------------------------
st.title("🚀 AI Job Search & Career Assistant")
st.markdown(
    "Welcome! Ask me to **search for open roles**, **tailor your resume for a job posting**, "
    "or **write a customized cover letter**."
)

# Suggestion Chips (Disappear once chat begins)
SUGGESTIONS = {
    ":material/search: Data Scientist in Wilmington, DE": "Find Data Scientist jobs in Wilmington DE",
    ":material/work: Remote Python Developer": "Search for Remote Python Developer jobs",
    ":material/description: Tailor My Resume": "Help me tailor my resume for a Data Science position",
    ":material/mail: Write a Cover Letter": "Write a tailored cover letter for a Software Engineer role"
}

if not st.session_state.messages:
    st.markdown("##### 💡 Try asking:")
    selected_chip = st.pills(
        "Suggestions",
        list(SUGGESTIONS.keys()),
        label_visibility="collapsed"
    )
    if selected_chip:
        prompt_text = SUGGESTIONS[selected_chip]
        st.session_state.messages.append({"role": "user", "content": prompt_text})
        st.session_state.pending_prompt = prompt_text
        st.rerun()

# Display Chat History
for message in st.session_state.messages:
    avatar = ":material/person:" if message["role"] == "user" else ":material/robot:"
    with st.chat_message(message["role"], avatar=avatar):
        st.markdown(message["content"])

# -----------------------------------------------------------------------------
# CHAT INPUT HANDLER
# -----------------------------------------------------------------------------
prompt = st.chat_input("Ask a question, search for jobs, or request document generation...", submit_mode="disable")

if not prompt and st.session_state.get("pending_prompt"):
    prompt = st.session_state.pop("pending_prompt")

if prompt:
    # Avoid duplicate append if triggered by suggestion pill
    if not st.session_state.messages or st.session_state.messages[-1].get("content") != prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user", avatar=":material/person:"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar=":material/robot:"):
        with st.spinner("Analyzing request & querying backend..."):
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
                        try:
                            data = json.loads(content)
                            if "error" in data:
                                st.error(f"Generation failed: {data['error']}")
                            if "preview" in data:
                                st.markdown(data["preview"])
                            if "file_content" in data:
                                file_bytes = base64.b64decode(data["file_content"])
                                st.session_state.last_generated_content = file_bytes
                                st.session_state.last_generated_type = output["name"]
                                st.session_state.last_generated_filename = data.get("filename")
                                st.success("✅ Document created! Download it from the sidebar.")
                        except Exception:
                            pass

                clean_response = re.sub(r"<tool_?call>.*?</tool_?call>", "", final_response, flags=re.DOTALL).strip()
                if not clean_response:
                    clean_response = final_response

                st.markdown(clean_response)
                st.session_state.messages.append({"role": "assistant", "content": clean_response})

            except Exception as exc:
                err_msg = f"⚠️ An error occurred: {exc}"
                st.error(err_msg)
                st.session_state.messages.append({"role": "assistant", "content": err_msg})
