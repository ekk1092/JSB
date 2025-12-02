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
import logging

# Suppress pypdf warnings (harmless "Ignoring wrong pointing object" logs)
logging.getLogger("pypdf").setLevel(logging.ERROR)

from server.prompts import build_enhanced_system_prompt

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
    """Create and return a persistent event loop for async operations in a separate thread."""
    loop = asyncio.new_event_loop()

    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    return loop

# -----------------------------------------------------------------------------
# 2. Enhanced System Prompt (Imported from Shared Logic)
# -----------------------------------------------------------------------------
# build_enhanced_system_prompt is now imported from server.prompts

# Add project root to sys.path to allow importing from server.prompts

# -----------------------------------------------------------------------------
# Session State Initialization
# -----------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "resume_text" not in st.session_state:
    st.session_state.resume_text = None
if "resume_path" not in st.session_state:
    st.session_state.resume_path = None
if "last_generated_filename" not in st.session_state:
    st.session_state.last_generated_filename = None

def clear_generated_state():
    """Callback to clear generated content after download."""
    st.session_state.last_generated_content = None
    st.session_state.last_generated_type = None
    st.session_state.last_generated_json = None
    st.session_state.last_generated_filename = None

# -----------------------------------------------------------------------------
# 3. File Upload with Temp Storage
# -----------------------------------------------------------------------------
with st.sidebar:
    # Add Logo
    current_dir = Path(__file__).parent
    logo_path = current_dir / "ds_logo.png"
    if logo_path.exists():
        st.image(str(logo_path), width='stretch')
    else:
        st.warning("Logo not found")

    st.title("Resume Upload")
    uploaded_file = st.file_uploader("Upload your Resume (TXT/MD/PDF/DOCX)", type=["txt", "md", "pdf", "docx", "doc"])
    
    if uploaded_file:
        try:
            # Save to temp file
            tmp_dir = Path(tempfile.gettempdir())
            safe_name = f"{uuid.uuid4()}_{uploaded_file.name}"
            resume_abs_path = tmp_dir / safe_name
            
            with open(resume_abs_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            st.session_state.resume_path = str(resume_abs_path)
            
            # Extract text for context
            file_ext = uploaded_file.name.split(".")[-1].lower()
            text = ""
            
            if file_ext in ["txt", "md"]:
                text = uploaded_file.getvalue().decode("utf-8")
            elif file_ext == "pdf":
                import pypdf
                pdf_reader = pypdf.PdfReader(io.BytesIO(uploaded_file.getvalue()))
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            elif file_ext in ["docx", "doc"]:
                import docx
                doc = docx.Document(io.BytesIO(uploaded_file.getvalue()))
                for para in doc.paragraphs:
                    text += para.text + "\n"
            
            st.session_state.resume_text = text
            st.success("Resume uploaded and processed successfully!")
            
        except Exception as e:
            st.error(f"Error processing file: {str(e)}")

# -----------------------------------------------------------------------------
# Main Chat Interface
# -----------------------------------------------------------------------------
st.title("💼 AI Job Assistant")
st.markdown("I can help you search for jobs, tailor your resume, and write cover letters.")

# Display Chat History
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# -----------------------------------------------------------------------------
# Async Logic (Executed on Threaded Loop)
# -----------------------------------------------------------------------------
async def run_chat_logic(user_input):
    # This function encapsulates the entire session lifecycle to avoid passing 'session' out
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
            
            openai_tools = []
            for tool in tools.tools:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema
                    }
                })

            system_prompt = build_enhanced_system_prompt(st.session_state.resume_text, openai_tools)
            # Use a copy of messages to avoid mutating state prematurely
            messages = [{"role": "system", "content": system_prompt}] + list(st.session_state.messages)
            
            # First LLM Call
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
                for tool_call in response_message.tool_calls:
                    import json
                    function_args = json.loads(tool_call.function.arguments)
                    
                    # Notify UI (we can't directly update UI from here easily, so we return status)
                    # For now, we just execute.
                    
                    result = await session.call_tool(tool_call.function.name, arguments=function_args)
                    
                    # Extract text from content items
                    content_parts = []
                    if hasattr(result, 'content') and isinstance(result.content, list):
                        for item in result.content:
                            if hasattr(item, 'text'):
                                content_parts.append(item.text)
                            else:
                                content_parts.append(str(item))
                        content = "\n".join(content_parts)
                    else:
                        content = str(result)
                    
                    tool_outputs.append({
                        "name": tool_call.function.name,
                        "content": content
                    })
                    
                    messages.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": tool_call.function.name,
                        "content": content
                    })
                
                second_response = client.chat.completions.create(
                    model=deployment_name,
                    messages=messages
                )
                final_response = second_response.choices[0].message.content
            else:
                final_response = response_message.content
                
            return final_response, tool_outputs

# -----------------------------------------------------------------------------
# User Input Handler
# -----------------------------------------------------------------------------
if prompt := st.chat_input("What would you like to do?"):
    # Clear previous generated content to prevent button persistence across turns
    st.session_state.last_generated_content = None
    st.session_state.last_generated_type = None
    st.session_state.last_generated_json = None
    st.session_state.last_generated_filename = None

    # 1. Append User Message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
        
    # 2. Run Async Logic (Directly)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                final_response, tool_outputs = asyncio.run(run_chat_logic(prompt))
                
                # 3. Handle Tool Outputs (Downloads)
                for output in tool_outputs:
                    st.markdown(f"*Called tool: `{output['name']}`*")
                    
                    content = output['content']
                    
                    if output['name'] in ["tailor_resume", "generate_cover_letter"]:
                        # Try to parse JSON output
                        try:
                            import json
                            data = json.loads(content)
                            
                            if "preview" in data:
                                st.markdown(data["preview"])
                            
                            if "file_path" in data:
                                # Read the generated file
                                with open(data["file_path"], "rb") as f:
                                    file_bytes = f.read()
                                
                                st.session_state.last_generated_content = file_bytes
                                st.session_state.last_generated_type = "resume" if output['name'] == "tailor_resume" else "cover_letter"
                                st.session_state.last_generated_json = content
                                st.session_state.last_generated_filename = data.get("filename")
                                
                        except json.JSONDecodeError:
                            # Fallback for plain text or error messages
                            st.markdown(content)
                    elif output['name'] in ["search_jobs", "scrape_job_description"]:
                        # Completely hide raw output for these tools
                        pass
                    else:
                        # Other tools
                        st.markdown(content)

                # 4. Display Final Response
                st.markdown(final_response)
                st.session_state.messages.append({"role": "assistant", "content": final_response})
                
                # 5. Show Download Buttons
                if "last_generated_content" in st.session_state and st.session_state.last_generated_content:
                    content_bytes = st.session_state.last_generated_content
                    doc_type = st.session_state.last_generated_type
                    
                    # Use dynamic filename if available, else fallback
                    filename = st.session_state.last_generated_filename or f"{doc_type}.docx"
                    
                    st.download_button(
                        label=f"Download {doc_type.replace('_', ' ').title()} (DOCX)",
                        data=content_bytes,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        on_click=clear_generated_state
                        )
                        
            except Exception as e:
                import traceback
                error_msg = f"An error occurred: {str(e)}\n\nTraceback:\n{traceback.format_exc()}"
                if hasattr(e, 'exceptions'):
                    for i, exc in enumerate(e.exceptions):
                        error_msg += f"\nSub-exception {i+1}: {str(exc)}"
                st.error(error_msg)
