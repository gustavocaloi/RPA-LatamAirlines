#!/usr/bin/env bash
set -euo pipefail

INTERVAL_SECONDS="${INTERVAL_SECONDS:-3600}"
INPUT_CSV="${INPUT_CSV:-/data/voos.csv}"
OUTPUT_CSV="${OUTPUT_CSV:-/data/resultado_voos.csv}"
SUMMARY_OUTPUT="${SUMMARY_OUTPUT:-/data/resumo_resultado.txt}"
PROFILE_DIR="${PROFILE_DIR:-/data/playwright-profile}"
BROWSER_CHANNEL="${PLAYWRIGHT_BROWSER_CHANNEL:-}"
PYTHON_BIN="${PYTHON_BIN:-python}"
PROJECT_DIR="${PROJECT_DIR:-/app}"
RUNNER_SCRIPT="${PROJECT_DIR}/scripts/executar_processamento_e_resumo.sh"

mkdir -p "$(dirname "$OUTPUT_CSV")" "$(dirname "$SUMMARY_OUTPUT")" "$PROFILE_DIR"

if [[ ! -f "$INPUT_CSV" ]]; then
  echo "[runner] arquivo de entrada nao encontrado: $INPUT_CSV"
  exit 1
fi

if [[ ! -x "$RUNNER_SCRIPT" ]]; then
  echo "[runner] script runner nao encontrado: $RUNNER_SCRIPT"
  exit 1
fi

while true; do
  STARTED_AT="$(date '+%Y-%m-%d %H:%M:%S %z')"
  echo "[runner] iniciando processamento em $STARTED_AT"

  if env \
    INPUT_CSV="$INPUT_CSV" \
    OUTPUT_CSV="$OUTPUT_CSV" \
    SUMMARY_OUTPUT="$SUMMARY_OUTPUT" \
    PROFILE_DIR="$PROFILE_DIR" \
    PLAYWRIGHT_BROWSER_CHANNEL="$BROWSER_CHANNEL" \
    PYTHON_BIN="$PYTHON_BIN" \
    "$RUNNER_SCRIPT"; then
    echo "[runner] processamento concluido"
  else
    echo "[runner] processamento falhou; nova tentativa em ${INTERVAL_SECONDS}s"
  fi

  sleep "$INTERVAL_SECONDS"
done
