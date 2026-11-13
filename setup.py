"""Build hook: copy the data an installed offload needs into the wheel (see offload/_bundle.py)."""
import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

sys.path.insert(0, str(Path(__file__).resolve().parent))


class BuildPy(build_py):
    def run(self):
        super().run()
        from offload import _bundle
        _bundle.collect(Path(self.build_lib) / "offload" / "_root")


setup(cmdclass={"build_py": BuildPy})
