# mcp-ssh

MCP server for Claude Desktop that allows secure management of a remote VPS via SSH.

## Security model

| Layer | Control |
|---|---|
| VPS | Dedicated `claude-agent` user with sudo restricted to specific services only |
| SSH | Dedicated Ed25519 key with passphrase, separate from your personal key |
| MCP | Service and repo allowlist — no arbitrary shell execution |
| Audit | Every executed command is logged to `~/.mcp-ssh/audit.log` |
| Transport | stdio (no port exposed on the local network) |

## Available tools

| Tool | Description |
|---|---|
| `ssh_ping` | Tests connectivity — returns hostname and uptime |
| `ssh_service_status` | systemctl status of an allowed service |
| `ssh_restart_service` | Restarts an allowed service |
| `ssh_service_logs` | Last N lines of a service's journal |
| `ssh_disk_usage` | Disk usage (df -h) |
| `ssh_memory_usage` | Memory usage + top processes |
| `ssh_uptime` | Uptime and load average |
| `ssh_git_pull` | git pull in an allowed repo path |
| `ssh_git_status` | git status + last 5 commits of a repo |
| `ssh_read_file` | Reads a remote file (max 500 lines) |
| `ssh_list_dir` | Lists files in a directory (ls -lah) |
| `ssh_audit_log` | Displays the local audit log |
| `ssh_config_info` | Shows current config (no secrets) |

## Installation

### 1. VPS — create dedicated user

```bash
# On the VPS as root:
sudo bash setup_vps.sh
```

Edit `setup_vps.sh` to include your services before running.

### 2. Windows — install dependencies and generate SSH key

```bat
install.bat
```

The script installs dependencies and generates the `mcp_ssh_ed25519` key.

### 3. VPS — authorize the public key

```bash
echo "your-public-key" >> /home/claude-agent/.ssh/authorized_keys
```

### 4. Test the connection manually

```bat
ssh -i C:\Users\panta\.ssh\mcp_ssh_ed25519 claude-agent@your.vps.ip
```

### 5. claude_desktop_config.json

Add to `mcpServers`:

```json
"mcp-ssh": {
  "command": "python",
  "args": ["C:\\Users\\panta\\mcp-ssh\\server.py"],
  "env": {
    "MCP_SSH_HOST": "your.vps.ip",
    "MCP_SSH_PORT": "22",
    "MCP_SSH_USER": "claude-agent",
    "MCP_SSH_KEY_PATH": "C:\\Users\\panta\\.ssh\\mcp_ssh_ed25519",
    "MCP_SSH_KEY_PASSPHRASE": "your-passphrase",
    "MCP_SSH_ALLOWED_SERVICES": "telegram-bot,pandapoints-dapp,nginx",
    "MCP_SSH_ALLOWED_REPOS": "/home/claude-agent/pandapoints-dapp,/home/claude-agent/telegram-bot"
  }
}
```

### 6. Restart Claude Desktop

---

## Adding new services

1. Edit `setup_vps.sh`, add the service to the `SERVICES` array, re-run on the VPS.
2. Update `MCP_SSH_ALLOWED_SERVICES` in `claude_desktop_config.json`.
3. Restart Claude Desktop.

## Audit log

The local log is at `%USERPROFILE%\.mcp-ssh\audit.log`. Example:

```
2026-05-16T14:23:01 | INFO | OK | service_logs | telegram-bot last=50
2026-05-16T14:25:10 | INFO | OK | restart_service | pandapoints-dapp -> exit 0
2026-05-16T14:30:44 | INFO | FAIL | restart_service | BLOCKED: mysql
```
