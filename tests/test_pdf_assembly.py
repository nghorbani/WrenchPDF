"""Tests for assembling a PDF from page assets: merging images with PDF pages and honouring the page order."""

import io
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
import pytest

from wrenchpdf.utils import InvalidImageError, PageAsset, assets_to_pdf_bytes, image_to_page_asset, pdf_to_page_assets


def _write_image(path: Path, size: tuple[int, int], color: str) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


def _write_pdf(path: Path, page_sizes: list[tuple[float, float]]) -> Path:
    writer = PdfWriter()
    for width, height in page_sizes:
        writer.add_blank_page(width=width, height=height)
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _page_sizes(pdf_bytes: bytes) -> list[tuple[int, int]]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [(round(float(page.mediabox.width)), round(float(page.mediabox.height))) for page in reader.pages]


def test_merge_image_and_pdf_pages_into_one_document(tmp_path):
    image = _write_image(tmp_path / "photo.png", (120, 80), "red")
    pdf = _write_pdf(tmp_path / "doc.pdf", [(200, 300), (400, 500)])

    assets = [image_to_page_asset(image), *pdf_to_page_assets(pdf)]
    merged = assets_to_pdf_bytes(assets, compress=False)

    assert len(PdfReader(io.BytesIO(merged)).pages) == 3
    assert _page_sizes(merged)[1:] == [(200, 300), (400, 500)]


def test_page_order_follows_the_asset_order(tmp_path):
    image = _write_image(tmp_path / "photo.png", (120, 80), "blue")
    pdf = _write_pdf(tmp_path / "doc.pdf", [(200, 300), (400, 500)])
    first_pdf_page, second_pdf_page = pdf_to_page_assets(pdf)

    natural = assets_to_pdf_bytes([image_to_page_asset(image), first_pdf_page, second_pdf_page], compress=False)
    reordered = assets_to_pdf_bytes([second_pdf_page, image_to_page_asset(image), first_pdf_page], compress=False)

    natural_sizes = _page_sizes(natural)
    reordered_sizes = _page_sizes(reordered)
    assert natural_sizes[1:] == [(200, 300), (400, 500)]
    assert reordered_sizes[0] == (400, 500)
    assert reordered_sizes[1] == natural_sizes[0]  # the image page moved to the middle
    assert reordered_sizes[2] == (200, 300)


def test_pdf_pages_become_one_asset_each_in_order(tmp_path):
    pdf = _write_pdf(tmp_path / "doc.pdf", [(200, 300), (400, 500), (600, 700)])

    assets = pdf_to_page_assets(pdf)

    assert [asset.page_index for asset in assets] == [0, 1, 2]
    assert all(asset.kind == "pdf" and isinstance(asset, PageAsset) for asset in assets)
    assert all(asset.source_path == pdf for asset in assets)


def test_empty_selection_is_rejected():
    with pytest.raises(InvalidImageError):
        assets_to_pdf_bytes([])
