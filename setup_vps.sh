#!/bin/bash
# =============================================================================
# setup_vps.sh — Run this ONCE on your VPS as root or with sudo
#
# Configures sudo rules so the 'panda' user can manage nginx via systemctl.
# pm2 and screen already work natively since they run under 'panda'.
#
# Usage:
#   chmod +x setup_vps.sh
#   sudo bash setup_vps.sh
# =============================================================================

set -e

SSH_USER="panda"

echo ">>> Configuring sudoers for $SSH_USER (nginx only)"
SUDOERS_FILE="/etc/sudoers.d/panda-mcp"

# Detect systemctl path
SYSTEMCTL=$(which systemctl 2>/dev/null || echo /usr/bin/systemctl)

cat > "$SUDOERS_FILE" << EOF
# mcp-ssh sudoers — allows panda to manage nginx and read its logs
$SSH_USER ALL=(ALL) NOPASSWD: $SYSTEMCTL status nginx
$SSH_USER ALL=(ALL) NOPASSWD: $SYSTEMCTL restart nginx
$SSH_USER ALL=(ALL) NOPASSWD: /usr/bin/tail -n * /var/log/nginx/error.log
$SSH_USER ALL=(ALL) NOPASSWD: /usr/bin/tail -n * /var/log/nginx/access.log
EOF

chmod 440 "$SUDOERS_FILE"
visudo -c -f "$SUDOERS_FILE"
echo "    Sudoers file written: $SUDOERS_FILE"

echo ""
echo ">>> Setting up screen log directory"
LOG_DIR="/home/$SSH_USER/logs"
mkdir -p "$LOG_DIR"
chown "$SSH_USER:$SSH_USER" "$LOG_DIR"
echo "    Log directory: $LOG_DIR"

echo ""
echo ">>> Setup complete!"
echo ""
echo "    IMPORTANT: restart your Telegram bot screen session with logging enabled:"
echo ""
echo "    screen -S telegram-bot -X quit   # stop current session"
echo "    screen -L -Logfile ~/logs/telegram-bot.log -S telegram-bot python bot.py"
echo ""
echo "    This allows mcp-ssh to read the bot output via ssh_screen_logs."
echo ""
echo "    Add your mcp-ssh public key to ~/.ssh/authorized_keys:"
echo "    echo 'YOUR_PUBLIC_KEY' >> /home/$SSH_USER/.ssh/authorized_keys"
