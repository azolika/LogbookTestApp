# Kicsi és gyors image
FROM python:3.11-slim

# Opcionális: hasznos OS csomagok a futáshoz és healthcheckhez
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Időzóna adatok (tzdata már python csomagként is jön, de OS oldalon sem árt)
ENV TZ=Europe/Bucharest
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Csak a requirements-t másoljuk először a gyorsabb layer cache miatt
COPY requirements.txt /app/
RUN pip install -r requirements.txt

# App forrás bemásolása
# Ha a fájlod neve nem app.py, cseréld le lentebb is a CMD-ben!
COPY . /app

# Streamlit port
EXPOSE 8501

# Streamlit beállítások – elérhető legyen hálózatról
ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0

# Opcionális: FM API kulcs és endpointok környezeti változóval (futáskor felülírhatod)
# ENV FM_API_BASE=https://api.fm-track.com
# ENV EVENTS_BASE=http://host.docker.internal:9877/api

# Indítás
CMD ["streamlit", "run", "app.py", "--server.headless=true"]
