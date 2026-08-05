import streamlit as st
import asyncio
import os
import sys
import tempfile
import uuid
import time
import json
import io
import base64
import re
import traceback
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI, RateLimitError
from dotenv import load_dotenv
from prompts import build_enhanced_system_prompt
from resume_analyzer import analyze_resume_profile, calculate_job_match

# Load environment variables
load_dotenv()

# Page configuration
st.set_page_config(page_title="Job Assistant", layout="wide")

# Initialize LLM Client (OpenAI-compatible endpoint pointing at Google Gemini)
client = OpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url=os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
)
model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# Retry configuration for Gemini API rate-limit (429) errors.
LLM_MAX_RETRIES = 4
LLM_BASE_BACKOFF_SECONDS = 2.0


def _parse_retry_after(exc: RateLimitError) -> float | None:
    """Extract the 'Please retry in Xs' hint from a Gemini RateLimitError."""
    match = re.search(r"Please retry in ([0-9.]+)s", str(exc))
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def _normalize_text(value) -> str:
    return value if isinstance(value, str) else ""


def _safe_parse_json(content: str):
    if not content or not isinstance(content, str):
        return None
    try:
        return json.loads(content)
    except Exception:
        try:
            return json.loads(content, strict=False)
        except Exception:
            try:
                match = re.search(r"\[\s*\{.*\}\s*\]", content, re.DOTALL)
                if match:
                    return json.loads(match.group(0), strict=False)
            except Exception:
                pass
    return None


def call_llm_with_retry(**kwargs):
    """
    Call the Gemini LLM with automatic retry on 429 RateLimitError.
    """
    last_exc = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except RateLimitError as exc:
            last_exc = exc
            retry_after = _parse_retry_after(exc)
            wait = retry_after if retry_after else (LLM_BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))
            if attempt < LLM_MAX_RETRIES:
                time.sleep(wait)
    raise last_exc


def _force_text_summary(messages: list) -> str:
    """
    Force a final text-only completion when the model returns empty content.
    This is a workaround for thinking models (e.g. gemini-3.5-flash) that
    sometimes return `content=None` after a tool call round.
    """
    try:
        resp = client.chat.completions.create(
            model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
            messages=messages,
            # No tools — force a plain text summarization
            tool_choice="none",
            # Lower temperature for more deterministic output
            temperature=0.3,
        )
        return _normalize_text(resp.choices[0].message.content)
    except Exception:
        return ""

# -----------------------------------------------------------------------------
# Session State Initialization
# -----------------------------------------------------------------------------
MAX_MESSAGES = 20  # Cap chat history sent to the LLM to bound context/cost
MAX_FILE_SIZE_MB = 10

st.session_state.setdefault("messages", [])
st.session_state.setdefault("resume_text", None)
st.session_state.setdefault("resume_path", None)
st.session_state.setdefault("resume_profile", None)
st.session_state.setdefault("last_generated_content", None)
st.session_state.setdefault("last_generated_type", None)
st.session_state.setdefault("last_generated_filename", None)

# Candidate Preferences Memory
if "search_preferences" not in st.session_state:
    st.session_state.search_preferences = {
        "no_clearance": False,
        "work_type": "All",
        "target_location": ""
    }


# -----------------------------------------------------------------------------
# CLEAR BUTTON CALLBACK
# -----------------------------------------------------------------------------
def clear_generated_state():
    st.session_state.last_generated_content = None
    st.session_state.last_generated_type = None
    st.session_state.last_generated_filename = None


# -----------------------------------------------------------------------------
# SIDEBAR — UPLOAD + PROFILE + PREFERENCES + DOWNLOAD
# -----------------------------------------------------------------------------
with st.sidebar:
    possible_paths = [
        Path(__file__).parent / "jsb_logo.png",
        Path.cwd() / "client_streamlit" / "jsb_logo.png",
        Path("jsb_logo.png")
    ]
    
    logo_path = None
    for p in possible_paths:
        if p.exists():
            logo_path = p
            break
            
    if logo_path:
        st.image(str(logo_path), width="stretch")

    # 1. Resume Upload Container
    with st.container(border=True):
        st.subheader("📁 Resume upload")
        uploaded_file = st.file_uploader(
            "Upload your resume",
            type=["txt", "md", "pdf", "docx"],
            label_visibility="collapsed"
        )

        if uploaded_file:
            if uploaded_file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
                st.error(f"File size exceeds maximum allowed size of {MAX_FILE_SIZE_MB}MB.")
            else:
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
                            text += (page.extract_text() or "") + "\n"
                    elif ext == "docx":
                        import docx
                        doc_obj = docx.Document(io.BytesIO(uploaded_file.getvalue()))
                        for para in doc_obj.paragraphs:
                            text += para.text + "\n"

                    st.session_state.resume_text = text
                    st.session_state.resume_profile = analyze_resume_profile(text)
                    st.success("✅ Resume analyzed!")

                except Exception as e:
                    st.error(f"Error reading file: {e}")

    # 2. Candidate AI Profile Card
    if st.session_state.resume_profile:
        prof = st.session_state.resume_profile
        with st.container(border=True):
            st.subheader("👤 Candidate AI profile")
            st.caption(f"**Level:** {prof.get('experience_level', 'Entry-Level')}")
            
            skills = prof.get("skills", [])
            if skills:
                st.markdown("**Top Skills:** " + ", ".join(f"`{s}`" for s in skills[:6]))
            
            roles = prof.get("suggested_roles", [])
            if roles:
                st.markdown("**Suggested Roles:**")
                try:
                    selected_role = st.pills(
                        "Target Roles",
                        options=roles,
                        selection_mode="single",
                        label_visibility="collapsed"
                    )
                    if selected_role:
                        st.session_state["pending_prompt"] = f"Search for {selected_role} positions"
                except Exception:
                    # Fallback for older Streamlit without st.pills
                    for r in roles[:3]:
                        if st.button(f"🔍 {r}", key=f"btn_role_{r}"):
                            st.session_state["pending_prompt"] = f"Search for {r} positions"

    # 3. Candidate Search Preferences
    with st.expander("⚙️ Search preferences", expanded=False):
        no_clearance_val = st.checkbox(
            "Exclude security clearance jobs",
            value=st.session_state.search_preferences["no_clearance"]
        )
        try:
            work_type_val = st.segmented_control(
                "Work arrangement",
                options=["All", "Remote", "Hybrid", "On-site"],
                default=st.session_state.search_preferences["work_type"]
            )
        except Exception:
            work_type_val = st.radio(
                "Work arrangement",
                options=["All", "Remote", "Hybrid", "On-site"],
                index=["All", "Remote", "Hybrid", "On-site"].index(st.session_state.search_preferences["work_type"]) if st.session_state.search_preferences["work_type"] in ["All", "Remote", "Hybrid", "On-site"] else 0
            )

        target_loc_val = st.text_input(
            "Preferred city / location",
            value=st.session_state.search_preferences["target_location"],
            placeholder="e.g. Wilmington, DE"
        )
        
        st.session_state.search_preferences["no_clearance"] = no_clearance_val
        st.session_state.search_preferences["work_type"] = work_type_val or "All"
        st.session_state.search_preferences["target_location"] = target_loc_val

    # 4. Persistent Document Download
    with st.container(border=True):
        st.subheader("📄 Generated documents")

        if st.session_state.last_generated_content:
            label = st.session_state.last_generated_type.replace("_", " ").title()
            filename = st.session_state.last_generated_filename or f"{label}.docx"

            st.download_button(
                label=f"Download {label}",
                data=st.session_state.last_generated_content,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="persistent_download_button",
                type="primary"
            )
        else:
            st.caption("No generated documents yet.")

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
async def run_chat_logic(user_input):
    mcp_server_url = os.getenv("MCP_SERVER_URL")

    if mcp_server_url:
        from mcp.client.sse import sse_client
        client_context = sse_client(mcp_server_url)
    else:
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["server/main.py"],
            env=os.environ.copy()
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

            system_prompt = build_enhanced_system_prompt(
                st.session_state.resume_text,
                openai_tools,
                preferences=st.session_state.get("search_preferences"),
                profile=st.session_state.get("resume_profile")
            )

            # Cap history to the most recent N messages to bound context window
            recent_messages = st.session_state.messages[-MAX_MESSAGES:]
            messages = [{"role": "system", "content": system_prompt}] + recent_messages

            try:
                response = call_llm_with_retry(
                    model=model_name,
                    messages=messages,
                    tools=openai_tools,
                    tool_choice="auto"
                )
            except RateLimitError as exc:
                retry_after = _parse_retry_after(exc)
                retry_text = (
                    f" Please try again in about {retry_after:.0f} seconds."
                    if retry_after
                    else " Please try again shortly."
                )
                return (
                    "The Gemini API quota is currently exhausted." + retry_text,
                    [],
                )

            response_message = response.choices[0].message
            tool_outputs = []
            final_response = ""
            MAX_TOOL_ROUNDS = 5  # Safeguard against infinite tool-call loops

            # ------------------------------------------------------------------
            # Loop through multiple rounds of tool calls until the model produces
            # a final text response.  This fixes the "dumb" canned fallback: the
            # previous code only handled ONE tool round and did NOT pass `tools`
            # on the follow-up completion.  Thinking models (e.g. gemini-3.5-flash)
            # return `content=None` when they want to make another tool call, which
            # left `final_response` empty and triggered the generic fallback text.
            # ------------------------------------------------------------------
            num_tool_rounds = 0
            while True:
                if response_message.tool_calls:
                    # Guard against infinite tool-call loops
                    num_tool_rounds += 1
                    if num_tool_rounds > MAX_TOOL_ROUNDS:
                        final_response = (
                            "I've made several tool calls to complete your request. "
                            "Please check the results above or rephrase your request."
                        )
                        break

                    if hasattr(response_message, "model_dump"):
                        messages.append(response_message.model_dump(exclude_none=True))
                    else:
                        messages.append(response_message)

                    for call in response_message.tool_calls:
                        args = json.loads(call.function.arguments) if call.function.arguments else {}
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

                    # Check if document creation tools were executed in this round
                    has_doc_tool = any(
                        call.function.name in ["tailor_resume", "generate_cover_letter"]
                        for call in response_message.tool_calls
                    )

                    try:
                        # If a document tool was called, force text-only completion (no more tool calls)
                        if has_doc_tool:
                            second = call_llm_with_retry(
                                model=model_name,
                                messages=messages,
                                tool_choice="none"
                            )
                        else:
                            second = call_llm_with_retry(
                                model=model_name,
                                messages=messages,
                                tools=openai_tools,
                                tool_choice="auto"
                            )
                    except RateLimitError as exc:
                        retry_after = _parse_retry_after(exc)
                        retry_text = (
                            f" Please try again in about {retry_after:.0f} seconds."
                            if retry_after
                            else " Please try again shortly."
                        )
                        return (
                            "The Gemini API quota is currently exhausted." + retry_text,
                            [],
                        )
                    except Exception as exc:
                        st.error(f"Error getting completion after tool execution: {exc}")
                        break

                    response_message = second.choices[0].message

                    # If the model produced a final text answer after this round,
                    # capture it and validate it is non-empty.
                    if not response_message.tool_calls:
                        final_response = _normalize_text(response_message.content)
                        # Thinking models sometimes return empty content; force a
                        # final text-only completion so the user gets a real reply.
                        if not final_response.strip():
                            final_response = _force_text_summary(messages)
                        break

                else:
                    final_response = _normalize_text(response_message.content)
                    # If content is empty (thinking models sometimes return None),
                    # force a final text-only completion.
                    if not final_response.strip():
                        final_response = _force_text_summary(messages)
                    break

            return final_response, tool_outputs

# -----------------------------------------------------------------------------
# CHAT INPUT HANDLER
# -----------------------------------------------------------------------------
user_prompt = None
if prompt := st.chat_input("How can I help you?"):
    user_prompt = prompt
elif st.session_state.get("pending_prompt"):
    user_prompt = st.session_state.pop("pending_prompt")

if user_prompt:
    # 👉 DO NOT clear generated files — we want persistent downloads
    st.session_state.messages.append({"role": "user", "content": user_prompt})

    with st.chat_message("user"):
        st.markdown(user_prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                final_response, tool_outputs = asyncio.run(run_chat_logic(user_prompt))

                for output in tool_outputs:
                    content = _normalize_text(output["content"])

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
                                st.session_state.last_generated_type = (
                                    "resume" if output["name"] == "tailor_resume" else "cover_letter"
                                )
                                st.session_state.last_generated_filename = data.get("filename")
                                
                                clean = re.sub(r"/tmp/[^\s]+\.docx", "", final_response)
                                clean = re.sub(r"\[.*?\]\(.*\.docx\)", "", clean)
                                clean = clean.replace("Download Cover Letter", "").replace("Download Resume", "")
                                clean = clean.replace("button below", "button in the sidebar")
                                
                                st.session_state.messages.append({"role": "assistant", "content": clean})
                                st.rerun()
                        except Exception as parse_err:
                            st.markdown(content)

                    elif output["name"] == "search_jobs":
                        try:
                            jobs_data = _safe_parse_json(content)
                            if isinstance(jobs_data, list) and jobs_data:
                                resume_text = st.session_state.get("resume_text", "")
                                profile_skills = st.session_state.resume_profile.get("skills", []) if st.session_state.resume_profile else []

                                st.markdown("### 🔍 Retrieved Positions & Match Analysis")
                                for idx, job in enumerate(jobs_data[:6]):
                                    match = calculate_job_match(
                                        resume_text,
                                        profile_skills,
                                        job.get("title", ""),
                                        job.get("description", "")
                                    )

                                    score = match["match_percentage"]
                                    badge_color = ":green" if score >= 75 else (":orange" if score >= 55 else ":red")

                                    with st.container(border=True):
                                        col1, col2 = st.columns([3, 1])
                                        with col1:
                                            title = job.get('title', 'Job Posting')
                                            company = job.get('company', 'Company')
                                            url = job.get('job_url') or job.get('url') or '#'
                                            st.markdown(f"#### [{title}]({url})")
                                            st.caption(f"**Company:** {company} | **Location:** {job.get('location', 'Not specified')}")
                                        with col2:
                                            st.markdown(f"### {badge_color}[{score}% Match]")

                                        matched_str = ", ".join(f"`{s}`" for s in match["matched_skills"]) if match["matched_skills"] else "None specified"
                                        missing_str = ", ".join(f"`{s}`" for s in match["missing_skills"]) if match["missing_skills"] else "None"
                                        st.markdown(f"**Matched Skills:** ✅ {matched_str}")
                                        st.markdown(f"**Skills to Highlight / Gap:** ⚠️ {missing_str}")

                                        with st.expander("Show Description Snippet"):
                                            st.write(job.get("description", "No description provided.")[:600] + "...")

                                        # 1-Click Action Buttons
                                        b1, b2, b3 = st.columns(3)
                                        with b1:
                                            if st.button("📄 Tailor Resume", key=f"tailor_{idx}_{hash(title)}"):
                                                st.session_state["pending_prompt"] = f"Tailor my resume for the {title} position at {company}. Job description: {job.get('description', '')[:2000]}"
                                                st.rerun()
                                        with b2:
                                            if st.button("✉️ Cover Letter", key=f"cover_{idx}_{hash(title)}"):
                                                st.session_state["pending_prompt"] = f"Generate a cover letter for the {title} position at {company}. Job description: {job.get('description', '')[:2000]}"
                                                st.rerun()
                                        with b3:
                                            if url != "#":
                                                st.link_button("🔗 View Posting", url)
                        except Exception:
                            pass
                    elif output["name"] not in ["scrape_job_description"]:
                        st.markdown(content)

                # Remove file path noise from response
                clean = re.sub(r"/tmp/[^\s]+\.docx", "", _normalize_text(final_response))
                if not clean.strip():
                    has_jobs = False
                    if tool_outputs:
                        for output in tool_outputs:
                            if output["name"] == "search_jobs":
                                try:
                                    j_data = _safe_parse_json(_normalize_text(output["content"]))
                                    if isinstance(j_data, list) and len(j_data) > 0:
                                        has_jobs = True
                                except Exception:
                                    pass

                    if has_jobs:
                        clean = "Above are the active position listings matching your request. Click **Tailor Resume** or **Cover Letter** on any posting to create customized application documents!"
                    elif tool_outputs:
                        clean = "I ran a live search on job boards for your request, but no open listings matched those exact search constraints on this run. Consider broadening your location preference, relaxing work arrangement filters (Remote/Hybrid), or searching for related role titles!"
                    else:
                        clean = "I'm ready to help! You can ask me career advice questions, upload your resume for review, or specify a target job title and city/state to search for active openings."

                if clean.strip():
                    st.markdown(clean)
                    st.session_state.messages.append({"role": "assistant", "content": clean})

            except Exception as e:
                st.error(f"Error: {str(e)}\n\n{traceback.format_exc()}")
