"""
dashboard/worker.py — JARVIS PC Worker

Runs on PC, connects to VPS dashboard via WebSocket.
Relays commands between VPS (phone/browser) and local JARVIS.

Usage:
  python worker.py

Requires: pip install websockets
"""

import asyncio
import json
import sys
import time
import traceback
from pathlib import Path

try:
    import websockets
except ImportError:
    print("[Worker] Instale: pip install websockets")
    exit(1)

# ── Config ──────────────────────────────────────────────────────────────────
VPS_URL = "wss://jarvis1-0-j5if.onrender.com/ws/worker"
RECONNECT_DELAY = 5
MAX_RECONNECT = 60


class JARVISWorker:
    def __init__(self):
        self._ws = None
        self._connected = False
        self._jarvis_queue: asyncio.Queue = asyncio.Queue()
        self._pending_commands: list[dict] = []

    async def connect(self):
        """Connect to VPS and handle messages."""
        delay = RECONNECT_DELAY
        while True:
            try:
                print(f"[Worker] Conectando ao VPS...")
                async with websockets.connect(VPS_URL, ping_interval=20, ping_timeout=10) as ws:
                    self._ws = ws
                    self._connected = True
                    delay = RECONNECT_DELAY
                    print("[Worker] ✅ Conectado ao VPS!")

                    async for message in ws:
                        try:
                            data = json.loads(message)
                            await self._handle_message(data)
                        except json.JSONDecodeError:
                            pass

            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                self._connected = False
                self._ws = None
                print(f"[Worker] ❌ Desconectado: {e}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAX_RECONNECT)
            except Exception as e:
                self._connected = False
                self._ws = None
                print(f"[Worker] ❌ Erro: {e}")
                traceback.print_exc()
                await asyncio.sleep(delay)

    async def _handle_message(self, data: dict):
        """Handle messages from VPS."""
        msg_type = data.get("type")

        if msg_type == "command":
            # Command from phone/browser → forward to JARVIS
            text = data.get("text", "")
            print(f"[Worker] 📥 Comando recebido: {text}")
            await self._send_to_jarvis(text)

        elif msg_type == "wake":
            # Wake signal from phone
            print("[Worker] 🔔 Sinal de wake recebido")
            await self._send_to_jarvis("[WAKE]")

        elif msg_type == "phone_connected":
            print("[Worker] 📱 Celular conectado")

        elif msg_type == "file_received":
            # File uploaded from phone → notify JARVIS
            name = data.get("name", "")
            print(f"[Worker] 📁 Arquivo recebido: {name}")
            await self._send_to_jarvis(f"[FILE_RECEIVED] {name}")

    async def _send_to_jarvis(self, text: str):
        """Send command to local JARVIS via stdin or queue."""
        # Put in queue for main.py to pick up
        await self._jarvis_queue.put(text)

    async def send_log(self, speaker: str, text: str):
        """Send log to VPS for display on dashboard."""
        if self._ws and self._connected:
            try:
                await self._ws.send(json.dumps({
                    "type": "log",
                    "speaker": speaker,
                    "text": text,
                    "ts": ""
                }))
            except Exception:
                pass

    async def send_status(self, state: str):
        """Send status to VPS."""
        if self._ws and self._connected:
            try:
                await self._ws.send(json.dumps({
                    "type": "status",
                    "state": state
                }))
            except Exception:
                pass


# Global worker instance
_worker: JARVISWorker | None = None


def get_worker() -> JARVISWorker:
    global _worker
    if _worker is None:
        _worker = JARVISWorker()
    return _worker


async def main():
    worker = get_worker()
    print("[Worker] Iniciando worker JARVIS...")
    print(f"[Worker] VPS: {VPS_URL}")
    await worker.connect()


if __name__ == "__main__":
    asyncio.run(main())
