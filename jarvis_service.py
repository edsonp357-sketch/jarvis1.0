"""
jarvis_service.py — JARVIS 24h Service
Mantém o JARVIS rodando 24/7 com auto-restart.
"""

import subprocess
import sys
import time
import os
import logging
from pathlib import Path

# Config
BASE_DIR = Path(__file__).parent
LOG_FILE = BASE_DIR / "jarvis_service.log"
PID_FILE = BASE_DIR / "jarvis_service.pid"
MAX_RESTARTS = 100
RESTART_DELAY = 5

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("JARVIS-Service")


def write_pid():
    PID_FILE.write_text(str(os.getpid()), encoding='utf-8')


def read_pid():
    try:
        return int(PID_FILE.read_text(encoding='utf-8').strip())
    except Exception:
        return None


def kill_previous():
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, 9)
            log.info(f"Processo anterior ({pid}) finalizado.")
        except Exception:
            pass
    write_pid()


def is_running():
    """Verifica se o JARVIS já está rodando."""
    pid = read_pid()
    if pid:
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            pass
    return False


def run_jarvis():
    """Executa o JARVIS com --remote."""
    cmd = [sys.executable, str(BASE_DIR / "main.py"), "--remote"]
    log.info(f"Iniciando JARVIS: {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
    )

    write_pid()
    log.info(f"JARVIS PID: {process.pid}")

    return process


def monitor():
    """Mantém o JARVIS rodando 24/7."""
    kill_previous()

    restart_count = 0

    while restart_count < MAX_RESTARTS:
        process = run_jarvis()

        try:
            # Lê output em tempo real
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    print(line.decode('utf-8', errors='replace'), end='')

            exit_code = process.wait()
            log.warning(f"JARVIS encerrou com código: {exit_code}")

        except Exception as e:
            log.error(f"Erro: {e}")
            process.kill()

        restart_count += 1
        log.info(f"Reiniciando em {RESTART_DELAY}s... (tentativa {restart_count}/{MAX_RESTARTS})")
        time.sleep(RESTART_DELAY)

    log.error("Número máximo de reinícios atingido.")


if __name__ == "__main__":
    log.info("=" * 50)
    log.info("JARVIS Service iniciado")
    log.info("=" * 50)
    monitor()
