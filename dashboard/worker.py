"""
dashboard/worker.py â€” JARVIS PC Worker

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

# â”€â”€ Config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
                    print("[Worker] Conectado ao VPS!")

                    async for message in ws:
                        try:
                            data = json.loads(message)
                            await self._handle_message(data)
                        except json.JSONDecodeError:
                            pass

            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                self._connected = False
                self._ws = None
                print(f"[Worker] Desconectado: {e}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAX_RECONNECT)
            except Exception as e:
                self._connected = False
                self._ws = None
                print(f"[Worker] Erro: {e}")
                traceback.print_exc()
                await asyncio.sleep(delay)

    async def _handle_message(self, data: dict):
        """Handle messages from VPS."""
        msg_type = data.get("type")

        if msg_type == "command":
            # Command from phone/browser â†’ forward to JARVIS
            text = data.get("text", "")
            print(f"[Worker] Comando recebido: {text}")
            await self._send_to_jarvis(text)

        elif msg_type == "wake":
            # Wake signal from phone
            print("[Worker] Sinal de wake recebido")
            await self._send_to_jarvis("[WAKE]")

        elif msg_type == "phone_connected":
            print("[Worker] Celular conectado")

        elif msg_type == "file_received":
            # File uploaded from phone â†’ notify JARVIS
            name = data.get("name", "")
            print(f"[Worker] Arquivo recebido: {name}")
            await self._send_to_jarvis(f"[FILE_RECEIVED] {name}")

        elif msg_type == "get_metrics":
            # VPS requesting system metrics
            print("[Worker] ðŸ“Š SolicitaÃ§Ã£o de mÃ©tricas recebida")
            await self._send_metrics()

        elif msg_type == "control":
            # Remote control action from phone
            action = data.get("action", "")
            value = data.get("value", "")
            print(f"[Worker] Controle remoto: {action} {value}")
            await self._send_to_jarvis(f"[SYSTEM_ACTION] {action} {value}".strip())

        elif msg_type == "phone_camera":
            # Camera image from phone for analysis
            image = data.get("image", "")
            mime_type = data.get("mime_type", "image/jpeg")
            print("[Worker] Imagem da camera recebida")
            await self._send_to_jarvis(f"[PHONE_CAMERA] data:{mime_type};base64,{image}")

        elif msg_type == "get_screen":
            # VPS requesting screen capture
            print("[Worker] Solicitacao de captura de tela")
            await self._send_screen_capture()

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

    async def _send_metrics(self):
        """Send system metrics to VPS."""
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.2)
            ram = psutil.virtual_memory()
            boot_time = psutil.boot_time()
            uptime_secs = time.time() - boot_time
            uptime_h = int(uptime_secs // 3600)
            uptime_m = int((uptime_secs % 3600) // 60)

            # Try to get GPU
            gpu_percent = None
            try:
                import ctypes
                class _Util(ctypes.Structure):
                    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]
                lib = ctypes.WinDLL("nvml")
                lib.nvmlInit_v2()
                dev = ctypes.c_void_p()
                lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
                u = _Util()
                lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(u))
                gpu_percent = float(u.gpu)
            except Exception:
                pass

            # Try to get CPU temp
            cpu_temp = None
            try:
                import wmi
                w = wmi.WMI(namespace="root/wmi")
                tz = w.MSAcpi_ThermalZoneTemperature()
                if tz:
                    cpu_temp = round((tz[0].CurrentTemperature / 10.0) - 273.15, 1)
            except Exception:
                pass

            metrics = {
                "type": "metrics",
                "cpu_percent": round(cpu, 1),
                "ram_percent": round(ram.percent, 1),
                "ram_used_gb": round(ram.used / 1024 ** 3, 1),
                "ram_total_gb": round(ram.total / 1024 ** 3, 1),
                "cpu_temp_c": cpu_temp if cpu_temp and cpu_temp > 0 else None,
                "gpu_percent": gpu_percent,
                "uptime": f"{uptime_h}h {uptime_m}m",
                "process_count": len(psutil.pids()),
            }

            if self._ws and self._connected:
                await self._ws.send(json.dumps(metrics))
                print(f"[Worker] ðŸ“Š MÃ©tricas enviadas: CPU {metrics['cpu_percent']}% RAM {metrics['ram_percent']}%")
        except Exception as e:
            print(f"[Worker] Erro ao enviar metricas: {e}")

    async def _send_screen_capture(self):
        """Send screen capture to VPS."""
        try:
            import base64
            import io
            from PIL import Image
            import mss

            with mss.mss() as sct:
                monitor = sct.monitors[1]
                screenshot = sct.grab(monitor)
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=70)
                b64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')

                if self._ws and self._connected:
                    await self._ws.send(json.dumps({
                        "type": "screen_data",
                        "image": f"data:image/jpeg;base64,{b64_image}",
                        "width": img.width,
                        "height": img.height
                    }))
                    print("[Worker] Captura de tela enviada")
        except Exception as e:
            print(f"[Worker] Erro ao capturar tela: {e}")


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

