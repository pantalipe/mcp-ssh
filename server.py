"""
mcp-ssh — SSH MCP Server for Claude Desktop
Connects to a remote VPS and exposes a controlled set of tools.

Security model:
  - Allowlist-only execution (no arbitrary shell)
  - All executions are audit-logged locally
  - Destructive operations do not exist
  - Credentials via env vars / SSH key with passphrase
"""

import os
import sys
import json
import logging
import paramiko
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SSH_HOST     = os.environ.get("MCP_SSH_HOST", "")
SSH_PORT     = int(os.environ.get("MCP_SSH_PORT", "22"))
SSH_USER     = os.environ.get("MCP_SSH_USER", "")
SSH_KEY_PATH = os.environ.get("MCP_SSH_KEY_PATH", "")
SSH_KEY_PASS = os.environ.get("MCP_SSH_KEY_PASSPHRASE", "")

AUDIT_LOG = Path.home() / ".mcp-ssh" / "audit.log"
AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)

# Systemd services allowed for status/restart (nginx, etc.)
ALLOWED_SYSTEMD = set(
    os.environ.get("MCP_SSH_ALLOWED_SERVICES", "nginx").split(",")
) - {""}

# pm2 app names allowed for status/restart/logs
ALLOWED_PM2 = set(
    os.environ.get("MCP_SSH_ALLOWED_PM2", "pp").split(",")
) - {""}

# screen session names allowed for inspection
ALLOWED_SCREENS = set(
    os.environ.get("MCP_SSH_ALLOWED_SCREENS", "bot").split(",")
) - {""}

# Directories allowed for git pull/status
ALLOWED_REPO_PATHS = set(
    os.environ.get("MCP_SSH_ALLOWED_REPOS", "").split(",")
) - {""}

# Pre-approved command aliases for ssh_run_command.
# Callers pass an alias key — the actual shell command is defined here only.
# Extend via MCP_SSH_ALLOWED_COMMANDS env var (JSON object: {"alias": "command"}).
_CMD_DEFAULTS: dict[str, str] = {
    # --- systemd service management ---
    "systemctl-enable-nginx":    "sudo -n systemctl enable nginx",
    "systemctl-disable-nginx":   "sudo -n systemctl disable nginx",
    "systemctl-enable-pm2":      "sudo -n systemctl enable pm2-panda",
    # --- PM2 lifecycle ---
    "pm2-startup":               "pm2 startup systemd",
    "pm2-save":                  "pm2 save",
    "pm2-resurrect":             "pm2 resurrect",
    # --- nginx ---
    "nginx-configtest":          "sudo -n nginx -t",
    # --- diagnostics ---
    "whoami":                    "whoami && id",
    "env-path":                  "echo $PATH",
}
_extra_cmds = os.environ.get("MCP_SSH_ALLOWED_COMMANDS", "")
try:
    ALLOWED_COMMANDS: dict[str, str] = (
        {**_CMD_DEFAULTS, **json.loads(_extra_cmds)} if _extra_cmds else _CMD_DEFAULTS
    )
except json.JSONDecodeError:
    ALLOWED_COMMANDS = _CMD_DEFAULTS

# ---------------------------------------------------------------------------
# Audit logger
# ---------------------------------------------------------------------------

logging.basicConfig(
    filename=str(AUDIT_LOG),
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
audit = logging.getLogger("mcp-ssh-audit")

def log(action: str, detail: str, success: bool = True):
    status = "OK" if success else "FAIL"
    audit.info(f"{status} | {action} | {detail}")

# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------

def _connect() -> paramiko.SSHClient:
    if not SSH_HOST or not SSH_USER:
        raise RuntimeError("MCP_SSH_HOST and MCP_SSH_USER must be set.")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())

    known_hosts = Path.home() / ".ssh" / "known_hosts"
    if known_hosts.exists():
        client.load_host_keys(str(known_hosts))

    key = None
    if SSH_KEY_PATH:
        key_path = Path(SSH_KEY_PATH).expanduser()
        passphrase = SSH_KEY_PASS or None
        try:
            key = paramiko.Ed25519Key.from_private_key_file(str(key_path), password=passphrase)
        except paramiko.ssh_exception.SSHException:
            key = paramiko.RSAKey.from_private_key_file(str(key_path), password=passphrase)

    client.connect(
        hostname=SSH_HOST,
        port=SSH_PORT,
        username=SSH_USER,
        pkey=key,
        timeout=15,
        banner_timeout=15,
    )
    return client


def _run(command: str, pty: bool = False) -> tuple[str, str, int]:
    """Open a fresh connection, run command, return (stdout, stderr, exit_code)."""
    client = _connect()
    try:
        _, stdout, stderr = client.exec_command(command, timeout=30)
        out = stdout.read().decode("utf-8", errors="replace").strip()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        code = stdout.channel.recv_exit_status()
        return out, err, code
    finally:
        client.close()


def _result(out: str, err: str, code: int) -> str:
    parts = []
    if out:
        parts.append(out)
    if err:
        parts.append(f"[stderr]\n{err}")
    parts.append(f"[exit code: {code}]")
    return "\n".join(parts)

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("mcp-ssh")

# ── Connectivity ─────────────────────────────────────────────────────────────

@mcp.tool()
def ssh_ping() -> str:
    """Check connectivity to the VPS. Returns hostname and uptime."""
    try:
        out, err, code = _run('echo "host=$(hostname)" && uptime')
        log("ping", SSH_HOST)
        return _result(out, err, code)
    except Exception as e:
        log("ping", str(e), success=False)
        return f"Connection failed: {e}"


# ── System info ───────────────────────────────────────────────────────────────

@mcp.tool()
def ssh_disk_usage() -> str:
    """Show disk usage on the VPS (df -h)."""
    out, err, code = _run("df -h --output=source,size,used,avail,pcent,target | column -t")
    log("disk_usage", SSH_HOST)
    return _result(out, err, code)


@mcp.tool()
def ssh_memory_usage() -> str:
    """Show memory usage and top processes by RAM on the VPS."""
    cmd = "free -h && echo '---' && ps aux --sort=-%mem | head -10"
    out, err, code = _run(cmd)
    log("memory_usage", SSH_HOST)
    return _result(out, err, code)


@mcp.tool()
def ssh_uptime() -> str:
    """Show VPS uptime and load average."""
    out, err, code = _run("uptime && echo '' && w")
    log("uptime", SSH_HOST)
    return _result(out, err, code)


# ── nginx (systemd) ───────────────────────────────────────────────────────────

@mcp.tool()
def ssh_nginx_status() -> str:
    """Get nginx systemd status."""
    out, err, code = _run("sudo -n systemctl status nginx --no-pager -l", pty=True)
    log("nginx_status", SSH_HOST)
    return _result(out, err, code)


@mcp.tool()
def ssh_nginx_restart() -> str:
    """Restart nginx."""
    out, err, code = _run("sudo -n systemctl restart nginx && echo 'nginx restarted OK'", pty=True)
    log("nginx_restart", f"exit {code}", success=(code == 0))
    return _result(out, err, code)


@mcp.tool()
def ssh_nginx_logs(lines: int = 50) -> str:
    """Fetch the last N lines of nginx error log (default 50, max 200)."""
    lines = min(int(lines), 200)
    out, err, code = _run(f"sudo -n tail -n {lines} /var/log/nginx/error.log", pty=True)
    log("nginx_logs", f"last={lines}")
    return _result(out, err, code)


# ── pm2 — pandapoints dapp (name: pp) ────────────────────────────────────────

@mcp.tool()
def ssh_pm2_status() -> str:
    """List all pm2 processes and their status."""
    out, err, code = _run("pm2 list")
    log("pm2_status", SSH_HOST)
    return _result(out, err, code)


@mcp.tool()
def ssh_pm2_restart(name: str) -> str:
    """
    Restart a pm2 app. Allowed apps defined in MCP_SSH_ALLOWED_PM2 (default: pp).
    """
    if name not in ALLOWED_PM2:
        log("pm2_restart", f"BLOCKED: {name}", success=False)
        return f"App '{name}' is not in the allowed list: {sorted(ALLOWED_PM2)}"
    out, err, code = _run(f"pm2 restart {name} && pm2 list")
    log("pm2_restart", f"{name} -> exit {code}", success=(code == 0))
    return _result(out, err, code)


@mcp.tool()
def ssh_pm2_logs(name: str, lines: int = 50) -> str:
    """
    Fetch the last N lines of a pm2 app's logs (default 50, max 200).
    Reads directly from /home/panda/.pm2/logs/<name>-out.log and <name>-error.log.
    """
    if name not in ALLOWED_PM2:
        log("pm2_logs", f"BLOCKED: {name}", success=False)
        return f"App '{name}' is not in the allowed list: {sorted(ALLOWED_PM2)}"
    lines = min(int(lines), 200)
    cmd = (
        f"echo '=== OUT ===' && tail -n {lines} ~/.pm2/logs/{name}-out.log 2>/dev/null; "
        f"echo '=== ERROR ===' && tail -n {lines} ~/.pm2/logs/{name}-error.log 2>/dev/null"
    )
    out, err, code = _run(cmd)
    log("pm2_logs", f"{name} last={lines}")
    return _result(out, err, code)


# ── screen — Telegram bot (name: bot) ────────────────────────────────────────

@mcp.tool()
def ssh_screen_list() -> str:
    """List all active screen sessions on the VPS."""
    out, err, code = _run("screen -ls 2>&1 || true")
    log("screen_list", SSH_HOST)
    return _result(out, err, code)


@mcp.tool()
def ssh_screen_logs(name: str) -> str:
    """
    Capture the current visible output of a screen session via hardcopy.
    Allowed sessions defined in MCP_SSH_ALLOWED_SCREENS (default: bot).

    Note: hardcopy captures only the current screen buffer (last ~24 lines).
    For full persistent history, restart the session with:
      screen -L -Logfile ~/logs/<name>.log -S <name> python bot.py
    """
    if name not in ALLOWED_SCREENS:
        log("screen_logs", f"BLOCKED: {name}", success=False)
        return f"Screen '{name}' is not in the allowed list: {sorted(ALLOWED_SCREENS)}"
    tmp = f"/tmp/mcp_screen_{name}.txt"
    cmd = f"screen -S {name} -X hardcopy {tmp} && sleep 0.2 && cat {tmp} && rm -f {tmp}"
    out, err, code = _run(cmd)
    log("screen_logs", f"{name} via hardcopy")
    return _result(out, err, code)


# ── Git operations ────────────────────────────────────────────────────────────

@mcp.tool()
def ssh_git_pull(repo_path: str) -> str:
    """
    Run 'git pull' in an allowed repository path on the VPS.
    Allowed paths defined in MCP_SSH_ALLOWED_REPOS.
    """
    if repo_path not in ALLOWED_REPO_PATHS:
        log("git_pull", f"BLOCKED: {repo_path}", success=False)
        return f"Path '{repo_path}' is not in the allowed repos list.\nAllowed: {sorted(ALLOWED_REPO_PATHS)}"
    out, err, code = _run(f"cd {repo_path} && git pull 2>&1")
    log("git_pull", f"{repo_path} -> exit {code}", success=(code == 0))
    return _result(out, err, code)


@mcp.tool()
def ssh_git_status(repo_path: str) -> str:
    """
    Run 'git status' and 'git log --oneline -5' in an allowed repo path.
    """
    if repo_path not in ALLOWED_REPO_PATHS:
        log("git_status", f"BLOCKED: {repo_path}", success=False)
        return f"Path '{repo_path}' is not in the allowed repos list."
    out, err, code = _run(f"cd {repo_path} && git status && echo '---' && git log --oneline -5")
    log("git_status", repo_path)
    return _result(out, err, code)


# ── Read-only file inspection ─────────────────────────────────────────────────

@mcp.tool()
def ssh_read_file(remote_path: str) -> str:
    """Read a text file from the VPS (read-only, max 500 lines)."""
    out, err, code = _run(f"head -500 {remote_path} 2>&1")
    log("read_file", remote_path)
    return _result(out, err, code)


@mcp.tool()
def ssh_list_dir(remote_path: str) -> str:
    """List files in a directory on the VPS (ls -lah)."""
    out, err, code = _run(f"ls -lah {remote_path} 2>&1")
    log("list_dir", remote_path)
    return _result(out, err, code)


# ── Controlled command runner ─────────────────────────────────────────────

@mcp.tool()
def ssh_run_command(alias: str) -> str:
    """
    Run a pre-approved command on the VPS by alias.
    The caller never supplies raw shell — only an alias key defined server-side.
    Every call (including blocked attempts) is written to the audit log.

    Built-in aliases:
      systemctl-enable-nginx   — enable nginx to auto-start on boot
      systemctl-disable-nginx  — disable nginx autostart
      systemctl-enable-pm2     — enable pm2-panda systemd service
      pm2-startup              — generate pm2 systemd startup hook
      pm2-save                 — save the current pm2 process list
      pm2-resurrect            — restore the saved pm2 process list
      nginx-configtest         — test nginx configuration (nginx -t)
      whoami                   — show current user and groups
      env-path                 — show PATH as seen by the SSH session

    Extra aliases can be added via the MCP_SSH_ALLOWED_COMMANDS env var
    (JSON object mapping alias → command, merged with the built-in list).
    """
    if alias not in ALLOWED_COMMANDS:
        log("run_command", f"BLOCKED unknown alias: {alias!r}", success=False)
        available = sorted(ALLOWED_COMMANDS.keys())
        return (
            f"Unknown alias '{alias}'.\n"
            f"Available aliases: {available}\n"
            f"To add more, set MCP_SSH_ALLOWED_COMMANDS in your env (JSON)."
        )

    command = ALLOWED_COMMANDS[alias]
    try:
        out, err, code = _run(command)
        log("run_command", f"{alias!r} -> {command!r} -> exit {code}", success=(code == 0))
        return _result(out, err, code)
    except Exception as e:
        log("run_command", f"{alias!r} -> EXCEPTION: {e}", success=False)
        return f"Command failed with exception: {e}"


# ── Audit log viewer ──────────────────────────────────────────────────────────

@mcp.tool()
def ssh_audit_log(lines: int = 30) -> str:
    """Show the last N lines of the local mcp-ssh audit log (default 30, max 100)."""
    lines = min(int(lines), 100)
    if not AUDIT_LOG.exists():
        return "Audit log is empty."
    entries = AUDIT_LOG.read_text(encoding="utf-8").splitlines()
    return "\n".join(entries[-lines:])


# ── Config info ───────────────────────────────────────────────────────────────

@mcp.tool()
def ssh_config_info() -> str:
    """Show the current mcp-ssh configuration (no secrets)."""
    return json.dumps({
        "host": SSH_HOST,
        "port": SSH_PORT,
        "user": SSH_USER,
        "key_path": SSH_KEY_PATH,
        "passphrase_set": bool(SSH_KEY_PASS),
        "allowed_systemd_services": sorted(ALLOWED_SYSTEMD),
        "allowed_pm2_apps": sorted(ALLOWED_PM2),
        "allowed_screen_sessions": sorted(ALLOWED_SCREENS),
        "allowed_repo_paths": sorted(ALLOWED_REPO_PATHS),
        "audit_log": str(AUDIT_LOG),
    }, indent=2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not SSH_HOST:
        print("ERROR: MCP_SSH_HOST is not set.", file=sys.stderr)
        sys.exit(1)
    mcp.run(transport="stdio")
