import sys
import json
import logging
from pathlib import Path
from src.logger_setup import setup_logging
from src.app import MonitorApp
from src.metrics import start_metrics_server

# Creación de objeto logger para imprimir logs
logger = logging.getLogger(__name__)

def main():
    setup_logging("app.log")
    start_metrics_server()
    app = MonitorApp(results_dir=Path("result"))

    try:
        logger.info("=" * 60)
        logger.info("INICIANDO MONITOR DE FILTRACIONES")
        logger.info("=" * 60)

        app.run()

    except FileNotFoundError as e:
        logger.error(f"(1) ERROR --> main(). Archivo de configuración no encontrado - {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"(2) ERROR --> main(). Archivo JSON mal formado - {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"(3) ERROR --> main(). Error crítico: {e}")
        logger.exception("Detalles del error:")
        sys.exit(1)
    finally:
        app.close()
        logger.info("Recursos liberados.")

if __name__ == "__main__":
    main()
