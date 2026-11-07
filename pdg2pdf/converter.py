from __future__ import annotations

import io
import logging
import re
import shutil
import subprocess
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import img2pdf
import pikepdf
from PIL import Image, UnidentifiedImageError

from . import decoder

LOG = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".pdg", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".gif"}


@dataclass(frozen=True)
class ConversionResult:
    output: Path
    page_count: int
    warnings: tuple[str, ...]


def _natural_key(path: Path):
    name = path.name.lower()
    parts = re.split(r"(\d+)", name)
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _magic(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"GIF8"):
        return "gif"
    if data.startswith(b"BM"):
        return "bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    if data.startswith(b"AT&TFORM") and len(data) >= 16 and data[12:16] in (b"DJVU", b"DJVM"):
        return "djvu"
    return None


def _render_pdg(path: Path, raw: bytes) -> bytes:
    width, height = decoder._decode_size_for_pdg(raw)
    decoded, kind = decoder.pdg_decode_pure_bytes(raw, width, height)
    if kind == "djvu":
        executable = shutil.which("ddjvu")
        if not executable:
            raise RuntimeError("This page contains DjVu data. Install DjVuLibre (for example: apt install djvulibre-bin) to render it.")
        proc = subprocess.run(
            [executable, "-format=pnm", "-"], input=decoded, capture_output=True, check=False, timeout=120
        )
        if proc.returncode:
            raise RuntimeError(f"ddjvu could not render {path.name}: {proc.stderr.decode(errors='replace').strip()}")
        decoded = proc.stdout
        kind = "pnm"
    if kind is None:
        raise RuntimeError(f"Unsupported or encrypted PDG variant in {path.name} (type 0x{raw[15]:02x})")
    try:
        with Image.open(io.BytesIO(decoded)) as image:
            image.load()
            normalized = io.BytesIO()
            image.save(normalized, format="PNG", optimize=False)
            return normalized.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise RuntimeError(f"Decoded page is not a valid image: {path.name}") from exc


def _read_info(root: Path) -> dict[str, str]:
    for candidate in root.iterdir():
        if candidate.is_file() and candidate.name.lower() in {"bookinfo.dat", "bookinfo.txt"}:
            raw = candidate.read_bytes()
            for encoding in ("utf-8-sig", "gb18030", "utf-16"):
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                continue
            return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    return {}


def _read_bookmarks(root: Path, page_count: int) -> list[tuple[str, int, int]]:
    candidate = next((p for p in root.iterdir() if p.is_file() and p.name.lower() == "bookcontents.dat"), None)
    if not candidate:
        return []
    raw = candidate.read_bytes()
    text = ""
    for offset in range(len(raw)):
        if raw[offset:offset + 2] not in (b"\x78\x01", b"\x78\x5e", b"\x78\x9c", b"\x78\xda"):
            continue
        try:
            text = zlib.decompress(raw[offset:]).decode("gb18030", errors="replace")
            break
        except zlib.error:
            continue
    bookmarks = []
    for line in text.splitlines():
        cols = line.split("|")
        if len(cols) < 3:
            continue
        try:
            page = int(cols[2], 16)
            level = max(0, int(cols[4])) if len(cols) > 4 and cols[4].isdigit() else 0
        except ValueError:
            continue
        if 0 <= page < page_count and cols[0].strip():
            bookmarks.append((cols[0].strip(), page, level))
    return bookmarks


def _collect_pages(source: Path, temp: Path) -> tuple[list[Path], Path]:
    root = source
    if source.is_file() and zipfile.is_zipfile(source):
        root = temp / "input"
        root.mkdir()
        with zipfile.ZipFile(source) as archive:
            for item in archive.infolist():
                target = (root / item.filename).resolve()
                if root.resolve() not in target.parents and target != root.resolve():
                    raise RuntimeError("Archive contains an unsafe path")
            archive.extractall(root)
    elif source.is_file():
        raise ValueError("Input must be a directory or a ZIP archive")
    if not root.is_dir():
        raise ValueError(f"Input directory not found: {root}")
    files = sorted((p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES), key=_natural_key)
    if not files:
        raise ValueError("No supported image or PDG pages were found")
    return files, root


def convert_book(
    source: str | Path,
    output: str | Path,
    *,
    title: str | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> ConversionResult:
    source, output = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="pdg2pdf-") as tmp:
        tmpdir = Path(tmp)
        files, root = _collect_pages(source, tmpdir)
        info = _read_info(root) if root.is_dir() else {}
        page_pdfs: list[bytes] = []
        for index, page in enumerate(files, 1):
            raw = page.read_bytes()
            kind = _magic(raw)
            try:
                if kind:
                    image_data = raw
                    if kind == "gif":
                        with Image.open(io.BytesIO(raw)) as im:
                            im.seek(0)
                            b = io.BytesIO()
                            im.convert("RGB").save(b, format="PNG")
                            image_data = b.getvalue()
                elif raw.startswith(b"HH"):
                    image_data = _render_pdg(page, raw)
                else:
                    warnings.append(f"Skipped unrecognized file: {page.name}")
                    continue
                page_pdfs.append(img2pdf.convert(image_data))
            except Exception as exc:
                raise RuntimeError(f"Failed on page {page.name}: {exc}") from exc
            if progress:
                progress(index, len(files), page.name)
        if not page_pdfs:
            raise RuntimeError("No pages could be converted")
        pdf = pikepdf.Pdf.new()
        for page_pdf in page_pdfs:
            with pikepdf.open(io.BytesIO(page_pdf)) as part:
                pdf.pages.extend(part.pages)
        final_title = title or info.get("书名", "").strip() or source.stem
        with pdf.open_metadata() as metadata:
            metadata["dc:title"] = final_title
            author = info.get("作者", "").strip()
            if author:
                metadata["dc:creator"] = [author]
        if root.is_dir():
            bookmarks = _read_bookmarks(root, len(pdf.pages))
            if bookmarks:
                with pdf.open_outline() as outline:
                    stack = [outline.root]
                    for label, page, level in bookmarks:
                        level = min(level, len(stack) - 1)
                        stack = stack[:level + 1]
                        item = pikepdf.OutlineItem(label, page)
                        stack[-1].append(item)
                        stack.append(item.children)
        pdf.save(output)
        page_count = len(pdf.pages)
    return ConversionResult(output, page_count, tuple(warnings))
