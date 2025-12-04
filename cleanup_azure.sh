#!/bin/bash

# Source utility functions
source ./deploy_utils.sh

RESOURCE_GROUP="${RESOURCE_GROUP:-edemjob-assistant-rg}"
ACR_NAME="${ACR_NAME:-jobassistantacr}"
KEEP_IMAGES=5

echo -e "${YELLOW}==================================================${NC}"
echo -e "${YELLOW}   🧹 Starting Azure Cleanup...                   ${NC}"
echo -e "${YELLOW}==================================================${NC}"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] --- Cleanup Started ---" >> "$LOG_FILE"

# -----------------------------------------------------------------------------
# 1. Clean up ACR Images
# -----------------------------------------------------------------------------
log "Cleaning up ACR images (keeping top $KEEP_IMAGES)..."

# Get list of repositories
REPOS=$(az acr repository list --name $ACR_NAME --output tsv)

for REPO in $REPOS; do
    log "Processing repository: $REPO"
    
    # Get all manifests sorted by timestamp (newest first)
    # We use --orderby time_desc to ensure we keep the latest
    MANIFESTS=$(az acr repository show-manifests --name $ACR_NAME --repository $REPO --orderby time_desc --query "[].digest" --output tsv)
    
    COUNT=0
    for DIGEST in $MANIFESTS; do
        COUNT=$((COUNT + 1))
        if [ $COUNT -le $KEEP_IMAGES ]; then
            # Skip the first N images (keep them)
            continue
        fi
        
        # Delete the rest
        log "  - Deleting old image: $REPO@$DIGEST"
        az acr repository delete --name $ACR_NAME --image $REPO@$DIGEST --yes > /dev/null 2>&1
        if [ $? -eq 0 ]; then
             echo "    Deleted $REPO@$DIGEST" >> "$LOG_FILE"
        else
             error "Failed to delete $REPO@$DIGEST"
        fi
    done
done

success "ACR cleanup complete."

# -----------------------------------------------------------------------------
# 2. Clean up Container App Revisions
# -----------------------------------------------------------------------------
APPS=("mcp-server" "streamlit-client" "slack-bot")

log "Cleaning up inactive Container App revisions..."

for APP in "${APPS[@]}"; do
    log "Processing app: $APP"
    
    # Get all revisions that are NOT active (provisioningState=Succeeded, but traffic=0 usually implies inactive if in single revision mode, 
    # but specifically we look for revisions that are not the current traffic target).
    # A simpler approach for "clearing previous revisions" is to list revisions that are inactive.
    
    # List revisions that are not active
    INACTIVE_REVISIONS=$(az containerapp revision list --name $APP --resource-group $RESOURCE_GROUP --query "[?properties.active==\`false\`].name" -o tsv)
    
    for REV in $INACTIVE_REVISIONS; do
        log "  - Deactivating/Deleting revision: $REV"
        az containerapp revision deactivate --name $APP --resource-group $RESOURCE_GROUP --revision $REV > /dev/null 2>&1
        # Note: You can't always 'delete' a revision easily via CLI in the same way as other resources, 
        # but deactivating them ensures they don't consume resources. 
        # Currently, 'az containerapp revision delete' does not exist in standard CLI, revisions are immutable snapshots.
        # They are garbage collected or hidden when deactivated.
        echo "    Deactivated $REV" >> "$LOG_FILE"
    done
done

success "Revision cleanup complete."
echo "[$(date +'%Y-%m-%d %H:%M:%S')] --- Cleanup Finished ---" >> "$LOG_FILE"
