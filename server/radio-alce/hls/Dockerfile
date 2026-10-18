FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /app/requirements.txt
RUN --mount=type=secret,id=proxy_ca PIP_CERT=/run/secrets/proxy_ca sh -c 'if [ ! -f "$PIP_CERT" ]; then unset PIP_CERT; fi; pip install --no-cache-dir -r /app/requirements.txt'
WORKDIR /app
COPY pipeline.py health.py ./
RUN chmod 644 /app/*.py && mkdir /output && chown 65534:65534 /output
USER 65534:65534
CMD ["python", "-u", "pipeline.py"]
