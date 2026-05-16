#!/bin/bash
# =============================================================================
# setup_vps.sh — Run this ONCE on your VPS (as root or with sudo)
#
# Creates the `claude-agent` user with minimal permissions and configures
# sudo rules so it can only manage specific services.
#
# Usage:
#   chmod +x setup_vps.sh
#   sudo bash setup_vps.sh
# =============================================================================

set -e

USER="claude-agent"
SERVICES=("telegram-bot" "pandapoints-dapp" "nginx")

echo ">>> Creating user: $USER"
if id "$USER" &>/dev/null; then
    echo "    User already exists, skipping creation."
else
    useradd -m -s /bin/bash "$USER"
    echo "    User created."
fi

echo ">>> Setting up .ssh directory"
SSH_DIR="/home/$USER/.ssh"
mkdir -p "$SSH_DIR"
touch "$SSH_DIR/authorized_keys"
chmod 700 "$SSH_DIR"
chmod 600 "$SSH_DIR/authorized_keys"
chown -R "$USER:$USER" "$SSH_DIR"

echo ""
echo ">>> NEXT STEP: paste your MCP SSH public key into:"
echo "    $SSH_DIR/authorized_keys"
echo ""
echo "    On your Windows machine, run:"
echo "    cat C:\\Users\\panta\\.ssh\\mcp_ssh_ed25519.pub"
echo "    Then paste the output into authorized_keys."
echo ""

echo ">>> Writing sudoers rules for $USER"
SUDOERS_FILE="/etc/sudoers.d/claude-agent"

{
    echo "# Sudoers rules for mcp-ssh claude-agent user"
    echo "# Only allows specific systemctl commands — no general sudo"
    echo ""
    for svc in "${SERVICES[@]}"; do
        echo "$USER ALL=(ALL) NOPASSWD: /bin/systemctl status $svc"
        echo "$USER ALL=(ALL) NOPASSWD: /bin/systemctl restart $svc"
        echo "$USER ALL=(ALL) NOPASSWD: /bin/journalctl -u $svc *"
    done
} > "$SUDOERS_FILE"

chmod 440 "$SUDOERS_FILE"
visudo -c -f "$SUDOERS_FILE"
echo "    Sudoers file written and validated: $SUDOERS_FILE"

echo ""
echo ">>> Setup complete!"
echo ""
echo "    Summary of what was done:"
echo "      - User '$USER' created (or already existed)"
echo "      - .ssh/authorized_keys created and ready for your public key"
echo "      - sudo rules: only systemctl status/restart for: ${SERVICES[*]}"
echo ""
echo "    Remember to:"
echo "      1. Paste your public key into $SSH_DIR/authorized_keys"
echo "      2. Test SSH from your Windows machine before configuring Claude Desktop"
echo "      3. Add more services to SERVICES array and re-run if needed"
