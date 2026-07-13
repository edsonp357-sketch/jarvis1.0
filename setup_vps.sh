#!/bin/bash
# setup_vps.sh — Script de configuração para VPS AWS
# Execute no VPS: bash setup_vps.sh

echo "=== JARVIS VPS Setup ==="

# Instalar dependências
echo "[1/4] Instalando dependências..."
pip install fastapi "uvicorn[standard]" cryptography websockets

# Criar diretório
echo "[2/4] Criando diretório..."
mkdir -p /opt/jarvis
cd /opt/jarvis

# Copiar arquivos (você precisa transferir os arquivos primeiro)
echo "[3/4] Verificando arquivos..."
if [ ! -f "vps_server.py" ]; then
    echo "❌ Copie os arquivos para /opt/jarvis/ primeiro:"
    echo "   scp -r dashboard/vps_server.py dashboard/static/ root@52.15.103.205:/opt/jarvis/"
    exit 1
fi

# Criar serviço systemd
echo "[4/4] Criando serviço..."
cat > /etc/systemd/system/jarvis.service << 'EOF'
[Unit]
Description=JARVIS Dashboard Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/jarvis
ExecStart=/usr/bin/python3 vps_server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable jarvis
systemctl start jarvis

echo ""
echo "✅ JARVIS Dashboard rodando!"
echo "   Dashboard: http://52.15.103.205:8000"
echo "   Worker: ws://52.15.103.205:8001/ws/worker"
echo ""
echo "Para verificar status: systemctl status jarvis"
echo "Para ver logs: journalctl -u jarvis -f"
