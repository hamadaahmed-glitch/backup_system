#!/usr/bin/env bash
#
# setup_desktop_user.sh
# Run this on the DESKTOP machine as root (or with sudo).
# Configures a dedicated backup user and prepares storage directories.
#

set -euo pipefail

# Configuration
BACKUP_USER="backup-user"
STORAGE_ROOT="/srv/backups"
SSH_PORT="22"

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

# 1. Root check
if [[ "$EUID" -ne 0 ]]; then
    log_error "This script must be executed as root or via sudo."
    exit 1
fi

log_info "Preparing Desktop storage environment..."

# 2. Package installation
log_info "Ensuring system packages (rsync, openssh-server) are installed..."
apt-get update -qq
apt-get install -y -qq rsync openssh-server ufw

# 3. Enable and start SSH service
log_info "Verifying OpenSSH daemon state..."
systemctl enable --now ssh

# 4. User creation
if id "$BACKUP_USER" &>/dev/null; then
    log_warn "User '${BACKUP_USER}' already exists. Skipping user creation."
else
    log_info "Creating dedicated service user '${BACKUP_USER}'..."
    useradd -m -s /bin/bash -c "Linux Backup Daemon Account" "$BACKUP_USER"
    log_success "User '${BACKUP_USER}' created."
fi

USER_HOME=$(eval echo "~$BACKUP_USER")

# 5. SSH directory permissions
log_info "Setting up SSH folder permissions for ${BACKUP_USER}..."
SSH_DIR="${USER_HOME}/.ssh"
AUTH_KEYS="${SSH_DIR}/authorized_keys"

mkdir -p "$SSH_DIR"
touch "$AUTH_KEYS"
chmod 700 "$SSH_DIR"
chmod 600 "$AUTH_KEYS"
chown -R "${BACKUP_USER}:${BACKUP_USER}" "$SSH_DIR"

# 6. Prepare Storage Root Directory
log_info "Configuring storage repository path at '${STORAGE_ROOT}'..."
mkdir -p "$STORAGE_ROOT"
chown -R "${BACKUP_USER}:${BACKUP_USER}" "$STORAGE_ROOT"
chmod 750 "$STORAGE_ROOT"

# 7. Firewall (UFW) Configuration
if ufw status | grep -qw "active"; then
    log_info "UFW active. Ensuring SSH port ${SSH_PORT} is accessible..."
    ufw allow "${SSH_PORT}/tcp" comment "Allow SSH for Backup Service"
    ufw reload
fi

# 8. Display System Summary
DESKTOP_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "================================================================="
log_success "Desktop backup target is configured!"
echo "================================================================="
echo -e " Target Host IP      : ${GREEN}${DESKTOP_IP}${NC}"
echo -e " Backup User Name    : ${GREEN}${BACKUP_USER}${NC}"
echo -e " Storage Repository  : ${GREEN}${STORAGE_ROOT}${NC}"
echo -e " SSH Authorized Keys : ${GREEN}${AUTH_KEYS}${NC}"
echo "================================================================="
echo "Next step: Run 'scripts/setup_ssh_keys.sh' on your Laptop."
echo ""