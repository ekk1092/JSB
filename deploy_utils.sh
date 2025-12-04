#!/bin/bash

# Log file
LOG_FILE="deployment_history.log"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Helper function for logging with timestamps
log() {
    TIMESTAMP=$(date +'%Y-%m-%d %H:%M:%S')
    echo -e "${BLUE}[$TIMESTAMP]${NC} $1"
    # Strip ANSI codes using perl for better compatibility
    CLEAN_MSG=$(echo "$1" | perl -pe 's/\e\[?.*?[\@-~]//g')
    echo "[$TIMESTAMP] INFO: $CLEAN_MSG" >> "$LOG_FILE"
}

success() {
    TIMESTAMP=$(date +'%Y-%m-%d %H:%M:%S')
    echo -e "${GREEN}[$TIMESTAMP] SUCCESS:${NC} $1"
    CLEAN_MSG=$(echo "$1" | perl -pe 's/\e\[?.*?[\@-~]//g')
    echo "[$TIMESTAMP] SUCCESS: $CLEAN_MSG" >> "$LOG_FILE"
}

error() {
    TIMESTAMP=$(date +'%Y-%m-%d %H:%M:%S')
    echo -e "${RED}[$TIMESTAMP] ERROR:${NC} $1"
    CLEAN_MSG=$(echo "$1" | perl -pe 's/\e\[?.*?[\@-~]//g')
    echo "[$TIMESTAMP] ERROR: $CLEAN_MSG" >> "$LOG_FILE"
}
