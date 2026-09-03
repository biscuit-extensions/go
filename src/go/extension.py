from __future__ import annotations

import typing

from biscuit.extensions import Extension

if typing.TYPE_CHECKING:
    from biscuit.api import ExtensionsAPI


class Go(Extension):
    """Rich Go language support, test runner, formatting, and build tools"""

    def __init__(self, api: ExtensionsAPI) -> None:
        super().__init__(api)
        self.api = api
        self.api.logger.info("Go extension initialised.")

    def build_run_command(self, file_path: str) -> str:
        return f'go run "{file_path}"'

    def build_test_command(self, package_path: str = "./...") -> str:
        return f'go test -v "{package_path}"'

    def build_build_command(self, output_path: str, entry_file: str) -> str:
        return f'go build -o "{output_path}" "{entry_file}"'

    def detect_go_mod(self, workspace_path: str) -> bool:
        import os
        return os.path.isfile(os.path.join(workspace_path, "go.mod"))

    def install(self) -> None:
        self.api.logger.info("Go extension installed.")
