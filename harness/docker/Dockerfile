FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends bash curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir aiohttp==3.14.5 pydantic==2.12.5
WORKDIR /workspace
CMD ["sleep", "infinity"]
