FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Los modelos de sentence-transformers se descargan la primera vez y se cachean
# aqui. docker-compose monta un volumen en esta ruta para no re-bajarlos.
ENV HF_HOME=/models

WORKDIR /app

# git: necesario para clonar los repos a indexar.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# torch desde el indice CPU-only: la rueda por defecto arrastra CUDA y pesa
# ~2.5GB. Aqui no hay GPU, asi que la version CPU baja la imagen a ~1GB.
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
