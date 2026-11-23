"""Start Claude Code in the current project, registering pdf-rag first if it is missing."""
import json
import os
import re
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

SERVER = Path(__file__).resolve().with_name("server.py")
# client: (project config file, servers key, extra fields the client requires)
JSON_CLIENTS = {
    "cursor": (".cursor/mcp.json", "mcpServers", {"type": "stdio"}),
    "vscode": (".vscode/mcp.json", "servers", {"type": "stdio"}),
    "gemini": (".gemini/settings.json", "mcpServers", {}),
}
CODEX_CONFIG = ".codex/config.toml"


def server_command() -> list[str]:
    """Use the git source this launcher was installed from, since uvx's own paths are temporary."""
    try:
        origin = json.loads(distribution("pdf-rag-mcp").read_text("direct_url.json"))
        if "vcs_info" in origin:
            return ["uvx", "--from", f"git+{origin['url']}", "pdf-rag-server"]
    except (PackageNotFoundError, TypeError):  # TypeError: not installed from a URL
        pass
    return [sys.executable, str(SERVER)]


def pick_folder() -> str:
    """Return the folder chosen in a native dialog, or "" on cancel or when no GUI is available."""
    try:
        from tkinter import TclError, Tk, filedialog
    except ImportError:
        return ""
    try:
        root = Tk()
    except TclError:
        return ""
    root.withdraw()
    folder = filedialog.askdirectory(title="PDF 폴더 선택 (취소하면 ./rag 사용)", initialdir=os.getcwd(), mustexist=True)
    root.destroy()
    return folder or ""


def add_to_config(client: str, project: Path, folder: str, command: list[str]) -> bool:
    """Merge pdf-rag into the client's project config. Returns False if it is already there."""
    rel = CODEX_CONFIG if client == "codex" else JSON_CLIENTS[client][0]
    path = (project / rel).resolve()
    text = path.read_text(encoding="utf-8") if path.exists() else ""

    if client == "codex":
        if re.search(r'^\s*\[mcp_servers\."?pdf-rag"?\]', text, re.M):
            return False
        # JSON strings and arrays are valid TOML basic strings and arrays.
        block = (
            f"[mcp_servers.pdf-rag]\ncommand = {json.dumps(command[0], ensure_ascii=False)}\n"
            f"args = {json.dumps(command[1:], ensure_ascii=False)}\n\n"
            f"[mcp_servers.pdf-rag.env]\nPDF_RAG_DIR = {json.dumps(folder, ensure_ascii=False)}\n"
        )
        new_text = f"{text.rstrip()}\n\n{block}" if text.strip() else block
    else:
        _, key, extra = JSON_CLIENTS[client]
        data = json.loads(text.strip() or "{}")  # Comments raise here, so the file is left untouched.
        servers = data.setdefault(key, {}) if isinstance(data, dict) else None
        if not isinstance(servers, dict):
            raise ValueError(f"unexpected structure in {path}")
        if "pdf-rag" in servers:
            return False
        servers["pdf-rag"] = {**extra, "command": command[0], "args": command[1:], "env": {"PDF_RAG_DIR": folder}}
        new_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    if path.exists():
        shutil.copymode(path, tmp)
    os.replace(tmp, path)  # Atomic, so a crash cannot leave a half-written config.
    return True


def add_client() -> None:
    clients = [*JSON_CLIENTS, "codex"]
    if len(sys.argv) != 3 or sys.argv[1] not in clients:
        sys.exit(f"사용법: pdf-rag-add <{'|'.join(clients)}> <PDF 폴더>")
    client, folder = sys.argv[1], str(Path(sys.argv[2]).resolve())
    command = server_command()
    # Absolute path: GUI editors often start without the shell's PATH.
    command[0] = shutil.which(command[0]) or command[0]
    try:
        added = add_to_config(client, Path.cwd(), folder, command)
    except (ValueError, OSError) as e:
        sys.exit(f"오류: 설정 파일을 변경하지 않았습니다. 직접 확인하세요. ({e})")
    if not added:
        print(f"{client}: 업데이트 완료. 기존 PDF 폴더와 설정은 유지합니다.")
        return
    # Created only on first registration, so an update never adds a stray folder.
    if not Path(folder).exists():
        Path(folder).mkdir(parents=True)
        (Path(folder) / ".gitignore").write_text("*\n", encoding="utf-8")
    print(f"{client}: 등록 완료. PDF 폴더: {folder}")


def main() -> None:
    found =subprocess.run(["claude", "mcp", "get", "pdf-rag"], capture_output=True, stdin=subprocess.DEVNULL)
    if found.returncode != 0:
        folder = Path(pick_folder() or Path.cwd() / "rag").resolve()
        folder.mkdir(parents=True, exist_ok=True)
        # Name goes before -e because -e is variadic and would swallow it.
        subprocess.run(
            ["claude", "mcp", "add", "pdf-rag", "--transport", "stdio", "--scope", "local",
             "-e", f"PDF_RAG_DIR={folder}", "--", *server_command()],
            check=True,
            stdout=sys.stderr,
        )
    os.execvp("claude", ["claude", *sys.argv[1:]])


if __name__ == "__main__":
    main()
