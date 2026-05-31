FROM python:3.14-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97

ARG BUILD_DATE=unknown
ARG VCS_REF=unknown

LABEL org.opencontainers.image.title="paga-eval" \
      org.opencontainers.image.description="Auditable child-reading tutor evaluation service" \
      org.opencontainers.image.version="0.4.0" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}"

WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir --constraint constraints/service-py312.txt ".[service]"

RUN useradd --create-home --uid 10001 paga
RUN mkdir -p /data && chown paga:paga /data
USER paga

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-m", "paga.healthcheck"]
CMD ["uvicorn", "paga.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
