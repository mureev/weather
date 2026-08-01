# syntax=docker/dockerfile:1
FROM python:3.12-slim

# lxml ships manylinux wheels for both amd64 and arm64, so this builds on a
# Raspberry Pi as readily as on the VPS. If a future dependency ever forces a
# source build, that is the moment to check the wheel situation *before*
# deploying rather than discovering it mid-deploy.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Moscow

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/

# Baked in so the running container can say what it is. Without this the only
# way to know whether a deploy landed is to squint at the UI and guess.
ARG APP_BUILD=dev
ARG APP_BUILT_AT=
ENV APP_BUILD=$APP_BUILD APP_BUILT_AT=$APP_BUILT_AT

# Nothing here needs root, and the container reaches out to the internet.
RUN useradd --system --uid 10001 --create-home yw && chown -R yw:yw /app
USER yw

EXPOSE 8080

# /healthz says only that the process is up -- which is all a liveness probe
# should ever claim. /api/health is the opinionated one, and it deliberately
# returns 503 when the data is bad, so wiring it here would restart the
# container every time Yandex has a wobble.
HEALTHCHECK --interval=60s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=4).status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
