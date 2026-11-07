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
