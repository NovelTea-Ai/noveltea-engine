"""
Nemotron Bash Agent
===================

A natural-language Bash agent built on the NVIDIA Nemotron models, following the
architecture from NVIDIA's "build a Bash agent" tutorial:

  1. A `Bash` class  — a thin wrapper over subprocess that enforces a command
     allowlist and tracks the working directory across calls.
  2. A `NemotronAgent` — drives the model, exposes `exec_bash_command` as a tool,
     and loops on tool calls until the model yields control back to the user.

Safety model (three independent layers):
  - Allowlist:     only known-safe commands may run at all.
  - Denylist:      destructive verbs are rejected even if somehow allowlisted.
  - Confirmation:  a human approves each command before it executes.

Default model/endpoint pair:
    nvidia/nemotron-3-ultra-550b-a55b  @  https://integrate.api.nvidia.com/v1

Note on model IDs: the model ID must match the provider. NVIDIA's own endpoint
serves "nvidia/nemotron-3-ultra-550b-a55b"; OpenRouter additionally offers a
free tier under "nvidia/nemotron-3-ultra-550b-a55b:free". The ":free" suffix is
OpenRouter-only and 404s against NVIDIA (verified live).
"""

import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

DEFAULT_ENDPOINT = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"

# Nemotron reasoning models emit their chain-of-thought in <think> blocks.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_thinking(text: str) -> str:
    """Remove <think>…</think> reasoning blocks from a model response."""
    if not text:
        return ""
    cleaned = _THINK_RE.sub("", text)
    # An unterminated block means the response was cut off mid-thought.
    if "<think>" in cleaned:
        cleaned = cleaned.split("<think>")[0]
    return cleaned.strip()


def _shell_executable() -> Optional[str]:
    """
    Resolve a bash executable. The agent's commands and quoting are POSIX, so on
    Windows we look for Git Bash rather than falling back to cmd.exe.
    Returns None to let subprocess use the platform default.
    """
    if os.name != "nt":
        return "/bin/bash"

    found = shutil.which("bash")
    if found:
        return found

    for candidate in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    ):
        if Path(candidate).exists():
            return candidate

    return None


@dataclass
class CommandResult:
    """Result of executing a bash command."""
    stdout: str
    stderr: str
    cwd: str
    exit_code: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "cwd": self.cwd,
            "exit_code": self.exit_code,
        }


class Bash:
    """
    Executes bash commands under an allowlist, tracking the working directory
    so that `cd` persists across separate calls.
    """

    DEFAULT_ALLOWED = {
        # Inspection / navigation
        "ls", "cat", "head", "tail", "grep", "find", "pwd", "cd", "stat",
        "file", "wc", "sort", "uniq", "diff", "tree", "realpath", "basename",
        "dirname",
        # Creation (non-destructive)
        "mkdir", "touch", "cp",
        # Text processing
        "echo", "sed", "awk", "cut", "tr", "printf",
        # System info
        "uname", "whoami", "date", "df", "du", "free", "uptime", "hostname",
        "ps", "env", "which",
        # Dev tooling
        "git", "python", "python3", "pip", "node", "npm", "jq",
    }

    # Rejected even if an allowlist entry would otherwise permit them. This is a
    # backstop against e.g. `find -delete` or a widened allowlist.
    DENIED_PATTERNS = (
        r"\brm\b", r"\brmdir\b", r"\bmv\b", r"\bdd\b", r"\bmkfs\b",
        r"\bsudo\b", r"\bsu\b", r"\bchmod\b", r"\bchown\b", r"\bkill\b",
        r"\bkillall\b", r"\bshutdown\b", r"\breboot\b", r"\bformat\b",
        r"\bdel\b", r"-delete\b", r"--delete\b", r">\s*/dev/sd",
    )

    # Operators that chain a second command; each segment is allowlist-checked
    # so `ls && rm -rf /` cannot slip through on the strength of `ls`.
    _SPLIT_RE = re.compile(r"\|\||&&|\||;|\n")

    def __init__(self, cwd: Optional[str] = None, allowed_commands: Optional[List[str]] = None):
        self.cwd = str(Path(cwd).resolve()) if cwd else str(Path.cwd())
        self.allowed_commands = set(allowed_commands or self.DEFAULT_ALLOWED)

    def exec_bash_command(self, cmd: str) -> CommandResult:
        """Validate `cmd` against the safety layers, then run it."""
        if not cmd or not cmd.strip():
            return CommandResult("", "No command was provided.", self.cwd, 1)

        denied = self._denied_reason(cmd)
        if denied:
            return CommandResult("", denied, self.cwd, 1)

        not_allowed = self._disallowed_commands(cmd)
        if not_allowed:
            return CommandResult(
                "",
                f"Command(s) not in the allowlist: {', '.join(sorted(not_allowed))}. "
                f"Allowed: {', '.join(sorted(self.allowed_commands))}",
                self.cwd,
                1,
            )

        return self._run(cmd)

    def _denied_reason(self, cmd: str) -> Optional[str]:
        for pattern in self.DENIED_PATTERNS:
            if re.search(pattern, cmd):
                return (
                    f"Refused: this command matches a destructive pattern "
                    f"({pattern}) and is blocked for safety."
                )
        return None

    def _disallowed_commands(self, cmd: str) -> List[str]:
        """Return the leading binary of each chained segment that isn't allowed."""
        bad = []
        for segment in self._SPLIT_RE.split(cmd):
            segment = segment.strip()
            if not segment:
                continue
            name = self._leading_binary(segment)
            if name and name not in self.allowed_commands:
                bad.append(name)
        return bad

    @staticmethod
    def _leading_binary(segment: str) -> Optional[str]:
        """Extract the command name from a segment, skipping VAR=value prefixes."""
        try:
            import shlex
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()

        for token in tokens:
            if "=" in token and not token.startswith(("-", "/", ".")):
                continue  # environment assignment, not the command
            return Path(token).name
        return None

    def _run(self, cmd: str) -> CommandResult:
        try:
            # Git Bash's `pwd` prints a POSIX path (/c/Users/...) that Windows
            # cannot reuse as a cwd; `pwd -W` prints C:/Users/... instead.
            pwd_cmd = "pwd -W" if os.name == "nt" else "pwd"
            # __RC__ carries the command's real exit status — the trailing pwd
            # would otherwise mask it and every failure would look successful.
            wrapped = (
                f'cd "{self.cwd}" && {cmd}; __rc=$?; '
                f'echo __END__; {pwd_cmd}; echo "__RC__$__rc"'
            )

            shell_exe = _shell_executable()
            if shell_exe:
                # Invoke bash directly: with shell=True, Windows re-parses the
                # command line and mangles paths like "C:\Program Files\...".
                argv: Any = [shell_exe, "-c", wrapped]
                use_shell = False
            else:
                argv, use_shell = wrapped, True

            result = subprocess.run(
                argv,
                shell=use_shell,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            stdout, stderr, exit_code = result.stdout, result.stderr, result.returncode

            if "__RC__" in stdout:
                stdout, _, rc_text = stdout.rpartition("__RC__")
                try:
                    exit_code = int(rc_text.strip())
                except ValueError:
                    pass

            if "__END__" in stdout:
                head, _, tail = stdout.rpartition("__END__")
                stdout = head.strip()
                new_cwd = tail.strip()
                if new_cwd:
                    self.cwd = new_cwd

            if not stdout and not stderr and exit_code == 0:
                stdout = "Command executed successfully, without any output."

            return CommandResult(stdout, stderr, self.cwd, exit_code)

        except subprocess.TimeoutExpired:
            return CommandResult("", "Command timed out after 30 seconds.", self.cwd, 124)
        except FileNotFoundError:
            return CommandResult(
                "",
                "No bash shell found. On Windows, install Git for Windows (Git Bash).",
                self.cwd,
                127,
            )
        except Exception as e:  # noqa: BLE001 - surfaced to the model as an error
            return CommandResult("", f"Execution error: {e}", self.cwd, 1)

    def to_json_schema(self) -> Dict[str, Any]:
        """Tool-calling schema describing exec_bash_command to the model."""
        return {
            "type": "function",
            "function": {
                "name": "exec_bash_command",
                "description": (
                    "Execute a bash command and return its stdout, stderr, exit "
                    "code, and the resulting working directory. Only allowlisted, "
                    "non-destructive commands may be run."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {
                            "type": "string",
                            "description": "The bash command to execute.",
                        }
                    },
                    "required": ["cmd"],
                },
            },
        }


class FileTools:
    """
    Structured file access for the agent, confined to an explicit set of root
    directories. This is what makes Nemotron usable as an agent engine: prose
    edits go through write_file (whole-file replacement, snapshot-friendly)
    rather than in-place `sed -i` surgery.

    Every path is resolved and re-checked against the roots, so `..` traversal
    and symlinks cannot escape the workspace.
    """

    MAX_READ_BYTES = 400_000

    def __init__(self, roots: List[Path], read_only_roots: Optional[List[Path]] = None):
        self.roots = [Path(r).resolve() for r in roots]
        self.read_only_roots = [Path(r).resolve() for r in (read_only_roots or [])]

    def _resolve(self, raw: str) -> Path:
        """Resolve `raw` and confirm it sits inside an allowed root."""
        if not raw or not raw.strip():
            raise ValueError("No path was provided.")

        candidate = Path(raw.strip()).expanduser()
        if not candidate.is_absolute():
            candidate = self.roots[0] / candidate

        # resolve() collapses ".." and follows symlinks, so the containment
        # check below cannot be fooled by either.
        resolved = candidate.resolve()

        for root in self.roots:
            if resolved == root or root in resolved.parents:
                return resolved

        allowed = ", ".join(str(r) for r in self.roots)
        raise ValueError(f"Path is outside the workspace. Allowed roots: {allowed}")

    def _assert_writable(self, path: Path) -> None:
        for ro in self.read_only_roots:
            if path == ro or ro in path.parents:
                raise ValueError(f"'{path}' is in a read-only root and cannot be modified.")

    def read_file(self, path: str) -> Dict[str, Any]:
        try:
            target = self._resolve(path)
        except ValueError as e:
            return {"error": str(e)}
        if not target.exists():
            return {"error": f"File not found: {target}"}
        if target.is_dir():
            return {"error": f"'{target}' is a directory — use list_files."}

        size = target.stat().st_size
        if size > self.MAX_READ_BYTES:
            return {"error": f"File is {size} bytes, over the {self.MAX_READ_BYTES} limit."}

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {"error": f"Could not read file: {e}"}

        return {"path": str(target), "content": content, "bytes": size}

    def write_file(self, path: str, content: str) -> Dict[str, Any]:
        try:
            target = self._resolve(path)
            self._assert_writable(target)
        except ValueError as e:
            return {"error": str(e)}

        if content is None:
            return {"error": "No content was provided."}

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            existed = target.exists()
            previous = target.stat().st_size if existed else 0
            # Read the old content first so the caller can report line deltas —
            # write_file replaces the whole file, so "removed" is every old line.
            prev_lines = 0
            if existed:
                try:
                    prev_lines = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
                except OSError:
                    prev_lines = 0
            target.write_text(content, encoding="utf-8")
        except OSError as e:
            return {"error": f"Could not write file: {e}"}

        return {
            "path": str(target),
            "written": True,
            "created": not existed,
            "bytes": len(content.encode("utf-8")),
            "previous_bytes": previous,
            "added_lines": len(content.splitlines()),
            "removed_lines": prev_lines,
        }

    def list_files(self, path: str = "") -> Dict[str, Any]:
        try:
            target = self._resolve(path) if path else self.roots[0]
        except ValueError as e:
            return {"error": str(e)}
        if not target.exists():
            return {"error": f"Directory not found: {target}"}
        if not target.is_dir():
            return {"error": f"'{target}' is not a directory."}

        entries = []
        try:
            for child in sorted(target.iterdir()):
                if child.name.startswith("."):
                    continue
                entries.append({
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "bytes": child.stat().st_size if child.is_file() else None,
                })
        except OSError as e:
            return {"error": f"Could not list directory: {e}"}

        return {"path": str(target), "entries": entries}

    # -- search -----------------------------------------------------------

    # Directories that are never worth searching and would otherwise dominate
    # results. Mirrors aicoder.py's _DENY_DIR_NAMES.
    SKIP_DIRS = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        "build", "dist", "_backups", "accounts", ".claude",
    }
    # Files whose contents must never be returned, even inside an allowed root.
    SECRET_PATTERNS = (".env", "credentials", ".pem", ".key")

    MAX_MATCHES = 200

    def _is_secret(self, path: Path) -> bool:
        name = path.name.lower()
        return any(p in name for p in self.SECRET_PATTERNS)

    def _walk(self, root: Path):
        """Yield files under `root`, skipping vendor dirs and secret files."""
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d not in self.SKIP_DIRS and not d.startswith(".")
            ]
            for fn in filenames:
                p = Path(dirpath) / fn
                if not self._is_secret(p):
                    yield p

    def grep_files(self, pattern: str, path: str = "", glob: str = "") -> Dict[str, Any]:
        """Regex-search file contents, returning matching lines with line numbers."""
        if not pattern or not pattern.strip():
            return {"error": "No search pattern was provided."}
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return {"error": f"Invalid regular expression: {e}"}

        try:
            root = self._resolve(path) if path else self.roots[0]
        except ValueError as e:
            return {"error": str(e)}
        if not root.exists():
            return {"error": f"Path not found: {root}"}

        roots = [root] if root.is_dir() else [root.parent]
        targets = [root] if root.is_file() else None

        matches, scanned, truncated = [], 0, False
        for r in roots:
            for f in (targets if targets else self._walk(r)):
                if glob and not fnmatch.fnmatch(f.name, glob):
                    continue
                try:
                    if f.stat().st_size > self.MAX_READ_BYTES:
                        continue
                    text = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                scanned += 1
                for i, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        matches.append({
                            "file": str(f),
                            "line": i,
                            "text": line.strip()[:300],
                        })
                        if len(matches) >= self.MAX_MATCHES:
                            truncated = True
                            break
                if truncated:
                    break
            if truncated:
                break

        return {
            "pattern": pattern,
            "files_scanned": scanned,
            "match_count": len(matches),
            "truncated": truncated,
            "matches": matches,
        }

    def glob_files(self, pattern: str, path: str = "") -> Dict[str, Any]:
        """Find files by name pattern (e.g. '*.py', 'ch*.json')."""
        if not pattern or not pattern.strip():
            return {"error": "No glob pattern was provided."}
        try:
            root = self._resolve(path) if path else self.roots[0]
        except ValueError as e:
            return {"error": str(e)}
        if not root.is_dir():
            return {"error": f"'{root}' is not a directory."}

        found, truncated = [], False
        for f in self._walk(root):
            if fnmatch.fnmatch(f.name, pattern):
                found.append({"path": str(f), "bytes": f.stat().st_size})
                if len(found) >= self.MAX_MATCHES:
                    truncated = True
                    break
        return {
            "pattern": pattern,
            "count": len(found),
            "truncated": truncated,
            "files": found,
        }

    def edit_file(self, path: str, old_text: str, new_text: str) -> Dict[str, Any]:
        """
        Replace an exact substring in a file. Preferred over write_file for
        targeted changes: it cannot silently discard the rest of the file, and
        it refuses ambiguous matches rather than guessing which one you meant.
        """
        try:
            target = self._resolve(path)
            self._assert_writable(target)
        except ValueError as e:
            return {"error": str(e)}

        if not target.exists():
            return {"error": f"File not found: {target}"}
        if not old_text:
            return {"error": "old_text is required — use write_file to create a file."}

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {"error": f"Could not read file: {e}"}

        count = content.count(old_text)
        if count == 0:
            return {"error": "old_text was not found in the file — it must match exactly."}
        if count > 1:
            return {
                "error": f"old_text appears {count} times; it must be unique. "
                         f"Include surrounding lines to disambiguate."
            }

        try:
            target.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
        except OSError as e:
            return {"error": f"Could not write file: {e}"}

        # Line deltas so the UI can render this like a diff (green added / red
        # removed) rather than just saying "edited".
        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()
        return {
            "path": str(target),
            "edited": True,
            "replaced_bytes": len(old_text),
            "new_bytes": len(new_text),
            "added_lines": len(new_lines),
            "removed_lines": len(old_lines),
        }

    def to_json_schemas(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a UTF-8 text file from the workspace and return its full contents.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Path to the file."},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": (
                        "Write UTF-8 text to a file in the workspace, replacing its entire "
                        "contents. Read the file first so nothing is lost."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Path to the file."},
                            "content": {"type": "string", "description": "The complete new file contents."},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_files",
                    "description": "List the files and directories at a path in the workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Directory path. Defaults to the workspace root."},
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "grep_files",
                    "description": (
                        "Search file contents with a regular expression. Returns matching "
                        "lines with their file path and line number. Use this to find where "
                        "something is defined or used before reading whole files."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "Regular expression to search for."},
                            "path": {"type": "string", "description": "File or directory to search. Defaults to the workspace root."},
                            "glob": {"type": "string", "description": "Optional filename filter, e.g. '*.py'."},
                        },
                        "required": ["pattern"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "glob_files",
                    "description": (
                        "Find files by filename pattern (e.g. '*.py', 'ch*.json'). "
                        "Use this to locate files when you know the name but not the path."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "pattern": {"type": "string", "description": "Filename glob, e.g. '*.json'."},
                            "path": {"type": "string", "description": "Directory to search under. Defaults to the workspace root."},
                        },
                        "required": ["pattern"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": (
                        "Replace an exact, unique substring in a file. PREFER THIS over "
                        "write_file for changing part of an existing file — write_file "
                        "replaces the entire file and can lose content. old_text must match "
                        "exactly and appear exactly once."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Path to the file."},
                            "old_text": {"type": "string", "description": "Exact text to replace. Must be unique in the file."},
                            "new_text": {"type": "string", "description": "Replacement text."},
                        },
                        "required": ["path", "old_text", "new_text"],
                    },
                },
            },
        ]


SYSTEM_PROMPT = """/think
You are a helpful Bash assistant with the ability to execute commands in the shell.
You engage with users to help answer questions about bash commands, or execute their intent.
If user intent is unclear, keep engaging with them to figure out what they need and how to
best help them. If they ask questions that are not relevant to bash or computer use, decline
to answer politely.

When a command is executed, you will be given the output from that command and any errors.
Based on that, either take further actions or yield control to the user.

The bash interpreter's output and current working directory will be given to you every time
a command is executed. Take that into account for the next conversation.

If there was an error during execution, tell the user what that error was exactly.

You are only allowed to execute the following commands:
{allowed_commands}

**Never** attempt to execute a command not in this list. **Never** attempt to execute
dangerous commands like `rm`, `mv`, `rmdir`, `sudo`, etc. If the user asks you to do so,
politely refuse.

When you switch to new directories, always list files so you can get more context.
"""


# ── Qwen-native tool calling (text mode) ─────────────────────────────────────
# Local Qwen models behind Colibrì's gateway can't use the OpenAI `tools` field: the gateway has no
# tool syntax for Qwen3.6 and its fallback explains tools in GLM's format, which Qwen copied literally
# (a call named "{function-name}<arg_key>read_file…"). Qwen's own format is XML — the same one the
# gateway already renders for Qwen3.8 (transcribed from chat_template.jinja) — and the model follows it
# when the declaration goes in the system message and tool results come back as <tool_response> user
# turns, as plain ChatML text. Verified live on Qwen3.6-35B-A3B: a correct read_file call, then the answer.
QWEN_TOOL_PREAMBLE = (
    "\n\nIf you choose to call a function ONLY reply in the following format with NO suffix:\n\n"
    "<tool_call>\n<function=example_function_name>\n<parameter=example_parameter_1>\nvalue_1\n</parameter>\n"
    "<parameter=example_parameter_2>\nThis is the value for the second parameter\nthat can span\nmultiple lines\n"
    "</parameter>\n</function>\n</tool_call>\n\n<IMPORTANT>\nReminder:\n"
    "- Function calls MUST follow the specified format: an inner <function=...></function> block must be nested "
    "within <tool_call></tool_call> XML tags\n- Required parameters MUST be specified\n"
    "- You may provide optional reasoning for your function call in natural language BEFORE the function call, "
    "but NOT after\n- If there is no function call available, answer the question like normal with your current "
    "knowledge and do not tell the user about function calls\n</IMPORTANT>"
)
_QWEN_CALL_RE = re.compile(r"<tool_call>\s*<function=([^>\n]+)>\s*(.*?)</function>\s*</tool_call>", re.S)
_QWEN_PARAM_RE = re.compile(r"<parameter=([^>\n]+)>\n?(.*?)\n?</parameter>", re.S)
_QWEN_JSON_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)   # Hermes-style fallback


def _shorten(text: str, limit: int) -> str:
    text = (text or "").strip()
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    first = first if len(first) <= limit else first[: limit - 1].rstrip() + "…"
    return first


def qwen_tool_block(schemas: List[Dict[str, Any]], compact: bool = True) -> str:
    """The `# Tools` system section, in the layout of Qwen's template. compact=True shortens the
    descriptions: on a CPU every prompt token costs seconds (about 3-4 tokens/s measured), so the
    full descriptions (~770 tokens for the seven tools) are not worth their cost."""
    lines = ["# Tools\n\nYou have access to the following functions:\n\n<tools>"]
    for tool in schemas:
        t = json.loads(json.dumps(tool))
        if compact:
            fn = t.get("function", {})
            fn["description"] = _shorten(fn.get("description", ""), 120)
            for prop in ((fn.get("parameters") or {}).get("properties") or {}).values():
                if isinstance(prop, dict) and "description" in prop:
                    prop["description"] = _shorten(prop["description"], 70)
        lines.append("\n" + json.dumps(t, ensure_ascii=False, separators=(", ", ": ")))
    lines.append("\n</tools>")
    lines.append(QWEN_TOOL_PREAMBLE)
    return "".join(lines)


def parse_qwen_tool_calls(reply: str, schemas: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    """Qwen's XML tool calls -> OpenAI-style tool_calls, plus the reply text with the calls removed.
    Values come back as strings; where the declared schema says another type they are re-read as JSON."""
    declared: Dict[str, Dict[str, Any]] = {}
    for tool in schemas:
        fn = tool.get("function", tool)
        declared[fn.get("name")] = (fn.get("parameters") or {}).get("properties") or {}
    calls = []
    for m in _QWEN_CALL_RE.finditer(reply or ""):
        name, args = m.group(1).strip(), {}
        for key, raw in _QWEN_PARAM_RE.findall(m.group(2)):
            key = key.strip()
            kind = (declared.get(name, {}).get(key) or {}).get("type")
            if kind in (None, "string"):
                args[key] = raw
            else:
                try:
                    args[key] = json.loads(raw)
                except ValueError:
                    args[key] = raw
        calls.append({"id": f"call_{len(calls)}_{abs(hash(m.group(0))) % 10**8}", "type": "function",
                      "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}})
    text = _QWEN_CALL_RE.sub("", reply or "")
    if not calls:   # a model that slipped into JSON inside <tool_call>
        for m in _QWEN_JSON_CALL_RE.finditer(reply or ""):
            try:
                obj = json.loads(m.group(1))
                fn_name = obj.get("name")
                fn_args = obj.get("arguments", obj.get("parameters", {}))
                if fn_name:
                    calls.append({"id": f"call_{len(calls)}_{abs(hash(m.group(0))) % 10**8}", "type": "function",
                                  "function": {"name": fn_name,
                                               "arguments": fn_args if isinstance(fn_args, str) else json.dumps(fn_args)}})
            except ValueError:
                continue
        if calls:
            text = _QWEN_JSON_CALL_RE.sub("", text)
    return text.strip(), calls


def render_tool_result(result: Any) -> str:
    """A tool result as readable text: multi-line values (file contents) verbatim rather than as one
    escaped JSON line, so a small model can quote them back exactly (edit_file needs exact text)."""
    if not isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False)
    out = []
    for k, v in result.items():
        if isinstance(v, str) and "\n" in v:
            out.append(f"{k}:\n{v}")
        elif isinstance(v, str):
            out.append(f"{k}: {v}")
        else:
            out.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    return "\n".join(out)


class NemotronAgent:
    """
    Drives a Nemotron model as a Bash agent.

    `confirm` implements the human-in-the-loop step: it receives the proposed
    command and returns True to allow execution. When None, commands run without
    asking — only appropriate for non-interactive/server use where the allowlist
    and denylist are the sole protection.
    """

    MAX_TOOL_ROUNDS = 15
    # Retries for transient 429/5xx responses (NVIDIA sheds load with 503).
    MAX_RETRIES = 3

    def __init__(
        self,
        api_key: str,
        api_endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        cwd: Optional[str] = None,
        allowed_commands: Optional[List[str]] = None,
        confirm: Optional[Callable[[str], bool]] = None,
        temperature: float = 0.6,
        max_tokens: int = 2048,
        file_roots: Optional[List[Path]] = None,
        read_only_roots: Optional[List[Path]] = None,
        system_prompt: Optional[str] = None,
        use_tools: bool = True,
        tool_format: str = "openai",
    ):
        if not api_key:
            raise ValueError("An API key is required.")

        self.api_key = api_key
        self.api_endpoint = api_endpoint.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.confirm = confirm
        # False = plain chat: no tools are declared at all. For engines that can't do tool calls
        # (a local Colibrì model) — declaring tools there only gets the call syntax garbled.
        self.use_tools = use_tools
        # "openai": the API's own tools field. "qwen_xml": Qwen's native text format (see qwen_tool_block)
        self.tool_format = tool_format
        self._merge_idx: Optional[int] = None   # the user turn collecting this round's <tool_response>s

        self.bash = Bash(cwd=cwd, allowed_commands=allowed_commands)

        # File tools are opt-in: only enabled when the caller names the roots the
        # agent may touch. The plain bash CLI leaves this None.
        self.files: Optional[FileTools] = (
            FileTools(file_roots, read_only_roots) if file_roots else None
        )

        self.system_prompt = system_prompt or SYSTEM_PROMPT.format(
            allowed_commands=", ".join(sorted(self.bash.allowed_commands))
        )
        self.messages: List[Dict[str, Any]] = []
        self.reset_usage()

    def reset_usage(self) -> None:
        """Per-turn totals the UI shows as stats: tokens as the provider reported them, how many
        model calls the turn took, and the seconds spent waiting on the model (tool execution and
        everything else not counted — so tokens / model_seconds is the model's real speed)."""
        self.usage = {"prompt": 0, "completion": 0, "calls": 0, "model_seconds": 0.0}
        self._last_usage: Dict[str, Any] = {}

    REQUEST_TIMEOUT = 300   # seconds per HTTP call; Kimi K3's always-on thinking is slow

    def _tool_schemas(self) -> List[Dict[str, Any]]:
        schemas = [self.bash.to_json_schema()]
        if self.files:
            schemas.extend(self.files.to_json_schemas())
        return schemas

    # -- model I/O ---------------------------------------------------------

    def query_llm(self, user_message: str = "") -> Tuple[str, List[Dict[str, Any]]]:
        """
        Send the conversation to the model. An empty `user_message` means
        "continue after tool results" — appending a blank user turn there would
        corrupt the history, and some providers reject it outright.
        Returns (response_text, tool_calls).
        """
        if user_message:
            self.messages.append({"role": "user", "content": user_message})
            self._merge_idx = None
        if self.tool_format == "qwen_xml" and self.use_tools:
            return self._query_qwen_xml()

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": self.system_prompt}] + self.messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if self.use_tools:
            payload["tools"] = self._tool_schemas()
            payload["tool_choice"] = "auto"

        t_req = time.time()
        self._last_usage = {}
        message, error = self._request(payload)
        # NVIDIA's hosted Kimi K3 sometimes degenerates on tool-loop turns into a run of "!"
        # (or "<|close|>!!!…") instead of an answer — seen live. A fresh sample usually comes
        # back clean, so retry those a couple of times rather than returning the garbage.
        for _ in range(2):
            if error or not self.model.startswith("moonshotai/") or not self._degenerate(message):
                break
            message, error = self._request(payload)
        self.usage["model_seconds"] += time.time() - t_req
        self.usage["calls"] += 1
        self.usage["prompt"] += int(self._last_usage.get("prompt_tokens") or 0)
        self.usage["completion"] += int(self._last_usage.get("completion_tokens") or 0)
        if error:
            return error, []
        if self.model.startswith("moonshotai/") and self._degenerate(message):
            return "API error: the model returned degenerate output (repeated '!') three times.", []

        text = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []

        entry: Dict[str, Any] = {"role": "assistant", "content": text}
        if tool_calls:
            entry["tool_calls"] = tool_calls
        # Kimi K3 (moonshotai/kimi-k3) always thinks, and its docs require the COMPLETE
        # assistant message — reasoning included — to be passed back on the next turn of
        # a tool loop. Only echoed for moonshotai/ models so Nemotron's history is unchanged.
        if self.model.startswith("moonshotai/"):
            for k in ("reasoning_content", "reasoning"):
                if message.get(k):
                    entry[k] = message[k]
        self.messages.append(entry)

        return text, tool_calls

    def _query_qwen_xml(self) -> Tuple[str, List[Dict[str, Any]]]:
        """query_llm for a Qwen model: tools are declared in the system message and called in
        Qwen's XML text format; the API never sees a `tools` field."""
        schemas = self._tool_schemas()
        system = qwen_tool_block(schemas) + "\n\n" + self.system_prompt
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + self.messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        t_req = time.time()
        self._last_usage = {}
        message, error = self._request(payload)
        self.usage["model_seconds"] += time.time() - t_req
        self.usage["calls"] += 1
        self.usage["prompt"] += int(self._last_usage.get("prompt_tokens") or 0)
        self.usage["completion"] += int(self._last_usage.get("completion_tokens") or 0)
        if error:
            return error, []
        raw = message.get("content") or ""
        text, calls = parse_qwen_tool_calls(raw, schemas)
        # the raw reply goes back into the history untouched, calls included — that is what the
        # model is conditioned on for the next turn
        self.messages.append({"role": "assistant", "content": raw})
        self._merge_idx = None
        return text, calls

    def _request(self, payload: Dict[str, Any], attempt: int = 0):
        """
        POST to the chat-completions endpoint.
        Returns (message, None) on success or (None, error_string) on failure.
        Transient server errors are retried with exponential backoff.
        """
        request = urllib.request.Request(
            f"{self.api_endpoint}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.REQUEST_TIMEOUT) as response:
                status = response.status
                req_id = response.headers.get("NVCF-REQID")
                raw = response.read().decode("utf-8")
            if status == 202 and req_id:
                raw = self._poll_nvcf(req_id)
            body = json.loads(raw)
            self._last_usage = body.get("usage") or {}
            return body["choices"][0]["message"], None
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:400]
            except Exception:  # noqa: BLE001
                pass

            if e.code in (401, 403):
                # NVIDIA returns 403 for a rejected key; OpenRouter returns 401.
                return None, f"API error: invalid or missing API key ({e.code})."
            if e.code == 404:
                return None, (
                    f"API error: model '{self.model}' not found at "
                    f"{self.api_endpoint} (404). Check that the model ID matches "
                    f"the provider — the ':free' suffix is OpenRouter-only."
                )
            # 429/5xx are transient: NVIDIA sheds load with 503
            # "ResourceExhausted: Worker local total request limit reached".
            # A short backoff usually clears it (verified live).
            if e.code in (429, 500, 502, 503, 504) and attempt < self.MAX_RETRIES:
                time.sleep(2 ** attempt)
                return self._request(payload, attempt + 1)
            if e.code == 429:
                return None, "API error: rate limited (429). Try another key or wait."
            return None, f"API error: HTTP {e.code} {detail}".strip()
        except urllib.error.URLError as e:
            if attempt < self.MAX_RETRIES:
                time.sleep(2 ** attempt)
                return self._request(payload, attempt + 1)
            return None, f"API error: could not reach {self.api_endpoint} ({e.reason})."
        except (KeyError, IndexError, ValueError) as e:
            return None, f"Unexpected API response: {e}"

    @staticmethod
    def _degenerate(message: Dict[str, Any]) -> bool:
        if message.get("tool_calls"):
            return False
        text = (message.get("content") or "") + (message.get("reasoning_content") or "")
        return "<|close|>" in text or bool(re.search(r"!{12,}", text)) or not text.strip()

    def _poll_nvcf(self, req_id: str) -> str:
        """NVIDIA's cloud functions answer a slow request with 202 + NVCF-REQID instead of
        the result (Kimi K3's thinking can take minutes); the result is then fetched from the
        status endpoint, which keeps answering 202 until it's ready."""
        url = f"https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/{req_id}"
        deadline = time.time() + self.REQUEST_TIMEOUT * 3
        while time.time() < deadline:
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.api_key}"})
            with urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT) as response:
                status = response.status
                raw = response.read().decode("utf-8")
            if status != 202:
                return raw
            time.sleep(2)
        raise ValueError(f"NVCF request {req_id} still pending after polling")

    def process_tool_call(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """Run one tool call (with confirmation), returning the result payload."""
        function = tool_call.get("function", {}) or {}
        name = function.get("name")

        try:
            args = json.loads(function.get("arguments") or "{}")
        except json.JSONDecodeError:
            return {"error": "Tool arguments were not valid JSON."}

        if name == "exec_bash_command":
            cmd = args.get("cmd")
            if not cmd:
                return {"error": "No 'cmd' argument was provided."}
            # Human-in-the-loop: the user approves before anything runs.
            if self.confirm is not None and not self.confirm(cmd):
                return {"error": "The user declined the execution of this command."}
            return self.bash.exec_bash_command(cmd).to_dict()

        if name in ("read_file", "write_file", "list_files",
                    "grep_files", "glob_files", "edit_file"):
            if not self.files:
                return {"error": "File tools are not enabled for this session."}
            try:
                # Read-only tools need no confirmation.
                if name == "read_file":
                    return self.files.read_file(args.get("path", ""))
                if name == "list_files":
                    return self.files.list_files(args.get("path", ""))
                if name == "grep_files":
                    return self.files.grep_files(
                        args.get("pattern", ""), args.get("path", ""), args.get("glob", "")
                    )
                if name == "glob_files":
                    return self.files.glob_files(args.get("pattern", ""), args.get("path", ""))

                # Mutating tools go through the human-in-the-loop check.
                path = args.get("path", "")
                if name == "edit_file":
                    if self.confirm is not None and not self.confirm(f"edit {path}"):
                        return {"error": "The user declined this edit."}
                    return self.files.edit_file(
                        path, args.get("old_text", ""), args.get("new_text", "")
                    )

                if self.confirm is not None and not self.confirm(f"write {path}"):
                    return {"error": "The user declined this write."}
                return self.files.write_file(path, args.get("content", ""))
            except ValueError as e:
                return {"error": str(e)}

        return {"error": f"Unknown tool: {name!r}"}

    def _record_tool_result(self, tool_call: Dict[str, Any], result: Dict[str, Any]) -> None:
        if self.tool_format == "qwen_xml" and self.use_tools:
            # Qwen's template has no tool role: results ride in a user turn, one <tool_response> each,
            # all of a round's results in the same turn
            block = "<tool_response>\n" + render_tool_result(result) + "\n</tool_response>"
            if self._merge_idx is not None:
                self.messages[self._merge_idx]["content"] += "\n" + block
            else:
                self.messages.append({"role": "user", "content": block})
                self._merge_idx = len(self.messages) - 1
            return
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call.get("id", ""),
            "content": json.dumps(result),
        })

    def send(self, user_message: str, on_command: Optional[Callable[..., None]] = None) -> str:
        """
        Send one user message and resolve every resulting tool call.
        Returns the model's final natural-language reply.

        `on_command` is invoked after each tool execution. It may take either:
          (call, result) -- call = {"name": str, "args": dict}   [preferred]
          (cmd, result)  -- cmd  = the bash command string       [legacy]
        The legacy form only ever saw bash commands; file tools passed an empty
        string, which is why they could not be reported. The arity is detected
        so existing callers (the CLI's own reporter) keep working unchanged.
        """
        self.reset_usage()
        text, tool_calls = self.query_llm(user_message)

        rounds = 0
        while tool_calls and rounds < self.MAX_TOOL_ROUNDS:
            rounds += 1
            for tool_call in tool_calls:
                result = self.process_tool_call(tool_call)
                self._record_tool_result(tool_call, result)
                if on_command:
                    fn = tool_call.get("function", {}) or {}
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    name = fn.get("name") or ""
                    if getattr(on_command, "_wants_call", False):
                        on_command({"name": name, "args": args}, result)
                    else:
                        on_command(args.get("cmd", ""), result)

            text, tool_calls = self.query_llm()

        if tool_calls:
            text = (
                f"{strip_thinking(text)}\n\n[Stopped after {self.MAX_TOOL_ROUNDS} "
                f"tool rounds to avoid an endless loop.]"
            ).strip()

        return strip_thinking(text)

    # -- interactive REPL --------------------------------------------------

    def run_agent_loop(self) -> None:
        """Interactive REPL, mirroring the tutorial's UX."""
        print(f"[🤖 Nemotron Bash Agent]  model={self.model}")
        print(f"Working directory: {self.bash.cwd}")
        print("Type 'exit' or Ctrl-D to quit.\n")

        while True:
            try:
                user = input(f"['{self.bash.cwd}' 🙂] ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[Exit]")
                return

            if user.lower() in ("exit", "quit"):
                print("[Exit]")
                return
            if not user:
                continue

            def report(cmd: str, result: Dict[str, Any]) -> None:
                if "error" in result:
                    print(f"    ⚠️   {result['error']}")
                else:
                    out = (result.get("stdout") or "").strip()
                    err = (result.get("stderr") or "").strip()
                    if out:
                        print(f"    │ {out}".replace("\n", "\n    │ "))
                    if err:
                        print(f"    ⚠️  {err}".replace("\n", "\n    ⚠️  "))

            reply = self.send(user, on_command=report)
            if reply:
                print(f"\n[🤖] {reply}\n")


def confirm_in_terminal(cmd: str) -> bool:
    """Default human-in-the-loop prompt: ask before running `cmd`."""
    try:
        answer = input(f"    ▶️   Execute '{cmd}'? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


def main() -> None:
    # The Windows console defaults to cp1252 and cannot encode the emoji below.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    api_key = (
        os.getenv("NEMOTRON_API_KEY")
        or os.getenv("NVIDIA_API_KEY")
        or os.getenv("OPENROUTER_API_KEY")
    )
    if not api_key:
        print(
            "Error: set NEMOTRON_API_KEY (or NVIDIA_API_KEY) to your API key.",
            file=sys.stderr,
        )
        sys.exit(1)

    agent = NemotronAgent(
        api_key=api_key,
        api_endpoint=os.getenv("NEMOTRON_ENDPOINT", DEFAULT_ENDPOINT),
        model=os.getenv("NEMOTRON_MODEL", DEFAULT_MODEL),
        confirm=confirm_in_terminal,
    )
    agent.run_agent_loop()


if __name__ == "__main__":
    main()
