from __future__ import annotations

import argparse
import sys

__version__ = "0.0.1"

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loom", description="A coding agent, built from scratch.")
    parser.add_argument(
        "--version",
        action="version",
        version=f"loom {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    return 0

if __name__ == "__main__":
    sys.exit(main())