from __future__ import annotations

import io
import json
import logging
import re
import shutil
import subprocess
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import img2pdf
import pikepdf
from PIL import Image, UnidentifiedImageError

from . import decoder

LOG = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".pdg", ".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".gif"}
ARCHIVE_SUFFIXES = {".zip", ".uvz"}
IMAGE_FORMATS = {"original", "jpeg", "png", "tiff"}


@dataclass(frozen=True)
class ConversionOptions:
    """Conversion settings shared by the command line and GTK front end."""

    dpi: float | None = None
    fixed_width: int | None = None
    image_format: str = "original"
    jpeg_quality: int = 90
    grayscale: bool = False
    include_bookmarks: bool = True
    bookmarks_file: Path | None = None

    def __post_init__(self) -> None:
        if self.dpi is not None and self.dpi <= 0:
            raise ValueError("DPI must be greater than zero")
        if self.fixed_width is not None and self.fixed_width <= 0:
            raise ValueError("fixed width must be greater than zero")
        if self.image_format not in IMAGE_FORMATS:
            raise ValueError(f"image format must be one of: {', '.join(sorted(IMAGE_FORMATS))}")
        if not 1 <= self.jpeg_quality <= 100:
            raise ValueError("JPEG quality must be between 1 and 100")


@dataclass(frozen=True)
class Bookmark:
    title: str
    page: int
    level: int = 0


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
    if data.startswith(b"%PDF-"):
        return "pdf"
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


def _render_pdg(path: Path, raw: bytes) -> tuple[bytes, str]:
    width, height = decoder._decode_size_for_pdg(raw)
    decoded, kind = decoder.pdg_decode_pure_bytes(raw, width, height)
    if kind == "djvu":
        executable = shutil.which("ddjvu")
        if not executable:
            raise RuntimeError(
                "This page contains DjVu data. Install DjVuLibre (for example: apt install djvulibre-bin) to render it."
            )
        proc = subprocess.run(
            [executable, "-format=pnm", "-"], input=decoded, capture_output=True, check=False, timeout=120
        )
        if proc.returncode:
            raise RuntimeError(f"ddjvu could not render {path.name}: {proc.stderr.decode(errors='replace').strip()}")
        decoded, kind = proc.stdout, "pnm"
    if kind is None:
        type_byte = raw[15] if len(raw) > 15 else 0
        raise RuntimeError(f"Unsupported or encrypted PDG variant in {path.name} (type 0x{type_byte:02x})")
    return decoded, kind


def _image_bytes(raw: bytes, kind: str, options: ConversionOptions) -> bytes:
    if options.image_format == "original" and not options.grayscale and kind in {"jpeg", "png", "tiff", "bmp"}:
        return raw
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if options.grayscale:
                image = image.convert("L")
            elif kind in {"jpeg", "bmp"} or options.image_format == "jpeg":
                image = image.convert("RGB")
            target = options.image_format if options.image_format != "original" else ("png" if kind == "gif" else kind)
            target = {"jpeg": "JPEG", "png": "PNG", "tiff": "TIFF", "bmp": "BMP"}.get(target, "PNG")
            encoded = io.BytesIO()
            save_kwargs = {}
            if target == "JPEG":
                save_kwargs = {"quality": options.jpeg_quality, "optimize": True}
            elif target == "PNG":
                save_kwargs = {"optimize": True}
            elif target == "TIFF":
                save_kwargs = {"compression": "tiff_lzw"}
            image.save(encoded, format=target, **save_kwargs)
            return encoded.getvalue()
    except (UnidentifiedImageError, OSError) as exc:
        raise RuntimeError("decoded page is not a valid image") from exc


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


def _decode_bookcontents(raw: bytes) -> str:
    for offset in range(len(raw)):
        if raw[offset : offset + 2] not in (b"\x78\x01", b"\x78\x5e", b"\x78\x9c", b"\x78\xda"):
            continue
        try:
            return zlib.decompress(raw[offset:]).decode("gb18030", errors="replace")
        except zlib.error:
            continue
    return ""


def _parse_bookmark_lines(lines: Iterable[str], page_count: int) -> list[Bookmark]:
    result: list[Bookmark] = []
    for line in lines:
        cols = line.rstrip("\r\n").split("|")
        if len(cols) < 3 or not cols[0].strip():
            continue
        try:
            page = int(cols[2], 16)
            level = max(0, int(cols[4])) if len(cols) > 4 and cols[4].isdigit() else 0
        except ValueError:
            continue
        if 0 <= page < page_count:
            result.append(Bookmark(cols[0].strip(), page, level))
    return result


def _read_bookmarks(root: Path, page_count: int, override: Path | None = None) -> list[Bookmark]:
    if override:
        raw = override.read_text(encoding="utf-8-sig")
        if override.suffix.lower() == ".json":
            data = json.loads(raw)
            return [
                Bookmark(str(item["title"]), int(item["page"]), max(0, int(item.get("level", 0))))
                for item in data
                if 0 <= int(item["page"]) < page_count and str(item["title"]).strip()
            ]
        return _parse_bookmark_lines(raw.splitlines(), page_count)
    candidate = next((p for p in root.iterdir() if p.is_file() and p.name.lower() == "bookcontents.dat"), None)
    if not candidate:
        return []
    return _parse_bookmark_lines(_decode_bookcontents(candidate.read_bytes()).splitlines(), page_count)


def write_bookmarks(path: str | Path, bookmarks: Iterable[Bookmark]) -> None:
    target = Path(path).expanduser()
    values = list(bookmarks)
    if target.suffix.lower() == ".json":
        target.write_text(
            json.dumps([{"title": item.title, "page": item.page, "level": item.level} for item in values], ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        return
    target.write_text("\n".join(f"{item.level}|{item.page}|{item.title}" for item in values) + "\n", encoding="utf-8")


def export_bookmarks(source: str | Path, target: str | Path) -> int:
    source = Path(source).expanduser().resolve()
    target = Path(target).expanduser()
    with tempfile.TemporaryDirectory(prefix="pdg2pdf-bookmarks-") as tmp:
        files, root = _collect_pages(source, Path(tmp))
        bookmarks = _read_bookmarks(root, len(files))
    write_bookmarks(target, bookmarks)
    return len(bookmarks)


def _collect_pages(
    source: Path,
    temp: Path,
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[list[Path], Path]:
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
    elif source.is_file() and source.suffix.lower() in ARCHIVE_SUFFIXES:
        raise ValueError(f"Input archive is not a valid ZIP/UVZ file: {source.name}")
    elif source.is_file():
        raise ValueError("Input must be a directory, ZIP or UVZ archive")
    if not root.is_dir():
        raise ValueError(f"Input directory not found: {root}")
    files = []
    if progress:
        progress(0, 0, "正在扫描目录")
    for path in root.rglob("*"):
        if progress:
            progress(0, 0, f"正在扫描：{path.name}")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            files.append(path)
    files.sort(key=_natural_key)
    if not files:
        raise ValueError("No supported image or PDG pages were found")
    return files, root


def _page_width(page: pikepdf.Page) -> float:
    box = page.mediabox
    return float(box[2]) - float(box[0])


def _scale_pages_to_width(pdf: pikepdf.Pdf, target_width: float) -> None:
    for page in pdf.pages:
        box = page.mediabox
        width = float(box[2]) - float(box[0])
        height = float(box[3]) - float(box[1])
        if width <= 0 or abs(width - target_width) < 0.01:
            continue
        scale = target_width / width
        original = page.get("/Contents")
        prefix = pikepdf.Stream(pdf, f"q {scale:.8f} 0 0 {scale:.8f} 0 0 cm\n".encode("ascii"))
        suffix = pikepdf.Stream(pdf, b"Q\n")
        if original is None:
            page.Contents = pikepdf.Array([prefix, suffix])
        elif isinstance(original, pikepdf.Array):
            page.Contents = pikepdf.Array([prefix, *list(original), suffix])
        else:
            page.Contents = pikepdf.Array([prefix, original, suffix])
        new_box = pikepdf.Array([0, 0, target_width, height * scale])
        page.MediaBox = new_box
        page.CropBox = new_box


def convert_book(
    source: str | Path,
    output: str | Path,
    *,
    title: str | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    options: ConversionOptions | None = None,
    dpi: float | None = None,
    fixed_width: int | None = None,
    image_format: str = "original",
    jpeg_quality: int = 90,
    grayscale: bool = False,
    bookmarks_file: str | Path | None = None,
    no_bookmarks: bool = False,
) -> ConversionResult:
    options = options or ConversionOptions(
        dpi=dpi,
        fixed_width=fixed_width,
        image_format=image_format,
        jpeg_quality=jpeg_quality,
        grayscale=grayscale,
        include_bookmarks=not no_bookmarks,
        bookmarks_file=Path(bookmarks_file).expanduser() if bookmarks_file else None,
    )
    source, output = Path(source).expanduser().resolve(), Path(output).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="pdg2pdf-") as tmp:
        files, root = _collect_pages(source, Path(tmp), progress)
        image_widths: list[int] = []
        valid_files: list[tuple[int, Path]] = []
        for index, page in enumerate(files):
            relative_name = str(page.relative_to(root)) if page.is_relative_to(root) else page.name
            if progress:
                progress(0, len(files), f"准备：{relative_name}")
            try:
                raw = page.read_bytes()
                kind = _magic(raw)
                if kind == "pdf":
                    with pikepdf.open(io.BytesIO(raw)) as part:
                        if not part.pages:
                            raise RuntimeError("PDF contains no pages")
                elif kind:
                    image_data, image_kind = raw, kind
                elif raw.startswith(b"HH"):
                    image_data, image_kind = _render_pdg(page, raw)
                else:
                    warnings.append(f"Skipped unrecognized file: {relative_name}")
                    continue
                if kind != "pdf":
                    with Image.open(io.BytesIO(image_data)) as image:
                        image.load()
                        image_widths.append(image.width)
                valid_files.append((index, page))
            except Exception as exc:
                warnings.append(f"Skipped page {relative_name}: failed to inspect: {exc}")
        effective_dpi = options.dpi or (100 if image_widths and max(image_widths) < 1200 else 300)
        info = _read_info(root) if root.is_dir() else {}
        pdf = pikepdf.Pdf.new()
        source_page_map: dict[int, int] = {}
        for index, (source_index, page) in enumerate(valid_files, 1):
            relative_name = str(page.relative_to(root)) if page.is_relative_to(root) else page.name
            page_start = len(pdf.pages)
            try:
                raw = page.read_bytes()
                kind = _magic(raw)
                if kind == "pdf":
                    with pikepdf.open(io.BytesIO(raw)) as part:
                        pdf.pages.extend(part.pages)
                else:
                    if kind:
                        image_data, image_kind = raw, kind
                    elif raw.startswith(b"HH"):
                        image_data, image_kind = _render_pdg(page, raw)
                    else:
                        warnings.append(f"Skipped unrecognized file: {relative_name}")
                        continue
                    image_data = _image_bytes(image_data, image_kind, options)
                    layout = img2pdf.get_fixed_dpi_layout_fun((effective_dpi, effective_dpi))
                    part_bytes = img2pdf.convert(image_data, layout_fun=layout)
                    with pikepdf.open(io.BytesIO(part_bytes)) as part:
                        pdf.pages.extend(part.pages)
                source_page_map[source_index] = page_start
            except Exception as exc:
                if len(pdf.pages) > page_start:
                    del pdf.pages[page_start:]
                warnings.append(f"Skipped page {relative_name}: {exc}")
            if progress:
                progress(index, len(valid_files), relative_name)
        if not pdf.pages:
            details = "; ".join(warnings)
            raise RuntimeError(
                f"No pages could be converted. {details}" if details else "No pages could be converted"
            )

        widths = [_page_width(page) for page in pdf.pages]
        target_width = max(widths)
        if options.fixed_width:
            target_dpi = options.dpi or (100 if options.fixed_width < 1200 else 300)
            target_width = options.fixed_width / target_dpi * 72
        _scale_pages_to_width(pdf, target_width)

        final_title = title or info.get("书名", "").strip() or source.stem
        with pdf.open_metadata() as metadata:
            metadata["dc:title"] = final_title
            author = info.get("作者", "").strip()
            if author:
                metadata["dc:creator"] = [author]
        if options.include_bookmarks and root.is_dir():
            bookmarks = _read_bookmarks(root, len(files), options.bookmarks_file)
            if bookmarks:
                with pdf.open_outline() as outline:
                    stack = [outline.root]
                    for bookmark in bookmarks:
                        target = source_page_map.get(bookmark.page)
                        if target is None:
                            continue
                        level = min(bookmark.level, len(stack) - 1)
                        stack = stack[: level + 1]
                        item = pikepdf.OutlineItem(bookmark.title, target)
                        stack[-1].append(item)
                        stack.append(item.children)
        pdf.save(output)
        page_count = len(pdf.pages)
    return ConversionResult(output, page_count, tuple(warnings))
