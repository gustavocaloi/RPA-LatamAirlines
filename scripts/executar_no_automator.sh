#!/usr/bin/env bash

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${SCRIPT_PATH}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
RUNNER_SCRIPT="${PROJECT_DIR}/scripts/executar_processamento_e_resumo.sh"
LOG_DIR="${PROJECT_DIR}/artifacts"
LOG_FILE="${LOG_DIR}/automator-run.log"

mkdir -p "${LOG_DIR}"

exec >> "${LOG_FILE}" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] Inicio da execucao via Automator"

if [[ ! -x "${RUNNER_SCRIPT}" ]]; then
  echo "[automator] Script runner nao encontrado em ${RUNNER_SCRIPT}"
  exit 1
fi

cd "${PROJECT_DIR}"

echo "[automator] Executando: ${RUNNER_SCRIPT}"
"${RUNNER_SCRIPT}"
STATUS=$?

echo "[automator] Finalizado com status ${STATUS}"
echo "[$(date '+%Y-%m-%d %H:%M:%S %z')] Fim da execucao via Automator"
