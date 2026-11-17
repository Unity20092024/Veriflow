FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-core.txt ./
ARG INSTALL_COMPOSIO=false
RUN --mount=type=secret,id=build_ca,target=/run/secrets/build_ca \
    set -e; \
    if [ -s /run/secrets/build_ca ]; then cp /run/secrets/build_ca /usr/local/share/ca-certificates/veriflow-build-ca.crt; update-ca-certificates; fi; \
    if [ "$INSTALL_COMPOSIO" = true ]; then PIP_CERT=/etc/ssl/certs/ca-certificates.crt pip install --no-cache-dir -r requirements.txt; else PIP_CERT=/etc/ssl/certs/ca-certificates.crt pip install --no-cache-dir -r requirements-core.txt; fi; \
    rm -f /usr/local/share/ca-certificates/veriflow-build-ca.crt; update-ca-certificates --fresh; \
    useradd --uid 10001 --create-home veriflow; mkdir -p /var/lib/veriflow/exports; chown -R veriflow:veriflow /var/lib/veriflow; chmod 700 /var/lib/veriflow/exports
COPY --chown=veriflow:veriflow veriflow ./veriflow
COPY --chown=veriflow:veriflow data ./data
USER 10001:10001
ENV VERIFLOW_ARTIFACT_DIR=/var/lib/veriflow/exports
EXPOSE 8080
CMD ["python","-m","veriflow","admin"]
