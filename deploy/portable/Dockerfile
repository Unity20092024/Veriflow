FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUPABASE_PROJECT_REF=qrejfpeclncrevmepgzx \
    SUPABASE_SSL_ROOT_CERT=/app/certificates/supabase-ca.crt \
    APIFY_PAID_RUNS_ENABLED=false \
    APIFY_MAX_RUN_USD=0 \
    APIFY_ROLLING_24H_BUDGET_USD=0

WORKDIR /app
COPY deploy/portable/requirements.txt /tmp/veriflow-core-requirements.txt
RUN pip install --no-cache-dir -r /tmp/veriflow-core-requirements.txt

COPY --chown=10001:10001 veriflow/ ./veriflow/
COPY --chown=10001:10001 data/sources.json data/source-capabilities.json data/collection-strategy.json data/first-collection-candidate.json ./data/
COPY --chown=10001:10001 certificates/supabase-ca.crt ./certificates/supabase-ca.crt

USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python", "-m", "veriflow"]
# Building or running the default image neither connects nor starts collection.
CMD ["--help"]
