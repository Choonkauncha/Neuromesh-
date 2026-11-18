"""Deterministic, path-confined tools. Identical definitions for every condition."""
import json, os, re, shutil, subprocess, sys
from pathlib import Path

LIST = {"type": "function", "function": {"name": "list_files", "description": "List available input files.", "parameters": {"type": "object", "properties": {}}}}
READ = {"type": "function", "function": {"name": "read_file", "description": "Read an input file (UTF-8 text).", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}
SEARCH = {"type": "function", "function": {"name": "search_text", "description": "Regex search across available files; returns file:line matches.", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}}, "required": ["pattern"]}}}
TESTS = {"type": "function", "function": {"name": "run_tests", "description": "Run the repository's unit tests; returns output.", "parameters": {"type": "object", "properties": {}}}}
WRITE = {"type": "function", "function": {"name": "write_file", "description": "Overwrite a file under repo/ with new content.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}}

MAX_READ = 20000


class ToolBox:
    def __init__(self, inputs_dir, workdir, visible=None, allow_tests=False, allow_write=False):
        self.src = Path(inputs_dir)
        self.root = Path(workdir) / "inputs"
        if not self.root.exists():
            shutil.copytree(self.src, self.root, ignore=shutil.ignore_patterns("__pycache__"))
        # Evidence quotes are checked against this pristine snapshot, so edits made by
        # write_file cannot change what counts as a verbatim quote of the original inputs.
        self.pristine = Path(workdir) / "pristine"
        if not self.pristine.exists():
            shutil.copytree(self.src, self.pristine, ignore=shutil.ignore_patterns("__pycache__"))
        self.visible_filter = set(visible) if visible else None
        self.allow_tests, self.allow_write = allow_tests, allow_write
        self.calls = []
        self.tool_outputs = {}  # 'tool:<name>' -> concatenated outputs, quotable as evidence

    def visible_files(self):
        out = []
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                rel = p.relative_to(self.root).as_posix()
                if self.visible_filter is None or rel in self.visible_filter:
                    out.append(rel)
        return out

    def schemas(self, readonly=False):
        s = [LIST, READ, SEARCH]
        if self.allow_tests: s.append(TESTS)
        if self.allow_write and not readonly: s.append(WRITE)
        return s

    def _resolve(self, rel):
        p = (self.root / rel).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise PermissionError("path escapes the input directory")
        return p

    def call(self, name, args):
        try:
            result = getattr(self, "_" + name)(**(args or {}))
        except Exception as ex:  # tool errors are observations, not crashes
            result = f"ERROR: {type(ex).__name__}: {ex}"
        self.calls.append({"name": name, "args": args, "result_chars": len(result)})
        if name == "run_tests":
            self.tool_outputs["tool:run_tests"] = self.tool_outputs.get("tool:run_tests", "") + result
        return result

    def _list_files(self):
        return "\n".join(self.visible_files()) or "(no files)"

    def _read_file(self, path):
        rel = Path(path).as_posix()
        if rel not in self.visible_files():
            raise FileNotFoundError(f"{path} is not an available file (use list_files)")
        text = self._resolve(rel).read_text()
        return text if len(text) <= MAX_READ else text[:MAX_READ] + "\n...[truncated]"

    def _search_text(self, pattern):
        rx, hits = re.compile(pattern, re.I), []
        for rel in self.visible_files():
            for n, line in enumerate(self._resolve(rel).read_text().splitlines(), 1):
                if rx.search(line): hits.append(f"{rel}:{n}: {line.strip()[:200]}")
        return "\n".join(hits[:50]) or "(no matches)"

    def _write_file(self, path, content):
        if not self.allow_write: raise PermissionError("write_file is not available")
        rel = Path(path).as_posix()
        if not rel.startswith("repo/"): raise PermissionError("writes are limited to repo/")
        p = self._resolve(rel)
        repo = (self.root / "repo").resolve()
        if repo not in p.parents:  # catches repo/../x style traversal after resolution
            raise PermissionError("writes are limited to repo/")
        if not p.parent.exists(): raise FileNotFoundError("parent directory does not exist")
        p.write_text(content)
        return f"wrote {len(content)} chars to {rel}"

    def _run_tests(self):
        if not self.allow_tests: raise PermissionError("run_tests is not available")
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                           cwd=self.root / "repo", capture_output=True, text=True, timeout=30, env=env)
        out = (r.stdout + r.stderr)[-4000:]
        return f"exit={r.returncode}\n{out}"
