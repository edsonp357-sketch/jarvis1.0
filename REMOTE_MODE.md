# JARVIS Remote Mode

## Visão Geral

O JARVIS pode rodar em modo remoto, onde:
- **VPS (52.15.103.205)**: Serve o dashboard e relay de comandos
- **PC Local**: Roda o JARVIS Core (Gemini Live, microfone, tela, apps)
- **Celular**: Acessa o dashboard de qualquer lugar

```
┌─────────────────┐     WebSocket      ┌──────────────────┐
│   PC Local      │ ◄────────────────► │   VPS AWS        │
│   (JARVIS Core) │                     │   (Dashboard)    │
└─────────────────┘                     └──────────────────┘
                                              ▲
                                              │
                                        ┌─────┴─────┐
                                        │  Celular  │
                                        └───────────┘
```

## Configuração do VPS

### 1. Transferir arquivos para o VPS

```bash
# Do seu PC local:
scp dashboard/vps_server.py root@52.15.103.205:/opt/jarvis/
scp -r dashboard/static/ root@52.15.103.205:/opt/jarvis/static/
```

### 2. Instalar dependências no VPS

```bash
ssh root@52.15.103.205
pip install fastapi "uvicorn[standard]" cryptography websockets
```

### 3. Iniciar o servidor

```bash
cd /opt/jarvis
python vps_server.py
```

Ou use o script de setup:
```bash
bash setup_vps.sh
```

## Configuração do PC Local

### 1. Instalar dependência

```bash
pip install websockets
```

### 2. Iniciar em modo remoto

```bash
python main.py --remote
```

### 3. Criar atalho para auto-start

Crie um atalho com:
```
python C:\Users\edson\Mark-XLVIII\main.py --remote
```

## Acesso

- **Dashboard**: http://52.15.103.205:8000
- **Celular**: Acesse o IP acima em qualquer navegador
- **QR Code**: Use o botão "Controle Remoto" na interface JARVIS

## Portas

| Porta | Uso |
|-------|-----|
| 8000 | Dashboard (HTTP) |
| 8001 | Worker WebSocket (PC ↔ VPS) |

## Solução de Problemas

### VPS não recebe conexão
```bash
# Verificar se as portas estão abertas
sudo ufw allow 8000/tcp
sudo ufw allow 8001/tcp
```

### PC não conecta ao VPS
```bash
# Testar conexão
python -c "import websockets; import asyncio; asyncio.run(websockets.connect('ws://52.15.103.205:8001/ws/worker'))"
```

### Ver logs no VPS
```bash
journalctl -u jarvis -f
```

## Arquitetura

1. **Celular** envia comando → **VPS** recebe
2. **VPS** encaminha via WebSocket → **PC** recebe
3. **PC** envia para Gemini → Processa comando
4. **PC** envia resposta → **VPS** encaminha
5. **VPS** mostra no dashboard → **Celular** vê resultado
