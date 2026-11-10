from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .converter import convert_book, export_bookmarks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdg2pdf",
        description="Convert PDG books or image directories to a PDF on Linux.",
    )
    parser.add_argument("input", nargs="?", help="PDG directory or ZIP archive")
    parser.add_argument("output", nargs="?", help="Output PDF path")
    parser.add_argument("--title", help="Override the PDF title")
    parser.add_argument("--dpi", type=float, help="Image DPI used when placing pages in PDF")
    parser.add_argument("--fixed-width", type=int, help="Target page width in source pixels; all PDF pages use this width")
    parser.add_argument("--image-format", choices=("original", "jpeg", "png", "tiff"), default="original")
    parser.add_argument("--jpeg-quality", type=int, default=90, help="JPEG quality from 1 to 100")
    parser.add_argument("--grayscale", action="store_true", help="Convert image pages to grayscale")
    parser.add_argument("--bookmarks-file", type=Path, help="JSON or simple text bookmark file to use instead of BookContents.dat")
    parser.add_argument("--no-bookmarks", action="store_true", help="Do not write PDF bookmarks")
    parser.add_argument("--export-bookmarks", type=Path, help="Export BookContents.dat as editable JSON and exit")
    parser.add_argument("--gui", action="store_true", help="Launch the GTK desktop interface")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.export_bookmarks:
        if not args.input:
            print("pdg2pdf: error: --export-bookmarks requires an input directory or ZIP", file=sys.stderr)
            return 2
        try:
            count = export_bookmarks(args.input, args.export_bookmarks)
        except Exception as exc:
            print(f"pdg2pdf: error: {exc}", file=sys.stderr)
            return 1
        print(f"Exported {count} bookmarks to {args.export_bookmarks}")
        return 0
    if args.gui or not args.input:
        from .gui import run_gui
        return run_gui()
    source = Path(args.input).expanduser()
    output = Path(args.output).expanduser() if args.output else source.with_suffix(".pdf")

    def progress(done: int, total: int, name: str) -> None:
        print(f"[{done}/{total}] {name}", flush=True)

    try:
        result = convert_book(
            source,
            output,
            title=args.title,
            progress=progress,
            dpi=args.dpi,
            fixed_width=args.fixed_width,
            image_format=args.image_format,
            jpeg_quality=args.jpeg_quality,
            grayscale=args.grayscale,
            bookmarks_file=args.bookmarks_file,
            no_bookmarks=args.no_bookmarks,
        )
    except Exception as exc:
        print(f"pdg2pdf: error: {exc}", file=sys.stderr)
        return 1
    print(f"Created {result.output} ({result.page_count} pages)")
    if result.warnings:
        print(f"Skipped {len(result.warnings)} page(s):", file=sys.stderr)
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
