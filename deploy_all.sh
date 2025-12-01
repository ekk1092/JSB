#!/bin/bash

# Configuration
RESOURCE_GROUP="edemjob-assistant-rg"
ACR_NAME="jobassistantacr"
IMAGE_NAME="job-assistant:latest"

echo "=================================================="
echo "Starting Deployment to Azure..."
echo "Resource Group: $RESOURCE_GROUP"
echo "ACR Name: $ACR_NAME"
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
echo ""
echo "[2/4] Updating MCP Server..."
az containerapp update --name mcp-server --resource-group $RESOURCE_GROUP --image $ACR_NAME.azurecr.io/$IMAGE_NAME

if [ $? -ne 0 ]; then
    echo "Error: Failed to update MCP Server."
    exit 1
fi

# 3. Update Streamlit Client
echo ""
echo "[3/4] Updating Streamlit Client..."
az containerapp update --name streamlit-client --resource-group $RESOURCE_GROUP --image $ACR_NAME.azurecr.io/$IMAGE_NAME

if [ $? -ne 0 ]; then
    echo "Error: Failed to update Streamlit Client."
    exit 1
fi

# 4. Update Slack Bot
echo ""
echo "[4/4] Updating Slack Bot..."
az containerapp update --name slack-bot --resource-group $RESOURCE_GROUP --image $ACR_NAME.azurecr.io/$IMAGE_NAME

if [ $? -ne 0 ]; then
    echo "Error: Failed to update Slack Bot."
    exit 1
fi

echo ""
echo "=================================================="
echo "Deployment Complete! 🚀"
echo "=================================================="
