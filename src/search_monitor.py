import json
import time
import logging
import re
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, Set, Any, List, Optional, Tuple
from urllib.parse import quote
from .config_manager import ConfigManager
import random
import math

from .metrics import (
    QUERY_DURATION, ROWS_FETCHED_TOTAL, NEW_LEAKS_TOTAL,
    ERRORS_TOTAL, RATE_LIMITED_TOTAL, Timer
)


logger = logging.getLogger(__name__)

class SearchMonitor:
    """
    - Consulta LeakCheck Pro API v2
    - Guarda snapshots JSON por query
    - Mantiene solo N archivos por query
    - Compara snapshot anterior vs nuevo (nuevas filtraciones)
    - Envía email si hay nuevas filtraciones
    """

    # Constructor SearchMonitor
    def __init__(
        self,
        api_config: Dict[str, Any],
        query_config: Dict[str, Any],
        email_config: Dict[str, Any],
        results_dir: Path,
        max_files_per_domain: int = 2,
        pause_between_domains: float = 0.6, 
    ):
        self.api_config = api_config
        self.query_config = query_config
        self.email_config = email_config

        self.results_dir = results_dir
        self.max_files_per_query = max_files_per_domain  
        self.pause_between_queries = pause_between_domains

        self.session = requests.Session()
        self.cfg = ConfigManager()

        self.results_dir.mkdir(exist_ok=True)

        self.max_rps = int(self.api_config.get("max_rps", 3))
        self._min_interval = 1.0 / max(1, self.max_rps)
        self._last_call_ts = 0.0
        
        self.max_429_retries = int(self.api_config.get("max_429_retries", 8))
        self.backoff_base_seconds = float(self.api_config.get("backoff_base_seconds", 2.0))
        self.backoff_cap_seconds = float(self.api_config.get("backoff_cap_seconds", 60.0))
        self.max_query_seconds = int(self.api_config.get("max_query_seconds", 300))  # timeout total por query

    # Funcion que cierra la sesion HTTP
    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    # Funcion encargada de normalizar nombres para ser usados de nombre de carpeta
    @staticmethod
    def _sanitize_fs_name(s: str, max_len: int = 80) -> str:
        s = (s or "").strip()
        s = re.sub(r"^https?://", "", s, flags=re.IGNORECASE).strip().strip("/")
        s = re.sub(r"[^\w\-.@]+", "_", s)
        return (s[:max_len] if len(s) > max_len else s) or "empty"

    # Funcion encargada de normalizar querys para evitar ERROR 400 'Invalid characters in query'
    @staticmethod
    def _sanitize_query_by_type(q: str, qtype: str) -> str:
        """
        - phone: solo dígitos (ej: 12063428631)
        - keyword/username: sin espacios (los pasamos a '_') y filtrado básico
        - domain: sin protocolo
        - email: tal cual
        - auto: sin espacios (para no romper el path)
        """
        q = (q or "").strip()
        t = (qtype or "auto").lower()

        if t == "phone":
            return re.sub(r"\D", "", q)

        if t == "domain":
            q = re.sub(r"^https?://", "", q, flags=re.IGNORECASE).strip().strip("/")
            return re.sub(r"[^a-zA-Z0-9.\-]", "", q)

        if t in ("keyword", "username"):
            q = re.sub(r"\s+", "_", q)
            return re.sub(r"[^a-zA-Z0-9._\-]", "", q)

        if t == "email":
            return q

        return re.sub(r"\s+", "_", q)

    # Funcion que comprueba que sea un email valido
    @staticmethod
    def _mask_email(email: str) -> str:
        if "@" not in (email or ""):
            return (email[:2] + "***") if email else ""
        user, dom = email.split("@", 1)
        if len(user) <= 2:
            return f"{user[:1]}***@{dom}"
        return f"{user[:2]}***@{dom}"

    # Funcion que enmascara el numero de telefono mostrando unicamente los 4 ultimos digitos
    @staticmethod
    def _mask_phone(phone: str) -> str:
        digits = re.sub(r"\D", "", phone or "")
        if not digits:
            return ""
        if len(digits) <= 4:
            return "***"
        return f"***{digits[-4:]}"

    # Funcion que asegura que no se supere max_rps
    def _throttle(self) -> None:
        now = time.time()
        wait = (self._last_call_ts + self._min_interval) - now
        if wait > 0:
            time.sleep(wait)
        self._last_call_ts = time.time()

    # Funcion encargada de normalizar querys
    def _normalize_queries(self) -> List[Dict[str, str]]:
        """
        Nuevo formato:
          {"queries":[{"q":"...", "type":"email|domain|keyword|..."}]}
        Compatibilidad antigua:
          {"domains":["a.com","b.com"]} -> type=domain
        """
        out: List[Dict[str, str]] = []
        if isinstance(self.query_config.get("queries"), list):
            for it in self.query_config["queries"]:
                if not isinstance(it, dict):
                    continue
                q = str(it.get("q", "")).strip()
                if not q:
                    continue
                t = str(it.get("type", "auto")).strip() or "auto"
                out.append({"q": q, "type": t})
            return out

        domains = self.query_config.get("domains", [])
        if isinstance(domains, list):
            for d in domains:
                d = str(d).strip()
                if d:
                    out.append({"q": d, "type": "domain"})
        return out

    # Funcion que realizar la busqueda de fitraciones para un dominio
    def realizar_busqueda(self, q_raw: str, qtype: str = "auto") -> None:

        with Timer() as t:
            try:
                base_url = str(self.api_config.get("base_url", "https://leakcheck.io/api/v2/query")).rstrip("/")
                api_key = str(self.api_config["api_key"])
                timeout = int(self.api_config.get("timeout", 30))

                # limit max 1000, offset max 2500}
                limit = int(self.api_config.get("limit", 200))
                limit = max(1, min(limit, 1000))

                q_sanitized = self._sanitize_query_by_type(q_raw, qtype)
                if not q_sanitized:
                    logger.warning(f"(1) WARNING --> realizar_busqueda. Query vacía tras sanitizar: '{q_raw}' (type={qtype})")
                    return

                headers = {"Accept": "application/json", "X-API-Key": api_key}

                all_rows: List[Dict[str, Any]] = []
                quota = None
                offset = 0
                truncated = False
                last_success = True

                start_ts = time.time()
                retries_429 = 0

                while True:
                    # dentro del while True:
                    if (time.time() - start_ts) > self.max_query_seconds:
                        ERRORS_TOTAL.labels(kind="query_total_timeout").inc()
                        raise TimeoutError(f"Timeout total de query ({self.max_query_seconds}s) para '{q_raw}' (type={qtype})")

                    if offset > 2500:
                        logger.warning("(2) WARNING --> realizar_busqueda. LeakCheck: offset > 2500, paro paginación.")
                        truncated = True
                        break

                    self._throttle()

                    url = f"{base_url}/{quote(q_sanitized, safe='')}"
                    params: Dict[str, Any] = {"limit": limit, "offset": offset}
                    if qtype and qtype != "auto":
                        params["type"] = qtype

                    resp = self.session.get(url, headers=headers, params=params, timeout=timeout)

                    if resp.status_code == 429:
                        RATE_LIMITED_TOTAL.inc()

                        retries_429 += 1
                        if retries_429 > self.max_429_retries:
                            ERRORS_TOTAL.labels(kind="rate_limited_abort").inc()
                            raise RuntimeError(
                                f"LeakCheck 429 persistente: abortando tras {self.max_429_retries} reintentos"
                            )

                        # backoff exponencial con jitter
                        backoff = min(self.backoff_cap_seconds, self.backoff_base_seconds * (2 ** (retries_429 - 1)))
                        backoff = backoff + random.uniform(0, 0.25 * backoff)

                        logger.warning(
                            f"(3) WARNING --> realizar_busqueda. LeakCheck 429. Retry {retries_429}/{self.max_429_retries}. "
                            f"Durmiendo {backoff:.1f}s."
                        )
                        time.sleep(backoff)
                        continue

                    resp.raise_for_status()
                    data = resp.json()

                    last_success = bool(data.get("success", True))
                    quota = data.get("quota", quota)

                    chunk = data.get("result", []) or []
                    if isinstance(chunk, list):
                        # métricas: filas recibidas en esta página
                        ROWS_FETCHED_TOTAL.inc(len(chunk))
                        all_rows.extend([x for x in chunk if isinstance(x, dict)])

                    if len(chunk) < limit:
                        break

                    offset += limit

                final = {
                    "success": last_success,
                    "quota": quota,
                    "found": len(all_rows),
                    "truncated_by_offset_limit": truncated,
                    "result": all_rows
                }
                self._guardar_resultados(q_raw, qtype, final)

            except Exception as e:
                ERRORS_TOTAL.labels(kind="leakcheck_request").inc()
                logger.error(f"(X) ERROR --> realizar_busqueda. Excepción en query '{q_raw}' (type={qtype}): {e}", exc_info=True)

            finally:
                QUERY_DURATION.observe(t.dt)



    # -------------------------
    # Guardado / diff / email
    # -------------------------
    def _folder_for_query(self, q_raw: str, qtype: str) -> Path:
        safe = self._sanitize_fs_name(f"{qtype}__{q_raw}")
        return self.results_dir / safe

    def _guardar_resultados(self, q_raw: str, qtype: str, data: Dict[str, Any]) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        folder_path = self._folder_for_query(q_raw, qtype)
        folder_path.mkdir(parents=True, exist_ok=True)

        filename = f"leaks_{timestamp}.json"
        file_path = folder_path / filename

        file_path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
        logger.info(f"LeakCheck [{qtype}] '{q_raw}': {data.get('found', 0)} filas (quota: {data.get('quota', 'N/A')})")

        self._limpiar_archivos_antiguos(folder_path)

        archivos = sorted(folder_path.glob("leaks_*.json"), reverse=True)
        if len(archivos) >= 2:
            self._comprobar_resultados(archivos[1], archivos[0], q_raw, qtype)

    def _limpiar_archivos_antiguos(self, folder_path: Path) -> None:
        archivos = sorted(folder_path.glob("leaks_*.json"), reverse=True)
        for archivo in archivos[self.max_files_per_query:]:
            try:
                archivo.unlink()
                logger.info(f"Archivo eliminado: {archivo.name}")
            except OSError as e:
                logger.error(f"Error al eliminar {archivo.name}: {e}")

    @staticmethod
    def _fingerprint_leak(entry: Dict[str, Any]) -> str:
        src = entry.get("source", {}) or {}
        fields = entry.get("fields", []) or []
        return "|".join([
            str(entry.get("email", "") or ""),
            str(entry.get("username", "") or ""),
            str(entry.get("phone", "") or ""),
            str(src.get("name", "") or ""),
            str(src.get("breach_date", "") or ""),
            ",".join(sorted(str(x) for x in fields if x is not None))
        ])

    def _extract_fingerprints(self, data: Dict[str, Any]) -> Set[str]:
        out: Set[str] = set()
        for e in (data.get("result", []) or []):
            if isinstance(e, dict):
                out.add(self._fingerprint_leak(e))
        return out

    def _preview_new(self, new_data: Dict[str, Any], added: Set[str], limit: int = 15) -> List[str]:
        lines: List[str] = []
        for e in (new_data.get("result", []) or []):
            if not isinstance(e, dict):
                continue
            if self._fingerprint_leak(e) not in added:
                continue

            src = e.get("source", {}) or {}
            src_name = str(src.get("name", "") or "")
            breach_date = str(src.get("breach_date", "") or "")

            email = self._mask_email(str(e.get("email", "") or ""))
            username = str(e.get("username", "") or "")
            phone = self._mask_phone(str(e.get("phone", "") or ""))

            line = f"- source={src_name} date={breach_date} email={email}"
            if username:
                line += f" user={username}"
            if phone:
                line += f" phone={phone}"
            lines.append(line)

            if len(lines) >= limit:
                break
        return lines

    # Funcion que comprueba los resultados de la busqueda y llama a _enviar:correo si hay nuevas filtraciones
    def _comprobar_resultados(self, archivo_antiguo: Path, archivo_nuevo: Path, q_raw: str, qtype: str) -> None:
        try:
            antiguo_data = self.cfg.load_json(archivo_antiguo)
            nuevo_data = self.cfg.load_json(archivo_nuevo)

            old_set = self._extract_fingerprints(antiguo_data)
            new_set = self._extract_fingerprints(nuevo_data)

            added = new_set - old_set
            removed = old_set - new_set

            if not added:
                logger.info("No hay nuevas filtraciones.")
                return

            logger.info(f"¡Nuevas filtraciones detectadas! +{len(added)}")
            
            NEW_LEAKS_TOTAL.inc(len(added))

            subject = f"[LeakCheck] NUEVAS filtraciones '{q_raw}' (type={qtype}) +{len(added)}"
            body = "\n".join([
                f"Query: {q_raw}",
                f"Type: {qtype}",
                f"Nuevas filas: {len(added)}",
                f"Quota: {nuevo_data.get('quota', 'N/A')}",
                "",
                "Preview (enmascarado):",
                *self._preview_new(nuevo_data, added)
            ])

            self._enviar_correo(subject, body)

        except Exception as e:
            ERRORS_TOTAL.labels(kind="diff_compare").inc()
            logger.error(f"(1) ERROR --> comprobar_resultados(). Error al comprobar resultados: {e}")

    # Funcion que genera el correo de alerta y lo envia segun los parametros del payload
    def _enviar_correo(self, subject: str, body: str) -> None:
        url = "https://api.emailjs.com/api/v1.0/email/send"
        payload = {
            "service_id": self.email_config["service_id"],
            "template_id": self.email_config["template_id"],
            "user_id": self.email_config["user_id"],
            "template_params": {
                "new_link": subject,
                "removed_link": body,
                "email": self.email_config["email"],
            }
        }

        try:
            response = self.session.post(url, json=payload, timeout=30)
            response.raise_for_status()
            logger.info("Correo enviado exitosamente!")
        except requests.exceptions.Timeout:
            logger.error("(1) ERROR --> _enviar_correo(). Timeout al enviar correo.")
        except requests.exceptions.RequestException as e:
            logger.error(f"(2) ERROR --> _enviar_correo(). Error al enviar correo: {e}")

    # Funcion que controla la busqueda de los dominios
    def ejecutar_busquedas(self, should_stop: callable) -> None:
        queries = self._normalize_queries()
        total = len(queries)

        logger.info("=" * 60)
        logger.info("Iniciando tarea programada (LeakCheck)...")
        logger.info(f"Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)

        for idx, item in enumerate(queries, 1):
            if should_stop():
                logger.info("Deteniendo búsquedas por señal de cierre...")
                break

            q_raw = item["q"]
            qtype = item["type"]

            logger.info(f"[{idx}/{total}] LeakCheck query: '{q_raw}' (type={qtype})")
            try:
                self.realizar_busqueda(q_raw, qtype)
            except Exception as e:
                ERRORS_TOTAL.labels(kind="query_exception").inc()
                logger.error(f"Error en query '{q_raw}' (type={qtype}): {e}", exc_info=True)

            if idx < total and not should_stop():
                time.sleep(self.pause_between_queries)

        logger.info("=" * 60)
        logger.info("Tarea programada completada.")
        logger.info("=" * 60)
