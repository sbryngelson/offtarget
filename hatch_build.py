"""Build hook: copy the data an installed offload needs into the wheel as offload/_root (offload/_bundle.py).
An editable install reads the checkout instead and gets nothing."""
import sys
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class BundleHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        if version == "editable":
            return
        sys.path.insert(0, self.root)
        from offload import _bundle
        self._tmp = tempfile.TemporaryDirectory(prefix="offload_root_")
        _bundle.collect(Path(self._tmp.name))
        build_data["force_include"][self._tmp.name] = "offload/_root"

    def finalize(self, version: str, build_data: dict, artifact_path: str) -> None:
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()
