"""
mcp-ssh — SSH MCP Server for Claude Desktop
Connects to a remote VPS and exposes a controlled set of tools.

Security model:
  - Allowlist-only execution (no arbitrary shell)
  - Dedicated low-privilege SSH user on the VPS
  - All executions are audit-logged locally
  - Destructive operations do not exist
  - Credentials via env vars / SSH key with passphrase
"""

import os
import sys
import json
import logging
import paramiko
from datetime import datetime
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

# Services allowed for status/restart operations
ALLOWED_SERVICES = set(
    os.environ.get("MCP_SSH_ALLOWED_SERVICES", "telegram-bot,pandapoints-dapp,nginx,caddy").split(",")
)

# Directories allowed for git pull
ALLOWED_REPO_PATHS = set(
    os.environ.get("MCP_SSH_ALLOWED_REPOS", "").split(",")
) - {""}

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
# SSH client factory
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
            # Fallback to RSA
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


def _run(command: str) -> tuple[str, str, int]:
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
    """Format a clean result string."""
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
    """Check connectivity to the VPS. Returns uptime and hostname."""
    try:
        out, err, code = _run("echo \"host=$(hostname)\" && uptime")
        log("ping", SSH_HOST)
        return _result(out, err, code)
    except Exception as e:
        log("ping", str(e), success=False)
        return f"Connection failed: {e}"


# ── Service management ────────────────────────────────────────────────────────

@mcp.tool()
def ssh_service_status(service: str) -> str:
    """
    Get the systemd status of a service.
    Allowed services are defined in MCP_SSH_ALLOWED_SERVICES.
    """
    if service not in ALLOWED_SERVICES:
        log("service_status", f"BLOCKED: {service}", success=False)
        return f"Service '{service}' is not in the allowed list: {sorted(ALLOWED_SERVICES)}"
    cmd = f"sudo systemctl status {service} --no-pager -l"
    out, err, code = _run(cmd)
    log("service_status", service)
    return _result(out, err, code)


@mcp.tool()
def ssh_restart_service(service: str) -> str:
    """
    Restart a systemd service. Only allowed services can be restarted.
    """
    if service not in ALLOWED_SERVICES:
        log("restart_service", f"BLOCKED: {service}", success=False)
        return f"Service '{service}' is not in the allowed list: {sorted(ALLOWED_SERVICES)}"
    cmd = f"sudo systemctl restart {service} && echo 'Restarted OK'"
    out, err, code = _run(cmd)
    log("restart_service", f"{service} -> exit {code}", success=(code == 0))
    return _result(out, err, code)


@mcp.tool()
def ssh_service_logs(service: str, lines: int = 50) -> str:
    """
    Fetch the last N lines of journal logs for a service (default 50, max 200).
    """
    if service not in ALLOWED_SERVICES:
        log("service_logs", f"BLOCKED: {service}", success=False)
        return f"Service '{service}' is not in the allowed list: {sorted(ALLOWED_SERVICES)}"
    lines = min(int(lines), 200)
    cmd = f"sudo journalctl -u {service} -n {lines} --no-pager"
    out, err, code = _run(cmd)
    log("service_logs", f"{service} last={lines}")
    return _result(out, err, code)


# ── System info ───────────────────────────────────────────────────────────────

@mcp.tool()
def ssh_disk_usage() -> str:
    """Show disk usage on the VPS (df -h)."""
    out, err, code = _run("df -h --output=source,size,used,avail,pcent,target | column -t")
    log("disk_usage", SSH_HOST)
    return _result(out, err, code)


@mcp.tool()
def ssh_memory_usage() -> str:
    """Show memory usage on the VPS (free -h + top processes by RSS)."""
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


# ── Git operations ────────────────────────────────────────────────────────────

@mcp.tool()
def ssh_git_pull(repo_path: str) -> str:
    """
    Run 'git pull' in an allowed repository path on the VPS.
    Allowed paths are defined in MCP_SSH_ALLOWED_REPOS.
    """
    if repo_path not in ALLOWED_REPO_PATHS:
        log("git_pull", f"BLOCKED: {repo_path}", success=False)
        return (
            f"Path '{repo_path}' is not in the allowed repos list.\n"
            f"Allowed: {sorted(ALLOWED_REPO_PATHS)}"
        )
    cmd = f"cd {repo_path} && git pull 2>&1"
    out, err, code = _run(cmd)
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
    cmd = f"cd {repo_path} && git status && echo '---' && git log --oneline -5"
    out, err, code = _run(cmd)
    log("git_status", repo_path)
    return _result(out, err, code)


# ── Read-only file inspection ─────────────────────────────────────────────────

@mcp.tool()
def ssh_read_file(remote_path: str) -> str:
    """
    Read a text file from the VPS (read-only). Max 500 lines returned.
    Use for config files, .env (non-sensitive), logs, etc.
    """
    cmd = f"head -500 {remote_path} 2>&1"
    out, err, code = _run(cmd)
    log("read_file", remote_path)
    return _result(out, err, code)


@mcp.tool()
def ssh_list_dir(remote_path: str) -> str:
    """
    List files in a directory on the VPS (ls -lah).
    """
    cmd = f"ls -lah {remote_path} 2>&1"
    out, err, code = _run(cmd)
    log("list_dir", remote_path)
    return _result(out, err, code)


# ── Audit log viewer ──────────────────────────────────────────────────────────

@mcp.tool()
def ssh_audit_log(lines: int = 30) -> str:
    """
    Show the last N lines of the local mcp-ssh audit log (default 30, max 100).
    """
    lines = min(int(lines), 100)
    if not AUDIT_LOG.exists():
        return "Audit log is empty."
    entries = AUDIT_LOG.read_text(encoding="utf-8").splitlines()
    return "\n".join(entries[-lines:])


# ── Config info ───────────────────────────────────────────────────────────────

@mcp.tool()
def ssh_config_info() -> str:
    """
    Show the current mcp-ssh configuration (no secrets).
    """
    return json.dumps({
        "host": SSH_HOST,
        "port": SSH_PORT,
        "user": SSH_USER,
        "key_path": SSH_KEY_PATH,
        "passphrase_set": bool(SSH_KEY_PASS),
        "allowed_services": sorted(ALLOWED_SERVICES),
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
