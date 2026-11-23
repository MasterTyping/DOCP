"""Start Claude Code in the current project, registering pdf-rag first if it is missing."""
import json
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

SERVER = Path(__file__).resolve().with_name("server.py")


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


def main() -> None:
    found = subprocess.run(["claude", "mcp", "get", "pdf-rag"], capture_output=True, stdin=subprocess.DEVNULL)
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
