from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.go import setup
from src.go.extension import Go


class TestGoExtension:
    def test_extension_setup(self, app_instance) -> None:
        setup(app_instance.api)
        ext = Go(app_instance.api)
        assert ext.build_run_command("main.go") == 'go run "main.go"'
        assert ext.build_test_command("./pkg/...") == 'go test -v "./pkg/..."'
        assert ext.build_build_command("bin/server", "cmd/server.go") == 'go build -o "bin/server" "cmd/server.go"'
