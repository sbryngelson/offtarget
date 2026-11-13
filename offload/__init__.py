"""Known OpenMP and OpenACC offload compiler problems: look up support, search issues."""

try:
    from offload._version import __version__   # written by hatch-vcs at build time (the git tag)
except ImportError:                             # a checkout that was not built
    from importlib.metadata import PackageNotFoundError, version
    try:
        __version__ = version("offtarget")
    except PackageNotFoundError:
        __version__ = "0+unknown"
