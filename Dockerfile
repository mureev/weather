# syntax=docker/dockerfile:1

# Two stages, so that nothing used to *build* the environment can end up in the
# thing that runs it. Today that is only pip's working files; the reason it is
# worth the four extra lines is the day a dependency stops shipping a wheel and
# needs gcc -- at which point the compiler lands in the builder and never
# reaches the image that faces the internet. Structuring for that in advance
# costs nothing; retrofitting it during an outage does not.
FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# A venv rather than the system site-packages, purely so the next stage can
# copy one self-contained directory instead of picking through /usr/local.
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Exactly the versions CI tested, hash-checked, and nothing they did not pull
# in. `requirements.txt` says what the app needs; `requirements.lock` is what
# it gets. Regenerate the lock with the command at its top and read its diff
# like code: that is where a new transitive dependency shows itself.
COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes --no-deps -r requirements.lock


FROM python:3.12-slim

# lxml ships manylinux wheels for both amd64 and arm64, so this builds on a
# Raspberry Pi as readily as on the VPS. If a future dependency ever forces a
# source build, that is the moment to check the wheel situation *before*
# deploying rather than discovering it mid-deploy.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/venv/bin:$PATH" \
    TZ=Europe/Moscow

COPY --from=build /venv /venv

WORKDIR /app
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
# should ever claim. The forecast answers 503 when no source does, so wiring
# that here would restart the container whenever the weather sites have a bad
# hour, which no restart can fix.
HEALTHCHECK --interval=60s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=4).status==200 else 1)"

# --limit-concurrency bounds memory under a burst: each in-flight request can
# hold three parsed documents, and lxml trees are not small. Refusing the 65th
# concurrent request with a 503 is a better failure than the OOM killer taking
# the container down for everyone.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header", \
     "--limit-concurrency", "64", "--timeout-keep-alive", "20"]
