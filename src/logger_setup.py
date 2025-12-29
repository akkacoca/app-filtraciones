import logging

# Funcion que configura el logging (FECHA - NIVEL - MENSAJE)
def setup_logging(log_file: str = "app.log") -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
