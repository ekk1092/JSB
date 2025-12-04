# Azure Container Apps Deployment Guide

This guide provides a step-by-step process to deploy the Job Assistant application (MCP Server, Streamlit Client, and Slack Bot) to Azure Container Apps.

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

# OpenAI Secrets
AZURE_OPENAI_API_KEY="your_openai_api_key"
AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
AZURE_OPENAI_API_VERSION="2025-01-01-preview"
AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4.1"

# Slack Secrets
SLACK_BOT_TOKEN="xoxb-your-bot-token"
SLACK_APP_TOKEN="xapp-your-app-token"
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
  --env-vars \
    AZURE_OPENAI_API_KEY=$AZURE_OPENAI_API_KEY \
    AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT \
    AZURE_OPENAI_API_VERSION=$AZURE_OPENAI_API_VERSION \
    AZURE_OPENAI_DEPLOYMENT_NAME=$AZURE_OPENAI_DEPLOYMENT_NAME \
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
  --env-vars \
    MCP_SERVER_URL=$MCP_SERVER_URL \
    AZURE_OPENAI_API_KEY=$AZURE_OPENAI_API_KEY \
    AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT \
    AZURE_OPENAI_API_VERSION=$AZURE_OPENAI_API_VERSION \
    AZURE_OPENAI_DEPLOYMENT_NAME=$AZURE_OPENAI_DEPLOYMENT_NAME \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
  --command "streamlit" "run" "client_streamlit/app.py"
```

## 6. Deploy Slack Bot

Deploy the Slack bot using Socket Mode (no ingress needed).

```bash
az containerapp create \
  --name slack-bot \
  --resource-group $RESOURCE_GROUP \
  --environment $ENV_NAME \
  --image $ACR_NAME.azurecr.io/job-assistant:latest \
  --registry-server $ACR_NAME.azurecr.io \
  --registry-username $ACR_NAME \
  --registry-password $REGISTRY_PASSWORD \
  --env-vars \
    MCP_SERVER_URL=$MCP_SERVER_URL \
    SLACK_BOT_TOKEN=$SLACK_BOT_TOKEN \
    SLACK_APP_TOKEN=$SLACK_APP_TOKEN \
    AZURE_OPENAI_API_KEY=$AZURE_OPENAI_API_KEY \
    AZURE_OPENAI_ENDPOINT=$AZURE_OPENAI_ENDPOINT \
    AZURE_OPENAI_API_VERSION=$AZURE_OPENAI_API_VERSION \
    AZURE_OPENAI_DEPLOYMENT_NAME=$AZURE_OPENAI_DEPLOYMENT_NAME \
  --command "python" "client_slack/bot.py"
```

## Troubleshooting

-   **Image Pull Errors**: Ensure `admin-enabled` is true for your ACR and you are passing the correct username/password.
-   **Architecture Mismatch**: Ensure you build with `--platform linux/amd64` if deploying to Azure from a Mac (M1/M2).
-   **Connection Errors**: Verify the `MCP_SERVER_URL` is correct and accessible.

## 8. Verification

After deployment, verify the application:

1.  **Streamlit Client**:
    -   Navigate to the Streamlit URL.
    -   Verify the **UNCW Logo** is present in the sidebar.
    -   Type "what can you do?" in the chat.
    -   Confirm the assistant responds correctly (this verifies the SSE connection).

2.  **Slack Bot**:
    -   Message the bot in Slack.
    -   Upload a resume and confirm it is processed.
