from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import typing
from pathlib import Path

from biscuit.extensions import Extension

if typing.TYPE_CHECKING:
    from biscuit.api import ExtensionsAPI


class Go(Extension):
    """Production Go language support, environment detector, test runner, and build tool."""

    def __init__(self, api: ExtensionsAPI) -> None:
        super().__init__(api)
        self.api = api
        self.statusbar_button = None
        self.go_binary = shutil.which("go")
        self.api.logger.info("Go extension loaded.")

    def get_go_binary(self) -> str:
        """Return path to go executable or fallback 'go'."""
        return self.go_binary or "go"

    def get_go_environment(self) -> dict[str, str]:
        """Detect Go environment variables, runtime version, and system architectures."""
        env_data: dict[str, str] = {
            "GOPATH": os.environ.get("GOPATH", ""),
            "GOROOT": os.environ.get("GOROOT", ""),
            "GOOS": os.environ.get("GOOS", ""),
            "GOARCH": os.environ.get("GOARCH", ""),
            "version": "",
            "installed": "false",
        }

        bin_path = shutil.which("go")
        if not bin_path:
            return env_data

        env_data["installed"] = "true"
        try:
            res = subprocess.run([bin_path, "version"], capture_output=True, text=True, timeout=5)
            output = (res.stdout or res.stderr).strip()
            # e.g. "go version go1.22.2 windows/amd64"
            match = re.search(r"go\s+version\s+go([\d\.\w]+)\s+([a-zA-Z0-9_\-]+)/([a-zA-Z0-9_\-]+)", output)
            if match:
                env_data["version"] = match.group(1)
                env_data["GOOS"] = match.group(2)
                env_data["GOARCH"] = match.group(3)
        except Exception as e:
            self.api.logger.warning(f"Error querying go version: {e}")

        # Query go env if GOPATH or GOROOT missing
        if not env_data["GOPATH"] or not env_data["GOROOT"]:
            try:
                res = subprocess.run([bin_path, "env", "GOPATH", "GOROOT"], capture_output=True, text=True, timeout=5)
                lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
                if len(lines) >= 2:
                    env_data["GOPATH"] = lines[0]
                    env_data["GOROOT"] = lines[1]
            except Exception:
                pass

        return env_data

    def detect_go_mod(self, workspace_path: str) -> bool:
        """Check if go.mod exists in target directory."""
        return os.path.isfile(os.path.join(workspace_path, "go.mod"))

    def find_go_mod(self, start_dir: str | None = None) -> Path | None:
        """Traverse directory tree upward to locate go.mod."""
        curr = Path(start_dir or os.getcwd()).resolve()
        for parent in [curr] + list(curr.parents):
            mod_file = parent / "go.mod"
            if mod_file.is_file():
                return mod_file
        return None

    def parse_go_mod(self, content: str) -> dict[str, typing.Any]:
        """Parse go.mod file content to extract module path, go version, and dependencies."""
        result: dict[str, typing.Any] = {
            "module": "",
            "go_version": "",
            "dependencies": [],
            "replaces": [],
        }

        # Module name
        mod_match = re.search(r"^module\s+([^\s\n]+)", content, re.MULTILINE)
        if mod_match:
            result["module"] = mod_match.group(1).strip()

        # Go version
        ver_match = re.search(r"^go\s+([0-9\.]+)", content, re.MULTILINE)
        if ver_match:
            result["go_version"] = ver_match.group(1).strip()

        # Single line require: require example.com/pkg v1.0.0
        single_reqs = re.finditer(r"^require\s+([^\s\(\)]+)\s+([^\s\n]+)(?:\s+//\s*(indirect))?", content, re.MULTILINE)
        for m in single_reqs:
            result["dependencies"].append({
                "package": m.group(1),
                "version": m.group(2),
                "indirect": bool(m.group(3)),
            })

        # Block require: require ( ... )
        block_match = re.search(r"require\s*\(([\s\S]*?)\)", content)
        if block_match:
            block_body = block_match.group(1)
            for line in block_body.splitlines():
                clean = line.strip()
                if not clean or clean.startswith("//"):
                    continue
                parts = clean.split()
                if len(parts) >= 2:
                    pkg = parts[0]
                    ver = parts[1]
                    indirect = "// indirect" in clean
                    result["dependencies"].append({
                        "package": pkg,
                        "version": ver,
                        "indirect": indirect,
                    })

        return result

    def discover_packages(self, workspace_dir: str | None = None) -> list[dict[str, typing.Any]]:
        """Discover Go packages in directory via 'go list -json' or directory scan."""
        target_dir = Path(workspace_dir or os.getcwd())
        bin_path = shutil.which("go")

        if bin_path:
            try:
                res = subprocess.run(
                    [bin_path, "list", "-json", "./..."],
                    cwd=str(target_dir),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if res.stdout.strip():
                    decoder = json.JSONDecoder()
                    idx = 0
                    packages = []
                    text = res.stdout.strip()
                    while idx < len(text):
                        while idx < len(text) and text[idx].isspace():
                            idx += 1
                        if idx >= len(text):
                            break
                        obj, end_idx = decoder.raw_decode(text, idx)
                        packages.append({
                            "name": obj.get("Name", ""),
                            "import_path": obj.get("ImportPath", ""),
                            "dir": obj.get("Dir", ""),
                            "go_files": obj.get("GoFiles", []),
                            "test_files": obj.get("TestGoFiles", []) + obj.get("XTestGoFiles", []),
                        })
                        idx = end_idx
                    if packages:
                        return packages
            except Exception:
                pass

        # Static file system scan fallback
        discovered: list[dict[str, typing.Any]] = []
        for go_file in target_dir.rglob("*.go"):
            if ".git" in go_file.parts:
                continue
            folder = str(go_file.parent)
            existing = next((p for p in discovered if p["dir"] == folder), None)
            if not existing:
                pkg_name = "main"
                try:
                    for line in go_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                        line = line.strip()
                        if line.startswith("package "):
                            pkg_name = line.split()[1]
                            break
                except Exception:
                    pass
                existing = {
                    "name": pkg_name,
                    "import_path": str(go_file.parent.relative_to(target_dir)).replace("\\", "/"),
                    "dir": folder,
                    "go_files": [],
                    "test_files": [],
                }
                discovered.append(existing)

            if go_file.name.endswith("_test.go"):
                existing["test_files"].append(go_file.name)
            else:
                existing["go_files"].append(go_file.name)

        return discovered

    def build_run_command(self, package_or_file: str, args: list[str] | None = None) -> str:
        """Generate shell command for 'go run'."""
        cmd = f'go run "{package_or_file}"'
        if args:
            extra = " ".join(f'"{a}"' if " " in a else a for a in args)
            cmd = f"{cmd} {extra}"
        return cmd

    def build_test_command(
        self,
        package_path: str = "./...",
        json_mode: bool = False,
        benchmark: bool = False,
        coverage: bool = False,
        extra_flags: list[str] | None = None,
    ) -> str:
        """Generate shell command for 'go test' with optional flags."""
        flags = ["-v"]
        if json_mode:
            flags.append("-json")
        if benchmark:
            flags.append("-bench=.")
        if coverage:
            flags.append("-cover")
        if extra_flags:
            flags.extend(extra_flags)

        flags_str = " ".join(flags)
        return f'go test {flags_str} "{package_path}"'

    def build_build_command(self, output_path: str, entry_file: str, flags: list[str] | None = None) -> str:
        """Generate shell command for 'go build'."""
        flag_str = f" {' '.join(flags)}" if flags else ""
        return f'go build{flag_str} -o "{output_path}" "{entry_file}"'

    def parse_compiler_diagnostics(self, output: str) -> list[dict[str, typing.Any]]:
        """Parse Go compiler output into structured diagnostics (file, line, col, message)."""
        diagnostics: list[dict[str, typing.Any]] = []
        pattern = re.compile(r"^(.+?):(\d+):(\d+):\s*(.+)$", re.MULTILINE)
        for match in pattern.finditer(output):
            diagnostics.append({
                "file": match.group(1).strip(),
                "line": int(match.group(2)),
                "col": int(match.group(3)),
                "message": match.group(4).strip(),
            })
        return diagnostics

    def parse_test_json_events(self, json_lines: str | list[str]) -> dict[str, typing.Any]:
        """Stream and parse Go test JSON events into structured test report."""
        if isinstance(json_lines, str):
            lines = json_lines.strip().splitlines()
        else:
            lines = json_lines

        tests: dict[str, dict[str, typing.Any]] = {}
        packages: dict[str, dict[str, typing.Any]] = {}
        total_duration = 0.0

        for raw_line in lines:
            line = raw_line.strip()
            if not line.startswith("{") or not line.endswith("}"):
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue

            action = event.get("Action", "")
            pkg = event.get("Package", "")
            test_name = event.get("Test", "")
            elapsed = float(event.get("Elapsed", 0.0))
            output_msg = event.get("Output", "")

            # Package-level status
            if not test_name and pkg:
                if pkg not in packages:
                    packages[pkg] = {"status": "running", "duration": 0.0}
                if action in ("pass", "fail", "skip"):
                    packages[pkg]["status"] = action.upper()
                    packages[pkg]["duration"] = elapsed
                    total_duration += elapsed
                continue

            # Test-level status
            if test_name:
                key = f"{pkg}::{test_name}"
                if key not in tests:
                    tests[key] = {
                        "id": key,
                        "name": test_name,
                        "package": pkg,
                        "status": "RUNNING",
                        "duration": 0.0,
                        "output": [],
                    }
                if output_msg:
                    tests[key]["output"].append(output_msg)
                if action in ("pass", "fail", "skip"):
                    tests[key]["status"] = "PASSED" if action == "pass" else ("FAILED" if action == "fail" else "SKIPPED")
                    tests[key]["duration"] = elapsed

        test_list = list(tests.values())
        passed_count = sum(1 for t in test_list if t["status"] == "PASSED")
        failed_count = sum(1 for t in test_list if t["status"] == "FAILED")
        skipped_count = sum(1 for t in test_list if t["status"] == "SKIPPED")

        return {
            "total": len(test_list),
            "passed": passed_count,
            "failed": failed_count,
            "skipped": skipped_count,
            "duration": round(total_duration, 4),
            "packages": packages,
            "tests": test_list,
        }

    def run_tests(self, package_path: str = "./...", json_mode: bool = True) -> dict[str, typing.Any]:
        """Execute 'go test' and return structured test results."""
        cmd = [self.get_go_binary(), "test", "-v"]
        if json_mode:
            cmd.append("-json")
        cmd.append(package_path)

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if json_mode:
                summary = self.parse_test_json_events(proc.stdout)
                summary["returncode"] = proc.returncode
                summary["raw_output"] = proc.stdout
                return summary
            else:
                return {
                    "returncode": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                }
        except Exception as e:
            self.api.logger.error(f"Error running go tests: {e}")
            return {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
                "duration": 0.0,
                "tests": [],
                "error": str(e),
                "returncode": -1,
            }

    def install(self) -> None:
        """Register commands, statusbar widget, and editor bindings."""
        # 1. Register commands
        self.api.commands.register_command("go.run_file", lambda: self.run_file_command())
        self.api.commands.register_command("go.run_package", lambda: self.run_package_command())
        self.api.commands.register_command("go.run_tests", lambda: self.run_tests())
        self.api.commands.register_command("go.run_benchmarks", lambda: self.run_benchmarks_command())
        self.api.commands.register_command("go.build", lambda: self.build_command())
        self.api.commands.register_command("go.mod_tidy", lambda: self.mod_tidy_command())

        # 2. Register core integrations
        self.api.register_comment_prefix("go", "//")
        self.api.register_run_command("go", 'go run "{filename}"')
        self.api.register_langserver("go", "gopls")

        # 3. Statusbar widget
        env = self.get_go_environment()
        ver = env.get("version", "")
        label = f"Go {ver}".strip() if ver else "Go (Not Found)"

        try:
            self.statusbar_button = self.api.statusbar.add_button(
                text=label,
                icon="symbol-method",
                callback=self.show_go_environment_command,
                description="Go Environment",
            )
            if self.statusbar_button:
                self.statusbar_button.show()
        except Exception as e:
            self.api.logger.warning(f"Could not initialize Go statusbar button: {e}")

        self.api.logger.info("Go extension installed.")

    def run_file_command(self) -> None:
        """Command: execute active Go file."""
        active = getattr(self.api.editors, "active_editor", None)
        path = getattr(active, "path", None)
        if path:
            cmd = self.build_run_command(str(path))
            if hasattr(self.api, "terminalmanager") and self.api.terminalmanager:
                self.api.terminalmanager.open_terminal(command=cmd)
            self.api.logger.info(f"Running Go file: {path}")
        else:
            self.api.notifications.warning("No active Go file open to run.")

    def run_package_command(self) -> None:
        """Command: execute active package."""
        cmd = self.build_run_command(".")
        if hasattr(self.api, "terminalmanager") and self.api.terminalmanager:
            self.api.terminalmanager.open_terminal(command=cmd)

    def run_benchmarks_command(self) -> None:
        """Command: execute benchmarks."""
        cmd = self.build_test_command(benchmark=True)
        if hasattr(self.api, "terminalmanager") and self.api.terminalmanager:
            self.api.terminalmanager.open_terminal(command=cmd)

    def build_command(self) -> None:
        """Command: build Go binary."""
        cmd = self.build_build_command("bin/app", ".")
        if hasattr(self.api, "terminalmanager") and self.api.terminalmanager:
            self.api.terminalmanager.open_terminal(command=cmd)

    def mod_tidy_command(self) -> None:
        """Command: execute go mod tidy."""
        cmd = f"{self.get_go_binary()} mod tidy"
        if hasattr(self.api, "terminalmanager") and self.api.terminalmanager:
            self.api.terminalmanager.open_terminal(command=cmd)

    def show_go_environment_command(self) -> dict[str, str]:
        """Display Go environment information."""
        env = self.get_go_environment()
        ver = env.get("version", "unknown")
        self.api.notifications.info(f"Go Version: {ver} (OS: {env.get('GOOS')}, Arch: {env.get('GOARCH')})")
        return env
