from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.go import setup
from src.go.extension import Go


class TestGoExtension:
    def test_setup_and_registration(self, mock_api) -> None:
        setup(mock_api)
        assert "go" in mock_api.registered_extensions
        ext = mock_api.registered_extensions["go"]
        assert isinstance(ext, Go)

    def test_install_registers_commands_and_integrations(self, mock_api) -> None:
        ext = Go(mock_api)
        ext.install()

        # Commands
        commands = mock_api.commands.commands
        assert "go.run_file" in commands
        assert "go.run_package" in commands
        assert "go.run_tests" in commands
        assert "go.run_benchmarks" in commands
        assert "go.build" in commands
        assert "go.mod_tidy" in commands

        # Core registrations
        mock_api.register_comment_prefix.assert_called_with("go", "//")
        mock_api.register_langserver.assert_called_with("go", "gopls")
        mock_api.register_run_command.assert_called()

        # Statusbar
        assert ext.statusbar_button is not None
        assert ext.statusbar_button.visible is True

    def test_get_go_environment(self, mock_api) -> None:
        ext = Go(mock_api)
        with patch("shutil.which", return_value="/usr/local/go/bin/go"):
            with patch("subprocess.run") as mock_sub:
                mock_sub.return_value = MagicMock(
                    stdout="go version go1.22.4 darwin/arm64\n",
                    stderr="",
                    returncode=0,
                )
                env = ext.get_go_environment()
                assert env["installed"] == "true"
                assert env["version"] == "1.22.4"
                assert env["GOOS"] == "darwin"
                assert env["GOARCH"] == "arm64"

    def test_parse_go_mod(self, mock_api) -> None:
        ext = Go(mock_api)
        sample_mod = """
module github.com/biscuit/sample-service

go 1.22.1

require (
    github.com/gin-gonic/gin v1.9.1
    github.com/stretchr/testify v1.8.4 // indirect
)

require golang.org/x/net v0.20.0
"""
        parsed = ext.parse_go_mod(sample_mod)
        assert parsed["module"] == "github.com/biscuit/sample-service"
        assert parsed["go_version"] == "1.22.1"
        assert len(parsed["dependencies"]) == 3

        deps = {d["package"]: d for d in parsed["dependencies"]}
        assert deps["github.com/gin-gonic/gin"]["version"] == "v1.9.1"
        assert deps["github.com/gin-gonic/gin"]["indirect"] is False

        assert deps["github.com/stretchr/testify"]["version"] == "v1.8.4"
        assert deps["github.com/stretchr/testify"]["indirect"] is True

        assert deps["golang.org/x/net"]["version"] == "v0.20.0"

    def test_find_go_mod_hierarchy(self, mock_api, tmp_path) -> None:
        ext = Go(mock_api)
        root = tmp_path / "myrepo"
        sub = root / "pkg" / "util"
        sub.mkdir(parents=True)
        mod_file = root / "go.mod"
        mod_file.write_text("module myrepo\ngo 1.22\n", encoding="utf-8")

        found = ext.find_go_mod(str(sub))
        assert found == mod_file

    def test_discover_packages(self, mock_api, tmp_path) -> None:
        ext = Go(mock_api)
        pkg_dir = tmp_path / "mypkg"
        pkg_dir.mkdir()
        (pkg_dir / "main.go").write_text("package main\nfunc main() {}\n", encoding="utf-8")
        (pkg_dir / "main_test.go").write_text("package main\nimport \"testing\"\n", encoding="utf-8")

        with patch("shutil.which", return_value=None):
            packages = ext.discover_packages(str(tmp_path))

        assert len(packages) >= 1
        pkg = next(p for p in packages if p["name"] == "main")
        assert "main.go" in pkg["go_files"]
        assert "main_test.go" in pkg["test_files"]

    def test_build_commands(self, mock_api) -> None:
        ext = Go(mock_api)
        run_cmd = ext.build_run_command("main.go", ["--port", "8080"])
        assert 'go run "main.go" --port 8080' in run_cmd

        test_cmd = ext.build_test_command("./...", json_mode=True, benchmark=True, coverage=True)
        assert "-v -json -bench=. -cover" in test_cmd

        build_cmd = ext.build_build_command("bin/server", "cmd/server/main.go")
        assert 'go build -o "bin/server" "cmd/server/main.go"' in build_cmd

    def test_parse_compiler_diagnostics(self, mock_api) -> None:
        ext = Go(mock_api)
        raw_output = """
main.go:15:2: undefined: fmt.Printl
pkg/util/math.go:42:10: cannot use x (variable of type int) as string
"""
        diags = ext.parse_compiler_diagnostics(raw_output)
        assert len(diags) == 2
        assert diags[0]["file"] == "main.go"
        assert diags[0]["line"] == 15
        assert diags[0]["col"] == 2
        assert "undefined: fmt.Printl" in diags[0]["message"]

        assert diags[1]["file"] == "pkg/util/math.go"
        assert diags[1]["line"] == 42
        assert diags[1]["col"] == 10

    def test_parse_test_json_events(self, mock_api) -> None:
        ext = Go(mock_api)
        sample_json_events = [
            '{"Time":"2026-10-18T10:00:00Z","Action":"run","Package":"myrepo/math","Test":"TestAdd"}',
            '{"Time":"2026-10-18T10:00:00.01Z","Action":"output","Package":"myrepo/math","Test":"TestAdd","Output":"=== RUN   TestAdd\\n"}',
            '{"Time":"2026-10-18T10:00:00.02Z","Action":"pass","Package":"myrepo/math","Test":"TestAdd","Elapsed":0.01}',
            '{"Time":"2026-10-18T10:00:00.03Z","Action":"run","Package":"myrepo/math","Test":"TestDivideZero"}',
            '{"Time":"2026-10-18T10:00:00.04Z","Action":"fail","Package":"myrepo/math","Test":"TestDivideZero","Elapsed":0.02}',
            '{"Time":"2026-10-18T10:00:00.05Z","Action":"run","Package":"myrepo/math","Test":"TestSkip"}',
            '{"Time":"2026-10-18T10:00:00.06Z","Action":"skip","Package":"myrepo/math","Test":"TestSkip","Elapsed":0.00}',
            '{"Time":"2026-10-18T10:00:00.07Z","Action":"fail","Package":"myrepo/math","Elapsed":0.03}',
        ]

        report = ext.parse_test_json_events(sample_json_events)
        assert report["total"] == 3
        assert report["passed"] == 1
        assert report["failed"] == 1
        assert report["skipped"] == 1
        assert "myrepo/math" in report["packages"]
        assert report["packages"]["myrepo/math"]["status"] == "FAIL"

    def test_command_handlers(self, mock_api) -> None:
        ext = Go(mock_api)
        ext.install()

        # Terminal run command
        ext.run_package_command()
        assert len(mock_api.terminalmanager.opened_terminals) == 1
        assert "go run" in mock_api.terminalmanager.opened_terminals[0]

        # Environment display
        with patch.object(ext, "get_go_environment", return_value={"version": "1.22", "GOOS": "linux", "GOARCH": "amd64"}):
            env = ext.show_go_environment_command()
            assert env["version"] == "1.22"
            mock_api.notifications.info.assert_called()

    def test_manifest_schema_and_dependencies(self) -> None:
        import tomllib

        manifest_path = Path(__file__).parent.parent / "extension.toml"
        assert manifest_path.exists()
        with open(manifest_path, "rb") as f:
            data = tomllib.load(f)

        assert data["extension"]["id"] == "go"
        assert data["extension"]["author"] == "tomlin7"
        assert data["extension"]["version"] == "0.2.0"
        assert "go" in data["dependencies"]["tools"]
        assert "gopls" in data["dependencies"]["tools"]
        assert len(data["contributes"]["commands"]) >= 5
