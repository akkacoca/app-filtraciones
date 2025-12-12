import os
import requests
import json
from datetime import datetime
import schedule  
import time
import logging
from pathlib import Path
from typing import Dict, List, Set, Optional
import signal
import sys

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Constantes
RESULTS_DIR = Path('result')
MAX_FILES_PER_DOMAIN = 2
SCHEDULE_HOURS = 24
MAX_SLEEP_TIME = 300  # 5 minutos máximo de sleep
WAKE_BEFORE_SECONDS = 30  # Despertar 30s antes de la tarea

# Variable global para control de cierre limpio
shutdown_flag = False

def signal_handler(signum, frame):
    """Maneja señales de cierre del sistema"""
    global shutdown_flag
    logger.info("\nSeñal de cierre recibida. Finalizando...")
    shutdown_flag = True

# Registrar manejadores de señales
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

class ConfigManager:
    """Gestiona la carga de archivos de configuración"""
    
    @staticmethod
    def load_json(filepath: str) -> Dict:
        """Carga un archivo JSON de forma segura"""
        try:
            with open(filepath, 'r', encoding='utf-8') as file:
                return json.load(file)
        except FileNotFoundError:
            logger.error(f"Archivo no encontrado: {filepath}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Error al parsear JSON en {filepath}: {e}")
            raise

class SearchMonitor:
    """Clase principal para monitorear búsquedas"""
    
    def __init__(self, api_config: Dict, query_config: Dict, email_config: Dict):
        self.api_config = api_config
        self.query_config = query_config
        self.email_config = email_config
        self.session = requests.Session()  # Reutilizar conexiones HTTP
        RESULTS_DIR.mkdir(exist_ok=True)
    
    def __del__(self):
        """Cerrar sesión al destruir el objeto"""
        if hasattr(self, 'session'):
            self.session.close()
    
    def realizar_busqueda(self, domain: str) -> None:
        """Realiza una búsqueda y guarda los resultados"""
        params = {
            'q': domain,
            'api_key': self.api_config['api-key'],
            'num': 10
        }
        
        try:
            response = self.session.get(
                self.api_config['api-url'], 
                params=params,
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            self._guardar_resultados(domain, data)
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout al buscar {domain}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error de red al buscar {domain}: {e}")
        except Exception as e:
            logger.error(f"Error inesperado en búsqueda de {domain}: {e}")
    
    def _guardar_resultados(self, domain: str, data: Dict) -> None:
        """Guarda los resultados y gestiona archivos antiguos"""
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        folder_path = RESULTS_DIR / domain
        folder_path.mkdir(parents=True, exist_ok=True)
        
        filename = f"search_results_{timestamp}.json"
        file_path = folder_path / filename
        
        # Guardar resultados
        with open(file_path, 'w', encoding='utf-8') as json_file:
            json.dump(data, json_file, indent=4, ensure_ascii=False)
        
        logger.info(f"Resultados para {domain} guardados en {filename}")
        
        # Limpiar archivos antiguos
        self._limpiar_archivos_antiguos(folder_path)
        
        # Comparar resultados
        archivos = sorted(folder_path.glob('search_results_*.json'), reverse=True)
        if len(archivos) >= 2:
            self._comprobar_resultados(archivos[1], archivos[0])
    
    def _limpiar_archivos_antiguos(self, folder_path: Path) -> None:
        """Elimina archivos antiguos manteniendo solo los últimos N"""
        archivos = sorted(folder_path.glob('search_results_*.json'), reverse=True)
        
        for archivo in archivos[MAX_FILES_PER_DOMAIN:]:
            try:
                archivo.unlink()
                logger.info(f"Archivo eliminado: {archivo.name}")
            except OSError as e:
                logger.error(f"Error al eliminar {archivo.name}: {e}")
    
    def _comprobar_resultados(self, archivo_antiguo: Path, archivo_nuevo: Path) -> None:
        """Compara los resultados entre dos archivos"""
        try:
            with open(archivo_antiguo, 'r', encoding='utf-8') as file:
                antiguo_data = json.load(file)
            
            with open(archivo_nuevo, 'r', encoding='utf-8') as file:
                nuevo_data = json.load(file)
            
            links_antiguos = self._extraer_links(antiguo_data)
            links_nuevos = self._extraer_links(nuevo_data)
            
            nuevos_links = links_nuevos - links_antiguos
            links_eliminados = links_antiguos - links_nuevos
            
            if not nuevos_links and not links_eliminados:
                logger.info("No hay cambios en los enlaces de los resultados.")
                return
            
            if nuevos_links:
                logger.info("\n¡Nuevos enlaces detectados!")
                for link in nuevos_links:
                    logger.info(f"  - Nuevo enlace: {link}")
            
            if links_eliminados:
                logger.info("\n¡Enlaces eliminados detectados!")
                for link in links_eliminados:
                    logger.info(f"  - Enlace eliminado: {link}")
            
            # Solo enviar correo si hay cambios
            if nuevos_links or links_eliminados:
                self._enviar_correo(nuevos_links, links_eliminados)
            
        except Exception as e:
            logger.error(f"Error al comprobar resultados: {e}")
    
    @staticmethod
    def _extraer_links(data: Dict) -> Set[str]:
        """Extrae los enlaces de los resultados orgánicos"""
        return {
            result['link'] 
            for result in data.get('organic_results', []) 
            if 'link' in result
        }
    
    def _enviar_correo(self, nuevos_links: Set[str], links_eliminados: Set[str]) -> None:
        """Envía notificación por correo usando EmailJS"""
        url = "https://api.emailjs.com/api/v1.0/email/send"
        
        data = {
            "service_id": self.email_config["service_id"],
            "template_id": self.email_config["template_id"],
            "user_id": self.email_config["user_id"],
            "template_params": {
                "new_link": "\n".join(nuevos_links) if nuevos_links else "Ninguno",
                "removed_link": "\n".join(links_eliminados) if links_eliminados else "Ninguno",
                "email": self.email_config["email"],
            }
        }
        
        try:
            response = self.session.post(url, json=data, timeout=30)
            response.raise_for_status()
            logger.info("Correo enviado exitosamente!")
        except requests.exceptions.Timeout:
            logger.error("Timeout al enviar correo")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error al enviar correo: {e}")
    
    def ejecutar_busquedas(self) -> None:
        """Ejecuta búsquedas para todos los dominios configurados"""
        logger.info("=" * 60)
        logger.info("Iniciando tarea programada...")
        logger.info(f"Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("=" * 60)
        
        dominios = self.query_config.get("domains", [])
        total = len(dominios)
        
        for idx, domain in enumerate(dominios, 1):
            if shutdown_flag:
                logger.info("Deteniendo búsquedas por señal de cierre...")
                break
                
            logger.info(f"[{idx}/{total}] Buscando información para: {domain}")
            self.realizar_busqueda(domain)
            
            # Pequeña pausa entre dominios para no saturar la API
            if idx < total:
                time.sleep(2)
        
        logger.info("=" * 60)
        logger.info("Tarea programada completada.")
        logger.info(f"Próxima ejecución en {SCHEDULE_HOURS} horas")
        logger.info("=" * 60)

def calcular_sleep_time() -> float:
    """Calcula el tiempo óptimo de sleep basado en próxima tarea"""
    idle = schedule.idle_seconds()
    
    # Si no hay tareas programadas o ya pasó el tiempo
    if idle is None or idle <= 0:
        return 1
    
    # Si falta mucho tiempo, dormir máximo MAX_SLEEP_TIME
    # Si falta poco, despertar WAKE_BEFORE_SECONDS antes
    if idle > MAX_SLEEP_TIME + WAKE_BEFORE_SECONDS:
        return MAX_SLEEP_TIME
    else:
        return max(1, idle - WAKE_BEFORE_SECONDS)

def main():
    """Función principal optimizada para mínimo consumo de recursos"""
    global shutdown_flag
    
    try:
        logger.info("=" * 60)
        logger.info("INICIANDO MONITOR DE FILTRACIONES")
        logger.info("=" * 60)
        
        # Cargar configuraciones
        logger.info("Cargando configuraciones...")
        config_manager = ConfigManager()
        api_config = config_manager.load_json('serpapi_api.json')
        query_config = config_manager.load_json('querys.json')
        email_config = config_manager.load_json('emailjs_api.json')
        
        # Inicializar monitor
        monitor = SearchMonitor(api_config, query_config, email_config)
        
        # Mostrar configuración
        num_dominios = len(query_config.get("domains", []))
        logger.info(f"Dominios a monitorear: {num_dominios}")
        logger.info(f"Frecuencia de monitoreo: cada {SCHEDULE_HOURS} horas")
        logger.info(f"Directorio de resultados: {RESULTS_DIR.absolute()}")
        
        # Ejecutar inmediatamente la primera vez
        logger.info("\nEjecutando primera búsqueda...")
        monitor.ejecutar_busquedas()
        
        # Programar ejecuciones periódicas
        schedule.every(SCHEDULE_HOURS).hours.do(monitor.ejecutar_busquedas)
        
        logger.info(f"\n✓ Monitor activo. Presiona Ctrl+C para detener.")
        logger.info("=" * 60 + "\n")
        
        # Loop principal optimizado
        while not shutdown_flag:
            # Ejecutar tareas pendientes
            schedule.run_pending()
            
            # Calcular tiempo óptimo de sleep
            sleep_time = calcular_sleep_time()
            
            # Dormir en intervalos pequeños para poder responder a shutdown_flag
            elapsed = 0
            while elapsed < sleep_time and not shutdown_flag:
                time.sleep(min(1, sleep_time - elapsed))
                elapsed += 1
        
        logger.info("\n" + "=" * 60)
        logger.info("Monitor detenido correctamente.")
        logger.info("=" * 60)
        
    except FileNotFoundError as e:
        logger.error(f"Error: Archivo de configuración no encontrado - {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Error: Archivo JSON mal formado - {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error crítico: {e}")
        logger.exception("Detalles del error:")
        sys.exit(1)
    finally:
        # Limpiar recursos
        if 'monitor' in locals():
            del monitor
        logger.info("Recursos liberados.")

if __name__ == "__main__":
    main()