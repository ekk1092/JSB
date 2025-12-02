#!/bin/bash

# Configuration
RESOURCE_GROUP="edemjob-assistant-rg"
ACR_NAME="jobassistantacr"
IMAGE_NAME="job-assistant:latest"

# Check for URL argument
if [ -z "$1" ]; then
    echo "Error: MCP Server URL argument is required."
    echo "Usage: $0 <MCP_SERVER_URL>"
    echo "Example: $0 https://mcp-server.happyriver-12345678.eastus.azurecontainerapps.io/sse"
    exit 1
fi

MCP_SERVER_URL=$1

echo "=================================================="
echo "Starting Deployment to Azure with Custom URL..."
echo "Resource Group: $RESOURCE_GROUP"
echo "ACR Name: $ACR_NAME"
echo "MCP Server URL: $MCP_SERVER_URL"
echo "=================================================="

# 1. Build Docker Image in ACR
echo ""
echo "[1/4] Building Docker image in Azure Container Registry..."
az acr build --registry $ACR_NAME --image $IMAGE_NAME --platform linux/amd64 .

if [ $? -ne 0 ]; then
    echo "Error: Docker build failed."
    exit 1
fi

# 2. Update MCP Server
# Note: We still update the server code, even if we are pointing clients elsewhere, 
# to ensure the whole stack is consistent if this URL points to this same deployment.
echo ""
echo "[2/4] Updating MCP Server..."
az containerapp update --name mcp-server --resource-group $RESOURCE_GROUP --image $ACR_NAME.azurecr.io/$IMAGE_NAME

if [ $? -ne 0 ]; then
    echo "Error: Failed to update MCP Server."
    exit 1
fi

# 3. Update Streamlit Client with new URL
echo ""
echo "[3/4] Updating Streamlit Client and setting MCP_SERVER_URL..."
az containerapp update --name streamlit-client --resource-group $RESOURCE_GROUP --image $ACR_NAME.azurecr.io/$IMAGE_NAME --set-env-vars MCP_SERVER_URL=$MCP_SERVER_URL

if [ $? -ne 0 ]; then
    echo "Error: Failed to update Streamlit Client."
    exit 1
fi

# 4. Update Slack Bot with new URL
echo ""
echo "[4/4] Updating Slack Bot and setting MCP_SERVER_URL..."
az containerapp update --name slack-bot --resource-group $RESOURCE_GROUP --image $ACR_NAME.azurecr.io/$IMAGE_NAME --set-env-vars MCP_SERVER_URL=$MCP_SERVER_URL

if [ $? -ne 0 ]; then
    echo "Error: Failed to update Slack Bot."
    exit 1
fi

echo ""
echo "=================================================="
echo "Deployment Complete! 🚀"
echo "Clients configured to connect to: $MCP_SERVER_URL"
echo "=================================================="
