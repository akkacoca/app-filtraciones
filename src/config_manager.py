import os
import json
import logging
from typing import Dict, Any, Union
from pathlib import Path

logger = logging.getLogger(__name__)

class ConfigManager:

    # Funcion que carga JSONs de configuracion/archivos de forma segura
    @staticmethod
    def load_json(filepath: Union[str, Path]) -> Dict[str, Any]:
        path = Path(filepath)
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"(1) ERROR --> load_json(). Archivo no encontrado: {path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"(2) ERROR --> load_json(). Fallo al parsear JSON en {path}: {e}")
            raise
    
    @staticmethod
    def _env_or_json(cfg: Dict[str, Any], json_key: str, env_key: str) -> str:
        """
        Devuelve primero el valor del JSON si existe y no está vacío.
        Si está vacío, devuelve el valor de la variable de entorno.
        """
        v = (cfg.get(json_key) or "")
        if isinstance(v, str):
            v = v.strip()
        else:
            v = str(v).strip() if v is not None else ""

        if not v:
            v = (os.getenv(env_key) or "").strip()

        return v

    @staticmethod
    def load_leakcheck_config(filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Carga config de LeakCheck desde JSON y rellena api_key desde env si viene vacía.
        """
        cfg = ConfigManager.load_json(filepath)

        api_key = ConfigManager._env_or_json(cfg, "api_key", "LEAKCHECK_API_KEY")
        if not api_key:
            raise ValueError(
                "LeakCheck API key missing. Define LEAKCHECK_API_KEY en .env (recomendado) "
                "o rellena api_key en config/leakcheck_api.json"
            )

        cfg["api_key"] = api_key
        return cfg

    @staticmethod
    def load_emailjs_config(filepath: Union[str, Path]) -> Dict[str, Any]:
        """
        Carga config de EmailJS desde JSON y rellena campos desde env si vienen vacíos.
        Si tu app permite desactivar EmailJS, NO hacemos raise aquí: solo devolvemos cfg.
        """
        cfg = ConfigManager.load_json(filepath)

        cfg["service_id"] = ConfigManager._env_or_json(cfg, "service_id", "EMAILJS_SERVICE_ID")
        cfg["template_id"] = ConfigManager._env_or_json(cfg, "template_id", "EMAILJS_TEMPLATE_ID")
        cfg["user_id"] = ConfigManager._env_or_json(cfg, "user_id", "EMAILJS_USER_ID")
        cfg["email"] = ConfigManager._env_or_json(cfg, "email", "EMAILJS_EMAIL")

        return cfg

