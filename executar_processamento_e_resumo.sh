#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd)"
exec "${SCRIPT_DIR}/scripts/executar_processamento_e_resumo.sh" "$@"
