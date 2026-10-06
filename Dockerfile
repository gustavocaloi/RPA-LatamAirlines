FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV INPUT_CSV=/data/voos.csv
ENV OUTPUT_CSV=/data/resultado_voos.csv
ENV SUMMARY_OUTPUT=/data/resumo_resultado.txt
ENV PROFILE_DIR=/data/playwright-profile
ENV PLAYWRIGHT_BROWSER_CHANNEL=
ENV INTERVAL_SECONDS=3600
ENV PYTHON_BIN=python

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY README.md ./
COPY scripts ./scripts
COPY voos.csv ./voos.csv

RUN mkdir -p /data
RUN chmod +x /app/scripts/*.sh

CMD ["bash", "/app/scripts/run_hourly.sh"]
