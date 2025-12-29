import os
import time
import logging
from prometheus_client import Counter, Gauge, Histogram, start_http_server

logger = logging.getLogger(__name__)

# --- Métricas "de runs" ---
RUNS_TOTAL = Counter("leakmonitor_runs_total", "Número total de ejecuciones del monitor")
LAST_RUN_TS = Gauge("leakmonitor_last_run_timestamp", "Timestamp (epoch) del último run")
LAST_RUN_SUCCESS = Gauge("leakmonitor_last_run_success", "1 si el último run fue OK, 0 si falló")

# --- Métricas por query ---
QUERY_DURATION = Histogram(
    "leakmonitor_query_duration_seconds",
    "Duración de cada query (segundos)",
    buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 40, 60)
)

ROWS_FETCHED_TOTAL = Counter("leakmonitor_rows_fetched_total", "Filas totales recibidas de la API")
NEW_LEAKS_TOTAL = Counter("leakmonitor_new_leaks_total", "Nuevas filtraciones detectadas")
ERRORS_TOTAL = Counter("leakmonitor_errors_total", "Errores totales", ["kind"])
RATE_LIMITED_TOTAL = Counter("leakmonitor_rate_limited_total", "Número de respuestas 429 (rate limit)")

# --- Estado general ---
IN_PROGRESS = Gauge("leakmonitor_in_progress", "1 si está ejecutando un run, 0 si no")


def start_metrics_server() -> int:
    """
    Levanta el endpoint /metrics en un puerto interno.
    Por defecto: 8000 (configurable por env METRICS_PORT).
    """
    port = int(os.getenv("METRICS_PORT", "8000"))
    try:
        start_http_server(port)
        logger.info(f"[metrics] Servidor de métricas levantado en :{port} (/metrics)")
    except Exception as e:
        logger.error(f"[metrics] No se pudo levantar el servidor de métricas en :{port}: {e}")
        raise
    return port


class Timer:
    """Context manager simple para medir tiempos."""
    def __init__(self):
        self.t0 = 0.0
        self.dt = 0.0

    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.dt = time.time() - self.t0
