FROM python:3.12-slim

# Evita buffers (logs en tiempo real)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Instala dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el código
COPY . .

# Crea carpeta de resultados (por si acaso)
RUN mkdir -p /app/result

# Ejecuta tu main
CMD ["python", "main.py"]