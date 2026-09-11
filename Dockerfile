# FluidPy: Python-SPH-Solver und statische WebGL-Oberfläche in einem Prozess.
# Keine Build-Toolchain nötig, NumPy und SciPy kommen als manylinux-Wheels.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# SciPy ist im Container fest dabei: die Nachbarsuche läuft damit etwa doppelt
# so schnell wie mit dem reinen NumPy-Gitter.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt "scipy>=1.11"

COPY physics.py app.py ./
COPY web ./web

# Unprivilegiert; das Abbild wird zur Laufzeit schreibgeschützt eingebunden.
RUN useradd --system --uid 10001 fluid
USER 10001

EXPOSE 8765

# --host 0.0.0.0 gilt nur containerintern. Nach außen wird der Port in
# docker-compose.yml bewusst nur an 127.0.0.1 des Hosts veröffentlicht.
CMD ["python", "app.py", "--no-browser", "--host", "0.0.0.0", "--port", "8765"]
