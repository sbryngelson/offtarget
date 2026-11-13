"""The offload command: one entry point, two subcommands (can-use, issues)."""
import importlib
import sys
from typing import Callable

from offload.engine import root
from offload import __version__

SUMMARY = {
    "can-use": "which compilers and versions support a clause, directive or construct",
    "issues": "search the known compiler problems, with reproducers",
}


def _lazy(module: str) -> Callable[[list[str]], int]:
    """Import the command only when it runs, after the data check."""
    def run(argv: list[str]) -> int:
        return importlib.import_module(f"offload.{module}").main(argv)
    return run


COMMANDS: dict[str, Callable[[list[str]], int]] = {
    "can-use": _lazy("canuse"),
    "issues": _lazy("issues"),
}


def _usage() -> str:
    width = max(map(len, SUMMARY))
    lines = ["usage: offload [--version] COMMAND [ARGS]", "", "commands:"]
    lines += [f"  {name:<{width}}  {text}" for name, text in SUMMARY.items()]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(_usage(), file=sys.stderr)
        return 2
    if argv[0] == "--version":
        print(f"offload {__version__}")
        return 0
    if argv[0] in ("-h", "--help"):
        print(_usage())
        return 0
    if argv[0] not in COMMANDS:
        print(f"offload: unknown command '{argv[0]}'\n\n{_usage()}", file=sys.stderr)
        return 2
    if argv[1:2] not in (['-h'], ['--help']) and (why := root.problem()):
        print(why, file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])
