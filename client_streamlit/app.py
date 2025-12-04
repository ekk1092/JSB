import streamlit as st
import asyncio
import os
import sys
import threading
import tempfile
import uuid
from pathlib import Path
from datetime import datetime
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AzureOpenAI
from dotenv import load_dotenv
import io
import base64
from prompts import build_enhanced_system_prompt

# Load environment variables
load_dotenv()

# Page configuration
st.set_page_config(page_title="Job Assistant", layout="wide")

# Initialize Azure OpenAI Client
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)
deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")

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

# -----------------------------------------------------------------------------
# SIDEBAR — UPLOAD + PERSISTENT DOWNLOAD
# -----------------------------------------------------------------------------
with st.sidebar:
    current_dir = Path(__file__).parent
    logo_path = current_dir / "uncw_logo.png"
    if logo_path.exists():
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
                openai_tools
            )

            messages = [{"role": "system", "content": system_prompt}] + st.session_state.messages

            response = client.chat.completions.create(
                model=deployment_name,
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

                second = client.chat.completions.create(model=deployment_name, messages=messages)
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
                final_response, tool_outputs = asyncio.run(run_chat_logic(prompt))

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
