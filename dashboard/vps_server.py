"""
dashboard/vps_server.py — JARVIS VPS Relay Server + Cloud Core

Runs on VPS (24/7). Serves dashboard, relays commands to PC worker.
When PC worker is NOT connected, uses JarvisCloud for text-based responses.

Modes:
  - PC Mode (🖥️): Worker connected → commands forwarded to PC
  - Cloud Mode (⛅): No worker → commands processed by JarvisCloud locally

Usage on VPS:
  pip install fastapi "uvicorn[standard]" cryptography google-genai duckduckgo-search
  python vps_server.py
"""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
    import uvicorn
except ImportError:
    print("[VPS] Instale as dependências: pip install fastapi 'uvicorn[standard]' cryptography")
    exit(1)

try:
    from fastapi import UploadFile, File as FastAPIFile
    _UPLOAD_OK = True
except Exception:
    _UPLOAD_OK = False

# Add parent to path so we can import jarvis_cloud
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from jarvis_cloud import JarvisCloud
    _CLOUD_OK = True
    print("[VPS] ☁️  JarvisCloud module loaded — cloud mode available")
except ImportError as e:
    _CLOUD_OK = False
    print(f"[VPS] ⚠️  JarvisCloud not available: {e}")
    print("[VPS]     Install: pip install google-genai duckduckgo-search")

# ── Config ──────────────────────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 8888))
WORKER_PORT = int(os.environ.get("WORKER_PORT", 8889))
IS_CLOUD_DEPLOY = bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RENDER") or os.environ.get("CLOUD_DEPLOY"))
STATIC_DIR = Path(__file__).parent / "static"
AES_SALT = b'JARVIS-DASHBOARD-v1'
MAX_UPLOAD_MB = 500
UPLOADS_DIR = Path.home() / "JARVIS Uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _derive_key(session_key: str) -> bytes:
    return hashlib.sha256(session_key.encode('utf-8') + AES_SALT).digest()


def _decrypt_cbc(aes_key: bytes, enc_b64: str) -> str:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_pad
    raw = base64.b64decode(enc_b64)
    iv, ct = raw[:16], raw[16:]
    dec = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    padded = dec.update(ct) + dec.finalize()
    unpadder = sym_pad.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode('utf-8')


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


# ── VPS Dashboard Server ───────────────────────────────────────────────────

class VPSDashboard:

    def __init__(self):
        self._tokens: dict[str, str] = {}
        self._token_keys: dict[str, str] = {}
        self._aes_cache: dict[str, bytes] = {}
        self._pending_keys: dict[str, float] = {}
        self._device_sessions: dict[str, dict] = {}
        self._browser_clients: set[WebSocket] = set()
        self._worker: WebSocket | None = None
        self._command_queue: asyncio.Queue = asyncio.Queue()
        self._phone_audio_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._history: list[dict] = []
        self._login_html = _read("login.html")
        self._app_html = _read("app.html")
        self.app = self._build_app()
        self.worker_app = self._build_worker_app()

        # ── Cloud Core ──────────────────────────────────────────────────
        self._cloud: JarvisCloud | None = None
        self._cloud_task: asyncio.Task | None = None
        if _CLOUD_OK:
            self._cloud = JarvisCloud()
            self._cloud._on_response = self._on_cloud_proactive
            self._cloud._on_log = self._on_cloud_log
            self._cloud.start()
            print("[VPS] ☁️  Cloud mode ACTIVE — JARVIS runs 24/7")

    @property
    def mode(self) -> str:
        """Current operating mode."""
        return "pc" if self._worker else "cloud"

    @property
    def mode_label(self) -> str:
        return "🖥️ PC Mode" if self._worker else "⛅ Cloud Mode"

    async def _on_cloud_proactive(self, text: str):
        """Called when cloud core generates a proactive message."""
        await self.broadcast_to_browsers({
            "type": "log",
            "speaker": "jarvis",
            "text": text,
            "ts": "",
            "cloud": True,
        })

    async def _on_cloud_log(self, text: str):
        """Called for cloud core log messages."""
        print(f"[Cloud] {text}")

    async def _process_cloud_command(self, text: str) -> None:
        """Process command via cloud core and broadcast response."""
        if not self._cloud:
            await self.broadcast_to_browsers({
                "type": "log",
                "speaker": "jarvis",
                "text": "⚠️ Cloud mode is not available. Connect your PC with: python main.py --remote",
                "ts": "",
            })
            return

        # Show thinking indicator
        await self.broadcast_to_browsers({
            "type": "status",
            "state": "thinking",
        })

        try:
            response = await self._cloud.process_command(text)
            await self.broadcast_to_browsers({
                "type": "log",
                "speaker": "jarvis",
                "text": response,
                "ts": "",
                "cloud": True,
            })
        except Exception as e:
            await self.broadcast_to_browsers({
                "type": "log",
                "speaker": "jarvis",
                "text": f"Error: {str(e)[:200]}",
                "ts": "",
            })
        finally:
            state = "active" if self._worker else "cloud_idle"
            await self.broadcast_to_browsers({
                "type": "status",
                "state": state,
            })

    async def _start_cloud_proactive_loop(self):
        """Start the proactive check-in loop for cloud mode."""
        if not self._cloud:
            return
        while True:
            await asyncio.sleep(60)
            # Only run proactive in cloud mode (no PC connected)
            if self._worker is not None:
                continue
            msg = await self._cloud.check_proactive()
            if msg:
                await self._on_cloud_proactive(msg)

    def new_key(self, expiry_secs: int = 600) -> str:
        now = time.time()
        self._pending_keys = {k: v for k, v in self._pending_keys.items() if v > now}
        key = ''.join(secrets.choice('ABCDEFGHJKMNPQRSTUVWXYZ23456789') for _ in range(6))
        self._pending_keys[key] = now + expiry_secs
        return key

    def _aes_key(self, session_key: str) -> bytes:
        if session_key not in self._aes_cache:
            self._aes_cache[session_key] = _derive_key(session_key)
        return self._aes_cache[session_key]

    def _decrypt(self, token: str, enc_b64: str) -> str | None:
        sk = self._token_keys.get(token)
        if not sk:
            return None
        try:
            return _decrypt_cbc(self._aes_key(sk), enc_b64)
        except Exception:
            return None

    async def broadcast_to_browsers(self, msg: dict) -> None:
        self._history.append(msg)
        if len(self._history) > 300:
            self._history = self._history[-300:]
        dead: set[WebSocket] = set()
        for ws in list(self._browser_clients):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        self._browser_clients -= dead

    async def send_to_worker(self, msg: dict) -> None:
        if self._worker:
            try:
                await self._worker.send_json(msg)
            except Exception:
                self._worker = None

    # ── Browser Dashboard App ─────────────────────────────────────────────

    def _build_app(self) -> FastAPI:
        app = FastAPI(docs_url=None, redoc_url=None)

        def _auth(req: Request) -> bool:
            return True

        @app.get("/static/crypto.js")
        async def serve_crypto():
            crypto_file = STATIC_DIR / "crypto-js.min.js"
            if crypto_file.exists():
                return FileResponse(str(crypto_file), media_type="application/javascript")
            from fastapi.responses import RedirectResponse
            return RedirectResponse("https://cdnjs.cloudflare.com/ajax/libs/crypto-js/4.2.0/crypto-js.min.js")

        @app.get("/login", response_class=HTMLResponse)
        async def login_page():
            return HTMLResponse(self._login_html)

        @app.get("/", response_class=HTMLResponse)
        async def index(req: Request):
            # Auto-detect host from request
            host = req.headers.get("host", "localhost")
            # For cloud deploys, don't show port (reverse proxy handles it)
            display_host = host if IS_CLOUD_DEPLOY else f"{host.split(':')[0]}:{PORT}"
            html = (self._app_html
                    .replace("__IP__", display_host.split(':')[0])
                    .replace("__PORT__", host.split(':')[-1] if ':' in host else str(PORT)))
            return HTMLResponse(html)

        @app.post("/login")
        async def login(req: Request):
            body = await req.json()
            entered = str(body.get("pin", "")).strip().upper()
            now = time.time()
            if entered in self._pending_keys and self._pending_keys[entered] > now:
                del self._pending_keys[entered]
                tok = secrets.token_urlsafe(32)
                self._tokens[tok] = entered
                self._token_keys[tok] = entered
                self._aes_key(entered)
                asyncio.create_task(self.broadcast_to_browsers(
                    {"type": "sys", "text": "Conexão remota estabelecida."}
                ))
                # Notify worker
                await self.send_to_worker({"type": "phone_connected"})
                return JSONResponse({"ok": True, "token": tok})
            return JSONResponse({"ok": False, "error": "Chave inválida ou expirada"}, status_code=401)

        @app.get("/auto-login")
        async def auto_login(key: str = ""):
            now = time.time()
            if not key or key not in self._pending_keys or self._pending_keys[key] <= now:
                return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
  h2{color:#f87171;margin-bottom:12px}p{color:#5e6a7e;font-size:14px}
</style></head>
<body><div><h2>Link Expirado</h2>
<p>Pressione <strong style="color:#dde3ed">Controle Remoto</strong> no JARVIS para obter um novo QR code.</p>
</div></body></html>""")

            del self._pending_keys[key]
            tok = secrets.token_urlsafe(32)
            dev_tok = secrets.token_urlsafe(32)
            self._tokens[tok] = key
            self._token_keys[tok] = key
            self._aes_key(key)
            self._device_sessions[dev_tok] = {"session_key": key}

            asyncio.create_task(self.broadcast_to_browsers(
                {"type": "sys", "text": "Conexão remota estabelecida via QR code."}
            ))
            await self.send_to_worker({"type": "phone_connected"})

            return HTMLResponse(f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<style>
  body{{background:#07090f;color:#dde3ed;font-family:sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}}
  p{{color:#5e6a7e;font-size:14px}}
</style></head>
<body>
<script>
  sessionStorage.setItem('jarvis_token','{tok}');
  sessionStorage.setItem('jarvis_key','{key}');
  localStorage.setItem('jarvis_device_token','{dev_tok}');
  setTimeout(function(){{location.replace('/')}},400);
</script>
<p>Conectando ao JARVIS…</p>
</body></html>""")

        @app.post("/api/device-login")
        async def device_login_ep(req: Request):
            try:
                body = await req.json()
            except Exception:
                return JSONResponse({"ok": False}, status_code=400)
            dev_tok = (body.get("device_token") or "").strip()
            if not dev_tok or dev_tok not in self._device_sessions:
                return JSONResponse({"ok": False}, status_code=401)
            session_key = self._device_sessions[dev_tok]["session_key"]
            tok = secrets.token_urlsafe(32)
            self._tokens[tok] = session_key
            self._token_keys[tok] = session_key
            self._aes_key(session_key)
            await self.send_to_worker({"type": "phone_connected"})
            return JSONResponse({"ok": True, "token": tok, "key": session_key})

        @app.post("/api/command")
        async def command(req: Request):
            body = await req.json()
            text = (body.get("text") or "").strip()
            
            if text:
                # Show user message on dashboard
                await self.broadcast_to_browsers({"type": "log", "speaker": "user", "text": text, "ts": ""})

                if self._worker:
                    # PC Mode: forward to worker
                    await self.send_to_worker({"type": "command", "text": text})
                else:
                    # Cloud Mode: process locally
                    asyncio.create_task(self._process_cloud_command(text))
            return JSONResponse({"ok": True, "mode": self.mode})

        @app.post("/api/wake")
        async def wake_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Não autorizado"}, status_code=401)
            await self.send_to_worker({"type": "wake"})
            return JSONResponse({"ok": True})

        @app.get("/api/mode")
        async def mode_ep():
            """Return current operating mode."""
            return JSONResponse({
                "mode": self.mode,
                "label": self.mode_label,
                "cloud_available": _CLOUD_OK,
                "worker_connected": self._worker is not None,
            })

        # ── File upload ───────────────────────────────────────────────────
        if _UPLOAD_OK:
            @app.post("/api/upload")
            async def upload_file(req: Request, file: UploadFile = FastAPIFile(...)):
                if not _auth(req):
                    return JSONResponse({"error": "Não autorizado"}, status_code=401)
                import re
                name = Path(file.filename or "upload").name
                name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ") or "upload"
                dest = UPLOADS_DIR / name
                stem, suffix = Path(name).stem, Path(name).suffix
                counter = 1
                while dest.exists():
                    dest = UPLOADS_DIR / f"{stem}_{counter}{suffix}"
                    counter += 1
                size = 0
                max_bytes = MAX_UPLOAD_MB * 1024 * 1024
                try:
                    with open(dest, "wb") as fout:
                        while True:
                            chunk = await file.read(65536)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > max_bytes:
                                fout.close()
                                dest.unlink(missing_ok=True)
                                return JSONResponse({"error": f"Arquivo muito grande (máximo {MAX_UPLOAD_MB} MB)"}, status_code=413)
                            fout.write(chunk)
                except Exception as exc:
                    dest.unlink(missing_ok=True)
                    return JSONResponse({"error": str(exc)}, status_code=500)
                # Notify worker about file
                await self.send_to_worker({"type": "file_received", "name": dest.name, "size": size, "path": str(dest)})
                await self.broadcast_to_browsers({"type": "file_received", "name": dest.name, "size": size})
                return JSONResponse({"ok": True, "name": dest.name, "size": size})

        @app.get("/uploads/{filename}")
        async def download_file(filename: str, token: str = ""):
            tok = token.strip()
            if not tok or tok not in self._tokens:
                return JSONResponse({"error": "Não autorizado"}, status_code=401)
            import re
            safe = re.sub(r'[/\\]', '', filename)
            path = UPLOADS_DIR / safe
            if not path.exists() or not path.is_file():
                return JSONResponse({"error": "Não encontrado"}, status_code=404)
            return FileResponse(str(path), filename=safe)

        # ── WebSocket (browser clients) ──────────────────────────────────
        @app.websocket("/ws")
        async def ws_ep(websocket: WebSocket, token: str = ""):
            await websocket.accept()
            self._browser_clients.add(websocket)
            # Send history
            for entry in self._history[-50:]:
                try:
                    await websocket.send_json(entry)
                except Exception:
                    break
            # Send current status
            if self._worker:
                state = "active"
            elif _CLOUD_OK:
                state = "cloud_idle"
            else:
                state = "sleeping"
            await websocket.send_json({"type": "status", "state": state})
            # Send mode info
            await websocket.send_json({
                "type": "mode",
                "mode": self.mode,
                "label": self.mode_label,
            })
            try:
                while True:
                    data = await websocket.receive_json()
                    if data.get("type") == "command":
                        t = (data.get("text") or "").strip()
                        if t:
                            await self.broadcast_to_browsers({"type": "log", "speaker": "user", "text": t, "ts": ""})
                            if self._worker:
                                await self.send_to_worker({"type": "command", "text": t})
                            else:
                                asyncio.create_task(self._process_cloud_command(t))
            except WebSocketDisconnect:
                pass
            finally:
                self._browser_clients.discard(websocket)

        return app

    # ── Worker App (PC connects here) ─────────────────────────────────────

    def _build_worker_app(self) -> FastAPI:
        app = FastAPI(docs_url=None, redoc_url=None)

        @app.websocket("/ws/worker")
        async def worker_ws(websocket: WebSocket):
            await websocket.accept()
            if self._worker:
                await self._worker.close()
            self._worker = websocket
            print("[VPS] ✅ Worker (PC) conectado! → 🖥️ PC Mode")
            await self.broadcast_to_browsers({"type": "status", "state": "active"})
            await self.broadcast_to_browsers({
                "type": "mode",
                "mode": "pc",
                "label": "🖥️ PC Mode",
            })
            await self.broadcast_to_browsers({
                "type": "sys",
                "text": "🖥️ PC conectado — modo completo ativado.",
            })
            try:
                while True:
                    data = await websocket.receive_json()
                    msg_type = data.get("type")

                    if msg_type == "log":
                        # Worker sending log from JARVIS
                        await self.broadcast_to_browsers(data)

                    elif msg_type == "status":
                        # Worker sending status update
                        await self.broadcast_to_browsers(data)

                    elif msg_type == "audio_data":
                        # Audio data from JARVIS → relay to phone if connected
                        await self.broadcast_to_browsers(data)

            except WebSocketDisconnect:
                pass
            except Exception as e:
                print(f"[VPS] Worker error: {e}")
            finally:
                self._worker = None
                print("[VPS] ❌ Worker (PC) desconectado → ⛅ Cloud Mode")

                if _CLOUD_OK:
                    await self.broadcast_to_browsers({"type": "status", "state": "cloud_idle"})
                    await self.broadcast_to_browsers({
                        "type": "mode",
                        "mode": "cloud",
                        "label": "⛅ Cloud Mode",
                    })
                    await self.broadcast_to_browsers({
                        "type": "sys",
                        "text": "⛅ PC desconectado — modo cloud ativado. Recursos limitados a: pesquisa, clima, memória.",
                    })
                else:
                    await self.broadcast_to_browsers({"type": "status", "state": "sleeping"})
                    await self.broadcast_to_browsers({
                        "type": "mode",
                        "mode": "offline",
                        "label": "💤 Offline",
                    })

        # Worker API endpoints
        @app.post("/api/worker/log")
        async def worker_log(req: Request):
            body = await req.json()
            await self.broadcast_to_browsers(body)
            return JSONResponse({"ok": True})

        @app.post("/api/worker/status")
        async def worker_status(req: Request):
            body = await req.json()
            await self.broadcast_to_browsers(body)
            return JSONResponse({"ok": True})

        # New key generation endpoint (called by worker)
        @app.post("/api/new-key")
        async def new_key_ep():
            key = self.new_key()
            return JSONResponse({"ok": True, "key": key})

        return app


# ── Main ───────────────────────────────────────────────────────────────────

def _mount_worker_routes(dashboard_app: FastAPI, vps: VPSDashboard):
    """Mount worker routes onto the main dashboard app (single-port mode)."""
    for route in vps.worker_app.routes:
        dashboard_app.routes.append(route)
    print("[VPS] Worker routes mounted on main app (single-port mode)")


async def main():
    vps = VPSDashboard()

    if IS_CLOUD_DEPLOY:
        # ── Single-port mode (Railway/Render) ─────────────────────────
        # Mount worker endpoints onto the main app
        _mount_worker_routes(vps.app, vps)

        cfg = uvicorn.Config(
            vps.app, host="0.0.0.0", port=PORT, log_level="info"
        )

        print(f"[VPS] ☁️  Cloud Deploy Mode (single port)")
        print(f"[VPS] Server: http://0.0.0.0:{PORT}")
        print(f"[VPS] Worker endpoint: ws://0.0.0.0:{PORT}/ws/worker")
        if _CLOUD_OK:
            print(f"[VPS] ☁️  Cloud mode: ACTIVE (JARVIS responds even without PC)")
        else:
            print(f"[VPS] ⚠️  Cloud mode: INACTIVE (install google-genai for cloud mode)")

        tasks = [uvicorn.Server(cfg).serve()]
        if vps._cloud:
            tasks.append(vps._start_cloud_proactive_loop())
        await asyncio.gather(*tasks)

    else:
        # ── Dual-port mode (VPS / local dev) ─────────────────────────
        cfg_dashboard = uvicorn.Config(
            vps.app, host="0.0.0.0", port=PORT, log_level="info"
        )
        cfg_worker = uvicorn.Config(
            vps.worker_app, host="0.0.0.0", port=WORKER_PORT, log_level="info"
        )

        print(f"[VPS] Dashboard: http://0.0.0.0:{PORT}")
        print(f"[VPS] Worker endpoint: ws://0.0.0.0:{WORKER_PORT}/ws/worker")
        if _CLOUD_OK:
            print(f"[VPS] ☁️  Cloud mode: ACTIVE (JARVIS responds even without PC)")
        else:
            print(f"[VPS] ⚠️  Cloud mode: INACTIVE (install google-genai for cloud mode)")
        print("[VPS] Aguardando conexão...")

        tasks = [
            uvicorn.Server(cfg_dashboard).serve(),
            uvicorn.Server(cfg_worker).serve(),
        ]
        if vps._cloud:
            tasks.append(vps._start_cloud_proactive_loop())
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
