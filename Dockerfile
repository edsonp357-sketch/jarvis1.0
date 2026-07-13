FROM python:3.11-slim

WORKDIR /app

# Instala dependências
COPY requirements-cloud.txt .
RUN pip install --no-cache-dir -r requirements-cloud.txt

# Copia o código
COPY . .

# Comando para iniciar
CMD ["sh", "-c", "cd dashboard && python vps_server.py"]
