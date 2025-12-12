FROM python:3.10-slim

# Establecemos el directorio de trabajo en el contenedor
WORKDIR /app-filtraciones

# Copiamos los archivos necesarios del proyecto al contenedor
COPY . /app-filtraciones

# Instalamos las dependencias desde el archivo requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Exponemos el puerto en el que la app escuchará
EXPOSE 5000

# Definimos el comando para ejecutar la aplicación
CMD ["python", "main.py"]
