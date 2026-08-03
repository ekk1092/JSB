# Azure Container Apps Deployment Guide

This guide provides a step-by-step process to deploy the Job Assistant application (MCP Server and Streamlit Client) to Azure Container Apps.

## Prerequisites

1.  **Azure CLI**: Ensure you have the Azure CLI installed and logged in (`az login`).
2.  **Docker**: Ensure Docker is installed (optional if building in cloud, but good for local testing).
3.  **Resource Group**: A resource group created in Azure (e.g., `edemjob-assistant-rg`).

## 1. Set Environment Variables

Set these variables in your terminal to make the commands easier to run. Replace the values with your actual secrets.

```bash
# Azure Configuration
RESOURCE_GROUP="edemjob-assistant-rg"
LOCATION="centralus"
ACR_NAME="jobassistantacr"
ENV_NAME="job-assistant-env"

# Google Gemini Secrets (free tier)
# Get a free API key at https://aistudio.google.com/apikey
GEMINI_API_KEY="your_gemini_api_key"
GEMINI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_MODEL="gemini-3.5-flash"

```

## 2. Create Azure Resources

If you haven't created them yet:

```bash
# Create Resource Group
az group create --name $RESOURCE_GROUP --location $LOCATION

# Create Container Registry (ACR)
az acr create --resource-group $RESOURCE_GROUP --name $ACR_NAME --sku Basic --admin-enabled true

# Create Container Apps Environment
az containerapp env create --name $ENV_NAME --resource-group $RESOURCE_GROUP --location $LOCATION
```

## 3. Build Docker Image

Build the Docker image in the cloud (ACR) to ensure compatibility with Azure (Linux/AMD64).

```bash
az acr build --registry $ACR_NAME --image job-assistant:latest --platform linux/amd64 .
```

## 4. Deploy MCP Server

Deploy the backend server first. It exposes an SSE endpoint for clients.

```bash
# Get Registry Password
REGISTRY_PASSWORD=$(az acr credential show -n $ACR_NAME --query "passwords[0].value" -o tsv)

# Deploy Server
# NOTE: Sensitive values (API keys) are passed as SECRETS, not env-vars,
# so they never appear in plaintext in the container app config or logs.
az containerapp create \
  --name mcp-server \
  --resource-group $RESOURCE_GROUP \
  --environment $ENV_NAME \
  --image $ACR_NAME.azurecr.io/job-assistant:latest \
  --target-port 8080 \
  --ingress external \
  --registry-server $ACR_NAME.azurecr.io \
  --registry-username $ACR_NAME \
  --registry-password $REGISTRY_PASSWORD \
  --secrets \
    gemini-api-key=$GEMINI_API_KEY \
  --env-vars \
    GEMINI_BASE_URL=$GEMINI_BASE_URL \
    GEMINI_MODEL=$GEMINI_MODEL \
    GEMINI_API_KEY=secretref:gemini-api-key \
    MCP_TRANSPORT="sse" \
  --command "python" "server/main.py"
```

**Note the Server URL**: After deployment, get the URL (e.g., `https://mcp-server.xyz.azurecontainerapps.io`). You will need it for the clients.

```bash
SERVER_URL=$(az containerapp show --name mcp-server --resource-group $RESOURCE_GROUP --query properties.configuration.ingress.fqdn -o tsv)
MCP_SERVER_URL="https://$SERVER_URL/sse"
echo "MCP Server URL: $MCP_SERVER_URL"
```

## 5. Deploy Streamlit Client

Deploy the web interface, connecting it to the MCP Server.

```bash
az containerapp create \
  --name streamlit-client \
  --resource-group $RESOURCE_GROUP \
  --environment $ENV_NAME \
  --image $ACR_NAME.azurecr.io/job-assistant:latest \
  --target-port 8501 \
  --ingress external \
  --registry-server $ACR_NAME.azurecr.io \
  --registry-username $ACR_NAME \
  --registry-password $REGISTRY_PASSWORD \
  --secrets \
    gemini-api-key=$GEMINI_API_KEY \
  --env-vars \
    MCP_SERVER_URL=$MCP_SERVER_URL \
    GEMINI_BASE_URL=$GEMINI_BASE_URL \
    GEMINI_MODEL=$GEMINI_MODEL \
    GEMINI_API_KEY=secretref:gemini-api-key \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
  --command "streamlit" "run" "client_streamlit/app.py"
```

## Troubleshooting

-   **Image Pull Errors**: Ensure `admin-enabled` is true for your ACR and you are passing the correct username/password.
-   **Architecture Mismatch**: Ensure you build with `--platform linux/amd64` if deploying to Azure from a Mac (M1/M2).
-   **Connection Errors**: Verify the `MCP_SERVER_URL` is correct and accessible.
-   **Gemini API Errors**: Verify `GEMINI_API_KEY` is valid and `GEMINI_MODEL` is a valid model (e.g., `gemini-3.5-flash`).

## 8. Verification

After deployment, verify the application:

1.  **Streamlit Client**:
    -   Navigate to the Streamlit URL.
    -   Verify the **UNCW Logo** is present in the sidebar.
    -   Type "what can you do?" in the chat.
    -   Confirm the assistant responds correctly (this verifies the SSE connection).