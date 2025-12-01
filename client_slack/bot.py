import os
import sys
import logging
import asyncio
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AzureOpenAI
from dotenv import load_dotenv
import aiohttp
import certifi
import ssl

# Load environment variables
load_dotenv()

# Fix for macOS SSL certificate issue
os.environ['SSL_CERT_FILE'] = certifi.where()
ssl_context = ssl.create_default_context(cafile=certifi.where())

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Slack App
# Initialize Slack App
from slack_sdk.web.async_client import AsyncWebClient
client_slack = AsyncWebClient(token=os.environ.get("SLACK_BOT_TOKEN"), ssl=ssl_context)
app = AsyncApp(client=client_slack)

# Initialize Azure OpenAI Client
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)
deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o")

# Store user context (resume text)
user_context = {}

import io

async def download_file(file_url, token):
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(file_url, headers=headers, ssl=ssl_context) as resp:
            if resp.status == 200:
                return await resp.read() # Return bytes
    return None

@app.event("message")
async def handle_message_events(body, logger, say):
    event = body.get("event", {})
    user_id = event.get("user")
    text = event.get("text", "")
    files = event.get("files", [])
    
    # Handle file uploads (Resume)
    if files:
        for file in files:
            file_type = file.get("filetype")
            if file_type in ["text", "markdown", "pdf", "docx"]:
                content_bytes = await download_file(file.get("url_private"), os.environ.get("SLACK_BOT_TOKEN"))
                
                if content_bytes:
                    text_content = ""
                    try:
                        if file_type in ["text", "markdown"]:
                            text_content = content_bytes.decode("utf-8")
                        elif file_type == "pdf":
                            import pypdf
                            pdf_file = io.BytesIO(content_bytes)
                            pdf_reader = pypdf.PdfReader(pdf_file)
                            for page in pdf_reader.pages:
                                text_content += page.extract_text() + "\n"
                        elif file_type == "docx":
                            import docx
                            docx_file = io.BytesIO(content_bytes)
                            doc = docx.Document(docx_file)
                            for para in doc.paragraphs:
                                text_content += para.text + "\n"
                        
                        user_context[user_id] = text_content
                        await say(f"Resume received and processed! I've stored it for this session.")
                    except Exception as e:
                        logger.error(f"Error parsing file: {e}")
                        await say(f"Error processing file: {str(e)}")
                else:
                    await say("Failed to download resume.")
        return

    # Prepare context
    resume_text = user_context.get(user_id, "No resume uploaded yet.")
    
    # Run MCP interaction
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
            
            # List tools
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
            
            # Add local tool for uploading DOCX
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": "upload_docx",
                    "description": "Converts markdown text to a DOCX file and uploads it to the Slack channel. Use this when the user asks for a downloadable file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "markdown_content": {
                                "type": "string",
                                "description": "The markdown content of the resume or document."
                            },
                            "filename": {
                                "type": "string",
                                "description": "The name of the file to create (e.g. 'resume.docx').",
                                "default": "resume.docx"
                            }
                        },
                        "required": ["markdown_content"]
                    }
                }
            })

            # Prepare messages
            messages = [
                {"role": "system", "content": f"You are a helpful job assistant. You have access to tools. Use the user's resume if needed: {resume_text}. If the user asks for a downloadable file, use the 'upload_docx' tool."},
                {"role": "user", "content": text}
            ]

            # Call LLM
            response = client.chat.completions.create(
                model=deployment_name,
                messages=messages,
                tools=openai_tools,
                tool_choice="auto"
            )
            
            response_message = response.choices[0].message
            
            if response_message.tool_calls:
                messages.append(response_message)
                
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = eval(tool_call.function.arguments)
                    
                    await say(f"Thinking... (Calling {function_name})")
                    
                    if function_name == "upload_docx":
                        # Handle local tool
                        try:
                            import docx
                            doc = docx.Document()
                            # Simple markdown to text conversion (stripping some md syntax could be better but keeping it simple)
                            doc.add_paragraph(function_args.get("markdown_content"))
                            
                            bio = io.BytesIO()
                            doc.save(bio)
                            file_bytes = bio.getvalue()
                            
                            # Upload to Slack
                            filename = function_args.get("filename", "resume.docx")
                            await app.client.files_upload_v2(
                                channel=event.get("channel"),
                                file=file_bytes,
                                filename=filename,
                                title=filename,
                                initial_comment="Here is your downloadable resume."
                            )
                            result_content = "File uploaded successfully to Slack."
                        except Exception as e:
                            logger.error(f"Error uploading file: {e}")
                            result_content = f"Error uploading file: {str(e)}"
                            
                        messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": result_content
                        })
                    else:
                        # Handle MCP tool
                        result = await session.call_tool(function_name, arguments=function_args)
                        
                        messages.append({
                            "tool_call_id": tool_call.id,
                            "role": "tool",
                            "name": function_name,
                            "content": str(result.content)
                        })
                
                second_response = client.chat.completions.create(
                    model=deployment_name,
                    messages=messages
                )
                await say(second_response.choices[0].message.content)
            else:
                await say(response_message.content)

async def main():
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    await handler.start_async()

if __name__ == "__main__":
    asyncio.run(main())
