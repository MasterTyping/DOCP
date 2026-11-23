#!/bin/sh
# Register pdf-rag in the current project: curl -fsSL https://raw.githubusercontent.com/MasterTyping/DOCP/main/install.sh | sh
set -eu

# Wrapped in main so a truncated download cannot run half a script.
main() {
    command -v claude >/dev/null || {
        echo "오류: Claude Code(claude)를 찾을 수 없습니다. 먼저 설치하세요: https://code.claude.com" >&2
        exit 1
    }

    if claude mcp get pdf-rag >/dev/null 2>&1 </dev/null; then
        echo "pdf-rag가 이 프로젝트에 이미 등록되어 있습니다. 확인: claude mcp get pdf-rag"
        exit 0
    fi

    if ! command -v uvx >/dev/null; then
        command -v curl >/dev/null || {
            echo "오류: uv 설치에 curl이 필요합니다." >&2
            exit 1
        }
        echo "uv를 설치합니다..."
        curl -fsSL https://astral.sh/uv/install.sh | sh
        PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
        command -v uvx >/dev/null || {
            echo "오류: uv 설치 후에도 uvx를 찾을 수 없습니다." >&2
            exit 1
        }
    fi

    folder="$PWD/rag"
    mkdir -p "$folder"
    # PDFs can be private, so keep them out of the host project's git by default.
    [ -e "$folder/.gitignore" ] || printf '*\n' >"$folder/.gitignore"

    # Absolute uvx path: Claude Code may start without the PATH a fresh uv install just added.
    claude mcp add pdf-rag --transport stdio --scope local -e "PDF_RAG_DIR=$folder" -- \
        "$(command -v uvx)" --from git+https://github.com/MasterTyping/DOCP pdf-rag-server </dev/null

    echo
    echo "등록 완료. PDF를 $folder 에 넣고 Claude Code를 다시 시작하세요."
}

main
