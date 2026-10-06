#!/usr/bin/env bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${SCRIPT_PATH}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
PROCESS_SCRIPT="${PROJECT_DIR}/scripts/processar_voos_latam.py"
SUMMARY_SCRIPT="${PROJECT_DIR}/scripts/resumir_resultado.py"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_CMD="${PYTHON_BIN}"
elif [[ -x "${VENV_PYTHON}" ]]; then
  PYTHON_CMD="${VENV_PYTHON}"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_CMD="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_CMD="$(command -v python)"
else
  echo "[runner] Nenhum interpretador Python encontrado."
  exit 1
fi

if [[ ! -f "${PROCESS_SCRIPT}" ]]; then
  echo "[runner] Script de processamento nao encontrado em ${PROCESS_SCRIPT}"
  exit 1
fi

if [[ ! -f "${SUMMARY_SCRIPT}" ]]; then
  echo "[runner] Script de resumo nao encontrado em ${SUMMARY_SCRIPT}"
  exit 1
fi

cd "${PROJECT_DIR}"

INPUT_CSV_PATH="${INPUT_CSV:-${PROJECT_DIR}/voos.csv}"
OUTPUT_CSV_PATH="${OUTPUT_CSV:-${PROJECT_DIR}/resultado_voos.csv}"
SUMMARY_OUTPUT_PATH="${SUMMARY_OUTPUT:-${PROJECT_DIR}/resumo_resultado.txt}"
PROFILE_DIR_PATH="${PROFILE_DIR:-${PROJECT_DIR}/.playwright-profile}"
BROWSER_CHANNEL_VALUE="${PLAYWRIGHT_BROWSER_CHANNEL:-chrome}"
HEADED_VALUE="${AUTOMATOR_HEADED:-0}"

PROCESS_CMD=(
  "${PYTHON_CMD}"
  "${PROCESS_SCRIPT}"
  --input "${INPUT_CSV_PATH}"
  --output "${OUTPUT_CSV_PATH}"
  --profile-dir "${PROFILE_DIR_PATH}"
)

if [[ -n "${BROWSER_CHANNEL_VALUE}" ]]; then
  PROCESS_CMD+=(--browser-channel "${BROWSER_CHANNEL_VALUE}")
fi

if [[ "${HEADED_VALUE}" == "1" ]]; then
  PROCESS_CMD+=(--headed)
fi

SUMMARY_CMD=(
  "${PYTHON_CMD}"
  "${SUMMARY_SCRIPT}"
  --input "${OUTPUT_CSV_PATH}"
  --output "${SUMMARY_OUTPUT_PATH}"
)

echo "[runner] Executando processamento: ${PROCESS_CMD[*]}"
"${PROCESS_CMD[@]}"

echo "[runner] Executando resumo: ${SUMMARY_CMD[*]}"
"${SUMMARY_CMD[@]}"
