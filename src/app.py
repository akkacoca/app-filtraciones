# src/app.py
import time
import json
import logging
import schedule
import signal
import os
from pathlib import Path
from typing import Optional

# +++ NUEVO (Linux/EC2): lockfile con fcntl
import fcntl

from .config_manager import ConfigManager
from .search_monitor import SearchMonitor
from .metrics import RUNS_TOTAL, LAST_RUN_TS, LAST_RUN_SUCCESS, IN_PROGRESS, ERRORS_TOTAL

logger = logging.getLogger(__name__)

RUN_SINGLE_FILE = Path("result/_run_single.json")


class _FileLock:
    """Lockfile simple para evitar runs concurrentes en EC2/Docker."""
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.fp = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.fp = open(self.lock_path, "w", encoding="utf-8")
        try:
            fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.fp.write(str(os.getpid()))
            self.fp.flush()
            return True
        except BlockingIOError:
            return False

    def release(self):
        if self.fp:
            try:
                fcntl.flock(self.fp.fileno(), fcntl.LOCK_UN)
            finally:
                try:
                    self.fp.close()
                except Exception:
                    pass
            self.fp = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()


class MonitorApp:
    def __init__(
        self,
        results_dir: Path,
        schedule_hours: int = 24,
        max_sleep_time: int = 300,
        wake_before_seconds: int = 30,
        max_files_per_domain: int = 14,  # <-- CAMBIO RECOMENDADO: guarda más histórico
    ):
        self.results_dir = results_dir
        self.schedule_hours = schedule_hours
        self.max_sleep_time = max_sleep_time
        self.wake_before_seconds = wake_before_seconds
        self.max_files_per_domain = max_files_per_domain

        self.shutdown_flag = False
        self.monitor: Optional[SearchMonitor] = None
        self.cfg = ConfigManager()

        # Lockfile para el run completo
        self._run_lock_path = self.results_dir / ".run.lock"

        self._install_signals()

    def _install_signals(self):
        def handler(signum, frame):
            logger.info("\nSeñal de cierre recibida. Finalizando.")
            self.shutdown_flag = True

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def should_stop(self) -> bool:
        return self.shutdown_flag

    def calcular_sleep_time(self) -> float:
        idle = schedule.idle_seconds()
        if idle is None or idle <= 0:
            return 1
        if idle > self.max_sleep_time + self.wake_before_seconds:
            return self.max_sleep_time
        return max(1, idle - self.wake_before_seconds)

    def load_and_build_monitor(self) -> None:
        api_config   = self.cfg.load_leakcheck_config("config/leakcheck_api.json")
        query_config = self.cfg.load_json("config/querys.json")
        email_config = self.cfg.load_emailjs_config("config/emailjs_api.json")

        self.monitor = SearchMonitor(
            api_config=api_config,
            query_config=query_config,
            email_config=email_config,
            results_dir=self.results_dir,
            max_files_per_domain=self.max_files_per_domain,
            pause_between_domains=0.6
        )

        queries = query_config.get("queries", [])
        if isinstance(queries, list) and queries:
            logger.info(f"Queries: {len(queries)}")
        else:
            logger.info(f"Dominios (modo legacy): {len(query_config.get('domains', []))}")

        logger.info(f"Directorio de resultados: {self.results_dir.absolute()}")
        logger.info(f"Frecuencia: cada {self.schedule_hours} horas")

    def _run_once(self) -> None:
        """Ejecuta una iteración completa del monitor, instrumentada con métricas."""
        # Lock: si ya hay un run, no arrancamos otro.
        with _FileLock(self._run_lock_path) as lk:
            if not lk.acquire():
                logger.warning("Ya hay un run en curso (.run.lock). Omitiendo esta ejecución.")
                ERRORS_TOTAL.labels(kind="run_locked").inc()
                return

            IN_PROGRESS.set(1)
            RUNS_TOTAL.inc()
            LAST_RUN_SUCCESS.set(0)

            try:
                assert self.monitor is not None
                self.monitor.ejecutar_busquedas(self.should_stop)
                LAST_RUN_SUCCESS.set(1)
            except Exception as e:
                ERRORS_TOTAL.labels(kind="run_exception").inc()
                logger.error(f"Error en run del monitor: {e}", exc_info=True)
            finally:
                LAST_RUN_TS.set(int(time.time()))
                IN_PROGRESS.set(0)

    def _check_run_single(self):
        if not RUN_SINGLE_FILE.exists():
            return
        try:
            req = json.loads(RUN_SINGLE_FILE.read_text(encoding="utf-8"))
            q = (req.get("q") or "").strip()
            t = (req.get("type") or "auto").strip() or "auto"
            RUN_SINGLE_FILE.unlink(missing_ok=True)

            if not q:
                logger.warning("[run-single] Petición inválida (q vacío). Ignorando.")
                ERRORS_TOTAL.labels(kind="run_single_invalid").inc()
                return

            logger.info(f"[run-single] Ejecutando búsqueda inmediata: {t}:{q}")
            assert self.monitor is not None

            # Para run-single también conviene lock (evita pisarse con el scheduler)
            with _FileLock(self._run_lock_path) as lk:
                if not lk.acquire():
                    logger.warning("[run-single] Ya hay un run en curso. Ignorando run-single.")
                    ERRORS_TOTAL.labels(kind="run_single_locked").inc()
                    return
                self.monitor.realizar_busqueda(q, t)

        except Exception as e:
            ERRORS_TOTAL.labels(kind="run_single_exception").inc()
            logger.error(f"[run-single] Fallo procesando petición: {e}", exc_info=True)

    def run(self) -> None:
        if self.monitor is None:
            self.load_and_build_monitor()
        assert self.monitor is not None

        logger.info("Ejecutando primera búsqueda.")
        self._run_once()

        # Limpia schedules por si se reimporta/reusa
        schedule.clear()

        # Mantengo tu lógica "cada X horas"
        schedule.every(self.schedule_hours).hours.do(self._run_once)

        logger.info("Monitor activo. Presiona Ctrl+C para detener.")
        logger.info("=" * 60 + "\n")

        while not self.shutdown_flag:
            # +++ IMPORTANTE: run-single se chequea SIEMPRE
            self._check_run_single()

            schedule.run_pending()
            sleep_time = self.calcular_sleep_time()

            elapsed = 0.0
            while elapsed < sleep_time and not self.shutdown_flag:
                dt = min(1.0, sleep_time - elapsed)
                time.sleep(dt)
                elapsed += dt

    def close(self) -> None:
        if self.monitor:
            self.monitor.close()
