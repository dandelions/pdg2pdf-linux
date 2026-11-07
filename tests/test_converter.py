from __future__ import annotations

import zipfile
from pathlib import Path

import pikepdf
import pytest

from pdg2pdf.converter import convert_book

ROOT = Path(__file__).parent
SAMPLES = ROOT / "test_data"


def test_real_sample_directory_converts_all_page_types(tmp_path):
    result = convert_book(SAMPLES, tmp_path / "book.pdf")
    assert result.page_count == 16
    with pikepdf.open(result.output) as pdf:
        assert len(pdf.pages) == 16
        assert str(pdf.docinfo.Title).startswith("华北地方")
        with pdf.open_outline() as outline:
            assert outline.root
            assert outline.root[0].title.startswith("第一章")


def test_zip_input_converts(tmp_path):
    archive = tmp_path / "book.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in SAMPLES.iterdir():
            if path.is_file():
                zf.write(path, path.name)
    result = convert_book(archive, tmp_path / "from-zip.pdf")
    assert result.page_count == 16


def test_zip_traversal_is_rejected(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.pdg", b"not an image")
    with pytest.raises(RuntimeError, match="unsafe path"):
        convert_book(archive, tmp_path / "unsafe.pdf")
    assert not (tmp_path / "escape.pdg").exists()


def test_single_image_input_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="directory or a ZIP"):
        convert_book(SAMPLES / "cov001.jpg", tmp_path / "single.pdf")


def test_pages_share_the_maximum_width(tmp_path):
    from PIL import Image

    source = tmp_path / "mixed"
    source.mkdir()
    Image.new("RGB", (600, 900), "white").save(source / "000001.jpg")
    Image.new("RGB", (900, 600), "gray").save(source / "000002.jpg")
    result = convert_book(source, tmp_path / "mixed.pdf", fixed_width=1200, dpi=300)
    with pikepdf.open(result.output) as pdf:
        widths = [float(page.mediabox[2]) - float(page.mediabox[0]) for page in pdf.pages]
        assert widths == pytest.approx([288.0, 288.0])


def test_pdf_named_pdg_is_preserved_and_scaled(tmp_path):
    from PIL import Image

    source = tmp_path / "text"
    source.mkdir()
    pdf_path = source / "000001.pdf"
    Image.new("RGB", (500, 700), "white").save(pdf_path, format="PDF", resolution=150)
    (source / "000002.pdg").write_bytes(pdf_path.read_bytes())
    result = convert_book(source, tmp_path / "text-out.pdf", fixed_width=1000, dpi=200)
    assert result.page_count == 2
    with pikepdf.open(result.output) as pdf:
        widths = [float(page.mediabox[2]) - float(page.mediabox[0]) for page in pdf.pages]
        assert widths == pytest.approx([360.0, 360.0])


def test_bookmark_json_override_and_export(tmp_path):
    import json
    from pdg2pdf.converter import export_bookmarks

    bookmarks = tmp_path / "bookmarks.json"
    export_bookmarks(SAMPLES, bookmarks)
    data = json.loads(bookmarks.read_text(encoding="utf-8"))
    assert data[0]["title"].startswith("第一章")
    data[0]["title"] = "Edited"
    bookmarks.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    convert_book(SAMPLES, tmp_path / "edited.pdf", bookmarks_file=bookmarks)
    with pikepdf.open(tmp_path / "edited.pdf") as pdf:
        with pdf.open_outline() as outline:
            assert outline.root[0].title == "Edited"
