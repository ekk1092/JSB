#!/bin/bash

# Configuration
RESOURCE_GROUP="${RESOURCE_GROUP:-edemjob-assistant-rg}"
ACR_NAME="${ACR_NAME:-jobassistantacr}"
IMAGE_NAME="${IMAGE_NAME:-job-assistant:latest}"
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
# Source utility functions
source ./deploy_utils.sh

echo -e "${YELLOW}==================================================${NC}"
echo -e "${YELLOW}   🚀 Starting Deployment to Azure...             ${NC}"
echo -e "${YELLOW}==================================================${NC}"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] --- New Deployment Started (Branch: $GIT_BRANCH) ---" >> "$LOG_FILE"
log "Configuration:"
log "  - Resource Group: ${YELLOW}$RESOURCE_GROUP${NC}"
log "  - ACR Name:       ${YELLOW}$ACR_NAME${NC}"
log "  - Image Name:     ${YELLOW}$IMAGE_NAME${NC}"
log "  - Git Branch:     ${YELLOW}$GIT_BRANCH${NC}"
echo ""

# 1. Build Docker Image in ACR
log "[1/3] Building Docker image in Azure Container Registry..."
az acr build --registry $ACR_NAME --image $IMAGE_NAME --platform linux/amd64 .

if [ $? -ne 0 ]; then
    error "Docker build failed."
    exit 1
fi
success "Docker image built successfully."
echo ""

# 2. Update MCP Server
log "[2/3] Updating MCP Server..."
az containerapp update --name mcp-server --resource-group $RESOURCE_GROUP --image $ACR_NAME.azurecr.io/$IMAGE_NAME --set-env-vars MCP_TRANSPORT=sse

if [ $? -ne 0 ]; then
    error "Failed to update MCP Server."
    exit 1
fi
success "MCP Server updated."
echo ""

# 3. Update Streamlit Client
log "[3/3] Updating Streamlit Client..."
az containerapp update --name streamlit-client --resource-group $RESOURCE_GROUP --image $ACR_NAME.azurecr.io/$IMAGE_NAME --set-env-vars STREAMLIT_SERVER_ENABLE_CORS=false STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false

if [ $? -ne 0 ]; then
    error "Failed to update Streamlit Client."
    exit 1
fi
success "Streamlit Client updated."
echo ""

# 4. Retrieve and Display URLs
log "Retrieving application URLs..."

echo -e "${GREEN}==================================================${NC}"
echo -e "${GREEN}   ✅ Deployment Complete!                        ${NC}"
echo -e "${GREEN}==================================================${NC}"

# Get Streamlit URL
STREAMLIT_URL=$(az containerapp show --name streamlit-client --resource-group $RESOURCE_GROUP --query properties.configuration.ingress.fqdn -o tsv)
if [ -n "$STREAMLIT_URL" ]; then
    echo -e "📱 ${GREEN}Streamlit App:${NC} https://$STREAMLIT_URL"
else
    echo -e "📱 ${RED}Streamlit App:${NC} URL not found (check ingress settings)"
fi

# Get MCP Server URL (useful for debugging)
MCP_URL=$(az containerapp show --name mcp-server --resource-group $RESOURCE_GROUP --query properties.configuration.ingress.fqdn -o tsv)
if [ -n "$MCP_URL" ]; then
    echo -e "⚙️  ${GREEN}MCP Server:${NC}    https://$MCP_URL"
fi

echo ""
log "Deployment finished successfully."
