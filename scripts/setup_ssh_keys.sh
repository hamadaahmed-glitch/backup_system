#!/usr/bin/env bash
#
# setup_ssh_keys.sh
# Run this on the LAPTOP (Client) as your normal user.
# Generates a dedicated SSH key pair and exports it to the Desktop.
#

set -euo pipefail

# Color formatting
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1" >&2; }

KEY_PATH="${HOME}/.ssh/id_ed25519_backup"

echo "================================================================="
echo "      LAPTOP TO DESKTOP SSH AUTHENTICATION SETUP                "
echo "================================================================="

# Prompt for Desktop target configuration
read -rp "Enter Desktop IP address or hostname: " DESKTOP_IP
read -rp "Enter Desktop username [default: backup-user]: " DESKTOP_USER
DESKTOP_USER=${DESKTOP_USER:-backup-user}

read -rp "Enter Desktop SSH Port [default: 22]: " DESKTOP_PORT
DESKTOP_PORT=${DESKTOP_PORT:-22}

# 1. Key Generation
if [[ -f "$KEY_PATH" ]]; then
    log_warn "Key pair '${KEY_PATH}' already exists. Reusing existing key."
else
    log_info "Generating Ed25519 key pair without passphrase..."
    ssh-keygen -t ed25519 -N "" -f "$KEY_PATH" -C "backup-client-$(hostname)-$(date +%Y%m%d)"
    log_success "SSH key generated at ${KEY_PATH}"
fi

# 2. Copy Public Key to Remote Desktop
log_info "Deploying public key to ${DESKTOP_USER}@${DESKTOP_IP}..."
echo "You may be prompted for the password of '${DESKTOP_USER}' on the Desktop:"

if command -v ssh-copy-id &>/dev/null; then
    ssh-copy-id -i "${KEY_PATH}.pub" -p "$DESKTOP_PORT" "${DESKTOP_USER}@${DESKTOP_IP}"
else
    # Fallback if ssh-copy-id is missing
    cat "${KEY_PATH}.pub" | ssh -p "$DESKTOP_PORT" "${DESKTOP_USER}@${DESKTOP_IP}" \
        "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
fi

# 3. Connection Verification
log_info "Validating passwordless login..."
if ssh -i "$KEY_PATH" -p "$DESKTOP_PORT" -o BatchMode=yes -o StrictHostKeyChecking=accept-new "${DESKTOP_USER}@${DESKTOP_IP}" "echo 'Auth test successful'" &>/dev/null; then
    echo ""
    echo "================================================================="
    log_success "SSH Key exchange completed successfully!"
    echo "================================================================="
    echo -e " Identity File : ${GREEN}${KEY_PATH}${NC}"
    echo -e " Desktop Host  : ${GREEN}${DESKTOP_IP}${NC}"
    echo -e " Remote User   : ${GREEN}${DESKTOP_USER}${NC}"
    echo "================================================================="
    echo "You can now execute the client application without password prompts."
    echo ""
else
    log_error "Connection test failed. Verify network connectivity and user permissions."
    exit 1
fi