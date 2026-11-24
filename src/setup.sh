#!/usr/bin/env bash
# Create .venv and install dependencies. Safe to re-run. Choose an interpreter with PYTHON=python3.12 ./setup.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null; then
    echo "오류: $PYTHON 을 찾을 수 없습니다." >&2
    exit 1
fi
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "오류: Python 3.10 이상이 필요합니다. (현재: $("$PYTHON" --version 2>&1))" >&2
    exit 1
fi

[ -x .venv/bin/python ] || "$PYTHON" -m venv .venv
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements.txt
.venv/bin/python -c 'import pymupdf; from mcp.server.fastmcp import FastMCP'

printf -v py '%q' "$PWD/.venv/bin/python"
printf -v launcher '%q' "$PWD/run.py"
printf -v server '%q' "$PWD/server.py"
cat <<EOF
설치 완료.

PDF를 사용할 프로젝트 폴더에서 실행하세요:
  $py $launcher

직접 등록하려면:
  mkdir -p rag
  claude mcp add pdf-rag --transport stdio --scope local -e PDF_RAG_DIR="\$PWD/rag" -- $py $server
EOF
