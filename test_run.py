"""Run with: python -m unittest test_run"""
import json
import tempfile
import unittest
from pathlib import Path

from run import CODEX_CONFIG, JSON_CLIENTS, add_to_config

CMD = ["/bin/uvx", "--from", "git+https://example.com/x", "pdf-rag-server"]


class AddToConfig(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name)

    def test_json_clients_keep_existing_settings_and_do_not_duplicate(self):
        for client, (rel, key, extra) in JSON_CLIENTS.items():
            path = self.project / rel
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"theme": "dark", key: {"other": {"command": "x"}}}))
            self.assertTrue(add_to_config(client, self.project, "/pdfs", CMD))
            data = json.loads(path.read_text())
            self.assertEqual(data["theme"], "dark")
            self.assertEqual(data[key]["other"], {"command": "x"})
            self.assertEqual(data[key]["pdf-rag"], {**extra, "command": CMD[0], "args": CMD[1:], "env": {"PDF_RAG_DIR": "/pdfs"}})
            before = path.read_text()
            self.assertFalse(add_to_config(client, self.project, "/other", CMD))
            self.assertEqual(path.read_text(), before)

    def test_unparseable_config_is_left_untouched(self):
        path = self.project / JSON_CLIENTS["vscode"][0]
        path.parent.mkdir(parents=True)
        original = '{ // comment\n "servers": {} }'
        path.write_text(original)
        with self.assertRaises(ValueError):
            add_to_config("vscode", self.project, "/pdfs", CMD)
        self.assertEqual(path.read_text(), original)

    def test_codex_appends_valid_toml_once(self):
        path = self.project / CODEX_CONFIG
        path.parent.mkdir(parents=True)
        path.write_text('model = "x"\n')
        folder = '/pdfs/한글 "q"'
        self.assertTrue(add_to_config("codex", self.project, folder, CMD))
        self.assertFalse(add_to_config("codex", self.project, folder, CMD))
        try:
            import tomllib
        except ImportError:  # Python 3.10
            return
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "x")
        self.assertEqual(data["mcp_servers"]["pdf-rag"]["command"], CMD[0])
        self.assertEqual(data["mcp_servers"]["pdf-rag"]["env"]["PDF_RAG_DIR"], folder)


if __name__ == "__main__":
    unittest.main()
