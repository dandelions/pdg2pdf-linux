from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .converter import convert_book


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdg2pdf",
        description="Convert PDG books or image directories to a PDF on Linux.",
    )
    parser.add_argument("input", nargs="?", help="PDG directory or ZIP archive")
    parser.add_argument("output", nargs="?", help="Output PDF path")
    parser.add_argument("--title", help="Override the PDF title")
    parser.add_argument("--gui", action="store_true", help="Launch the GTK desktop interface")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.gui or not args.input:
        from .gui import run_gui
        return run_gui()
    source = Path(args.input).expanduser()
    output = Path(args.output).expanduser() if args.output else source.with_suffix(".pdf")

    def progress(done: int, total: int, name: str) -> None:
        print(f"[{done}/{total}] {name}", flush=True)

    try:
        result = convert_book(source, output, title=args.title, progress=progress)
    except Exception as exc:
        print(f"pdg2pdf: error: {exc}", file=sys.stderr)
        return 1
    print(f"Created {result.output} ({result.page_count} pages)")
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
