# Lead Processing Service - Cloud Run
# Multi-stage build dla mniejszego obrazu

# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /app

# Zainstaluj zależności budowania
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Skopiuj requirements i zainstaluj zależności
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt


# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Skopiuj zainstalowane pakiety z buildera
COPY --from=builder /root/.local /root/.local

# Upewnij się że pakiety są w PATH
ENV PATH=/root/.local/bin:$PATH

# Zmienne środowiskowe dla Cloud Run
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Skopiuj kod aplikacji
COPY src/ ./src/

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

# Uruchom serwer
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
