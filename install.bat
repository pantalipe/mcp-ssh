@echo off
REM =============================================================================
REM install.bat — mcp-ssh installer for Windows (Claude Desktop)
REM Run this once after cloning the repo.
REM =============================================================================

echo.
echo [mcp-ssh] Instalando dependencias...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERRO: pip install falhou.
    pause
    exit /b 1
)

echo.
echo [mcp-ssh] Gerando chave SSH dedicada...
echo.
echo Isso criara uma chave Ed25519 em C:\Users\%USERNAME%\.ssh\mcp_ssh_ed25519
echo Defina uma passphrase quando solicitado (recomendado).
echo.
ssh-keygen -t ed25519 -f "%USERPROFILE%\.ssh\mcp_ssh_ed25519" -C "mcp-ssh-claude-agent"

echo.
echo [mcp-ssh] Chave gerada. Sua chave PUBLICA para o VPS:
echo.
type "%USERPROFILE%\.ssh\mcp_ssh_ed25519.pub"

echo.
echo ===========================================================================
echo PROXIMOS PASSOS:
echo.
echo 1. Copie a chave publica acima e cole em:
echo    /home/claude-agent/.ssh/authorized_keys  (no seu VPS)
echo.
echo 2. No VPS, execute como root:
echo    bash setup_vps.sh
echo.
echo 3. Copie .env.example para .env e preencha os valores:
echo    copy .env.example .env
echo.
echo 4. Adicione o bloco abaixo no seu claude_desktop_config.json:
echo.
echo    "mcp-ssh": {
echo      "command": "python",
echo      "args": ["C:\\Users\\%USERNAME%\\mcp-ssh\\server.py"],
echo      "env": {
echo        "MCP_SSH_HOST": "seu.vps.ip",
echo        "MCP_SSH_PORT": "22",
echo        "MCP_SSH_USER": "claude-agent",
echo        "MCP_SSH_KEY_PATH": "C:\\Users\\%USERNAME%\\.ssh\\mcp_ssh_ed25519",
echo        "MCP_SSH_KEY_PASSPHRASE": "sua-passphrase-aqui",
echo        "MCP_SSH_ALLOWED_SERVICES": "telegram-bot,pandapoints-dapp,nginx",
echo        "MCP_SSH_ALLOWED_REPOS": "/home/claude-agent/pandapoints-dapp,/home/claude-agent/telegram-bot"
echo      }
echo    }
echo.
echo 5. Reinicie o Claude Desktop.
echo ===========================================================================
echo.
pause
