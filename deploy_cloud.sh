#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
# deploy_cloud.sh — Deploy JARVIS Cloud to VPS
#
# Run from your PC:
#   bash deploy_cloud.sh
#
# What it does:
#   1. Copies all necessary files to VPS via SCP
#   2. Installs Python dependencies
#   3. Configures systemd service for 24/7 operation
#   4. Starts JARVIS Cloud
# ═══════════════════════════════════════════════════════════════════

set -e

# ── CONFIG (edit these) ──────────────────────────────────────────
VPS_IP="52.15.103.205"
VPS_USER="root"
VPS_DIR="/opt/jarvis"
SSH_KEY=""  # Optional: path to SSH key, e.g. ~/.ssh/my_key.pem
# ─────────────────────────────────────────────────────────────────

# Build SSH/SCP options
SSH_OPTS=""
if [ -n "$SSH_KEY" ]; then
    SSH_OPTS="-i $SSH_KEY"
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "═══════════════════════════════════════════════"
echo "   JARVIS Cloud Deploy"
echo "   VPS: $VPS_USER@$VPS_IP"
echo "   Dir: $VPS_DIR"
echo "═══════════════════════════════════════════════"
echo ""

# ── Step 1: Create directory on VPS ──────────────────────────────
echo "[1/5] 📁 Criando diretório no VPS..."
ssh $SSH_OPTS $VPS_USER@$VPS_IP "mkdir -p $VPS_DIR/config $VPS_DIR/core $VPS_DIR/memory $VPS_DIR/actions $VPS_DIR/dashboard/static"

# ── Step 2: Copy files ───────────────────────────────────────────
echo "[2/5] 📤 Copiando arquivos para o VPS..."

# Core files
scp $SSH_OPTS "$SCRIPT_DIR/jarvis_cloud.py" $VPS_USER@$VPS_IP:$VPS_DIR/

# Dashboard
scp $SSH_OPTS "$SCRIPT_DIR/dashboard/vps_server.py" $VPS_USER@$VPS_IP:$VPS_DIR/dashboard/
scp $SSH_OPTS "$SCRIPT_DIR/dashboard/__init__.py" $VPS_USER@$VPS_IP:$VPS_DIR/dashboard/
scp $SSH_OPTS -r "$SCRIPT_DIR/dashboard/static/" $VPS_USER@$VPS_IP:$VPS_DIR/dashboard/

# Config
scp $SSH_OPTS "$SCRIPT_DIR/config/api_keys.json" $VPS_USER@$VPS_IP:$VPS_DIR/config/
scp $SSH_OPTS "$SCRIPT_DIR/config/__init__.py" $VPS_USER@$VPS_IP:$VPS_DIR/config/

# Core (prompt)
scp $SSH_OPTS "$SCRIPT_DIR/core/prompt.txt" $VPS_USER@$VPS_IP:$VPS_DIR/core/

# Memory
scp $SSH_OPTS "$SCRIPT_DIR/memory/memory_manager.py" $VPS_USER@$VPS_IP:$VPS_DIR/memory/
if [ -f "$SCRIPT_DIR/memory/long_term.json" ]; then
    scp $SSH_OPTS "$SCRIPT_DIR/memory/long_term.json" $VPS_USER@$VPS_IP:$VPS_DIR/memory/
fi
# Ensure memory __init__.py exists
ssh $SSH_OPTS $VPS_USER@$VPS_IP "touch $VPS_DIR/memory/__init__.py"

# Actions (cloud-compatible only)
scp $SSH_OPTS "$SCRIPT_DIR/actions/web_search.py" $VPS_USER@$VPS_IP:$VPS_DIR/actions/
scp $SSH_OPTS "$SCRIPT_DIR/actions/proactive.py" $VPS_USER@$VPS_IP:$VPS_DIR/actions/
# Ensure actions __init__.py exists
ssh $SSH_OPTS $VPS_USER@$VPS_IP "touch $VPS_DIR/actions/__init__.py"

# Systemd service
scp $SSH_OPTS "$SCRIPT_DIR/jarvis_cloud.service" $VPS_USER@$VPS_IP:/etc/systemd/system/jarvis-cloud.service

echo "   ✅ Arquivos copiados!"

# ── Step 3: Install dependencies ─────────────────────────────────
echo "[3/5] 📦 Instalando dependências no VPS..."
ssh $SSH_OPTS $VPS_USER@$VPS_IP << 'REMOTE_SCRIPT'
pip install --quiet \
    fastapi \
    "uvicorn[standard]" \
    cryptography \
    google-genai \
    google-generativeai \
    duckduckgo-search \
    requests \
    2>&1 | tail -5
REMOTE_SCRIPT
echo "   ✅ Dependências instaladas!"

# ── Step 4: Configure systemd ────────────────────────────────────
echo "[4/5] ⚙️  Configurando serviço systemd..."
ssh $SSH_OPTS $VPS_USER@$VPS_IP << REMOTE_SCRIPT
# Update WorkingDirectory in service to point to dashboard/
sed -i 's|WorkingDirectory=.*|WorkingDirectory=$VPS_DIR/dashboard|' /etc/systemd/system/jarvis-cloud.service
sed -i 's|ExecStart=.*|ExecStart=/usr/bin/python3 $VPS_DIR/dashboard/vps_server.py|' /etc/systemd/system/jarvis-cloud.service

systemctl daemon-reload
systemctl enable jarvis-cloud
systemctl restart jarvis-cloud
REMOTE_SCRIPT
echo "   ✅ Serviço configurado e iniciado!"

# ── Step 5: Verify ───────────────────────────────────────────────
echo "[5/5] 🔍 Verificando..."
sleep 3
ssh $SSH_OPTS $VPS_USER@$VPS_IP "systemctl status jarvis-cloud --no-pager -l | head -20"

echo ""
echo "═══════════════════════════════════════════════"
echo "   ✅ JARVIS Cloud DEPLOYED!"
echo ""
echo "   Dashboard: http://$VPS_IP:8888"
echo "   Worker:    ws://$VPS_IP:8889/ws/worker"
echo ""
echo "   Comandos úteis:"
echo "     Ver logs:    ssh $VPS_USER@$VPS_IP journalctl -u jarvis-cloud -f"
echo "     Reiniciar:   ssh $VPS_USER@$VPS_IP systemctl restart jarvis-cloud"
echo "     Status:      ssh $VPS_USER@$VPS_IP systemctl status jarvis-cloud"
echo "     Parar:       ssh $VPS_USER@$VPS_IP systemctl stop jarvis-cloud"
echo "═══════════════════════════════════════════════"
echo ""
