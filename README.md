# mcp-ssh

MCP server para Claude Desktop que permite gerenciar um VPS remoto via SSH com segurança.

## Modelo de segurança

| Camada | Controle |
|---|---|
| VPS | Usuário dedicado `claude-agent` com sudo restrito a serviços específicos |
| SSH | Chave Ed25519 dedicada com passphrase, separada da chave pessoal |
| MCP | Allowlist de serviços e repos — sem execução arbitrária |
| Audit | Todo comando executado é logado em `~/.mcp-ssh/audit.log` |
| Transporte | stdio (sem porta exposta na rede local) |

## Ferramentas disponíveis

| Ferramenta | Descrição |
|---|---|
| `ssh_ping` | Testa conectividade — retorna hostname e uptime |
| `ssh_service_status` | Status systemctl de um serviço permitido |
| `ssh_restart_service` | Reinicia um serviço permitido |
| `ssh_service_logs` | Últimas N linhas do journal de um serviço |
| `ssh_disk_usage` | Uso de disco (df -h) |
| `ssh_memory_usage` | Uso de memória + top processos |
| `ssh_uptime` | Uptime e load average |
| `ssh_git_pull` | git pull em um repo permitido |
| `ssh_git_status` | git status + últimos 5 commits de um repo |
| `ssh_read_file` | Lê um arquivo remoto (máx 500 linhas) |
| `ssh_list_dir` | Lista arquivos em um diretório (ls -lah) |
| `ssh_audit_log` | Exibe o log de auditoria local |
| `ssh_config_info` | Mostra a config atual (sem secrets) |

## Instalação

### 1. VPS — criar usuário dedicado

```bash
# No VPS como root:
sudo bash setup_vps.sh
```

Edite `setup_vps.sh` para incluir seus serviços antes de rodar.

### 2. Windows — instalar e gerar chave SSH

```bat
install.bat
```

O script instala as dependências e gera a chave `mcp_ssh_ed25519`.

### 3. VPS — autorizar a chave pública

```bash
echo "sua-chave-publica" >> /home/claude-agent/.ssh/authorized_keys
```

### 4. Testar a conexão manualmente

```bat
ssh -i C:\Users\panta\.ssh\mcp_ssh_ed25519 claude-agent@seu.vps.ip
```

### 5. claude_desktop_config.json

Adicione em `mcpServers`:

```json
"mcp-ssh": {
  "command": "python",
  "args": ["C:\\Users\\panta\\mcp-ssh\\server.py"],
  "env": {
    "MCP_SSH_HOST": "seu.vps.ip",
    "MCP_SSH_PORT": "22",
    "MCP_SSH_USER": "claude-agent",
    "MCP_SSH_KEY_PATH": "C:\\Users\\panta\\.ssh\\mcp_ssh_ed25519",
    "MCP_SSH_KEY_PASSPHRASE": "sua-passphrase",
    "MCP_SSH_ALLOWED_SERVICES": "telegram-bot,pandapoints-dapp,nginx",
    "MCP_SSH_ALLOWED_REPOS": "/home/claude-agent/pandapoints-dapp,/home/claude-agent/telegram-bot"
  }
}
```

### 6. Reiniciar o Claude Desktop

---

## Adicionando novos serviços

1. Edite `setup_vps.sh`, adicione o serviço ao array `SERVICES`, re-execute no VPS.
2. Atualize `MCP_SSH_ALLOWED_SERVICES` no `claude_desktop_config.json`.
3. Reinicie o Claude Desktop.

## Audit log

O log local fica em `%USERPROFILE%\.mcp-ssh\audit.log`. Exemplo:

```
2026-05-16T14:23:01 | INFO | OK | service_logs | telegram-bot last=50
2026-05-16T14:25:10 | INFO | OK | restart_service | pandapoints-dapp -> exit 0
2026-05-16T14:30:44 | INFO | FAIL | restart_service | BLOCKED: mysql
```
