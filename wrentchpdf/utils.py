"""Utility functions for preparing image inputs and generating PDF output."""

from __future__ import annotations

import io
import re
import tempfile
import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, TYPE_CHECKING
from uuid import uuid4

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader, PdfWriter

from wrentchpdf.tempfiles import register_temp_path

if TYPE_CHECKING:  # pragma: no cover - imported for type hints only
    from wrentchpdf.tempfiles import TempFileTracker

SUPPORTED_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
}

SUPPORTED_PDF_EXTENSIONS = {".pdf"}
PDF_PREVIEW_SCALE = 2.0


@dataclass(slots=True)
class PageAsset:
    """Represents a single page that can be arranged in the UI."""

    id: str
    kind: str  # "image" | "pdf"
    source_path: Path
    display_name: str
    preview_path: Path
    page_index: int = 0
    temp_preview: bool = False


class InvalidImageError(Exception):
    """Raised when an uploaded file cannot be processed as an image."""


def sanitize_filename(raw: str, default: str = "output.pdf") -> str:
    """Return a safe filename with `.pdf` suffix ensured."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    if not cleaned:
        cleaned = Path(default).stem
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned


def is_supported_image(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def is_supported_pdf(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_PDF_EXTENSIONS


def _compress_image(image: Image.Image, quality: int = 80) -> Image.Image:
    buffer = io.BytesIO()
    try:
        image.save(buffer, format="JPEG", optimize=True, quality=quality)
        buffer.seek(0)
        compressed = Image.open(buffer)
        compressed.load()
        result = compressed.convert("RGB")
        compressed.close()
        return result
    finally:
        buffer.close()


def load_image_for_pdf(path: Path, *, compress: bool = True, quality: int = 80) -> Image.Image:
    """Load an image suitable for PDF concatenation."""
    try:
        with Image.open(path) as img:
            converted = img.convert("RGB") if img.mode != "RGB" else img.copy()
    except (OSError, ValueError) as exc:
        raise InvalidImageError(f"Unable to open '{path.name}' as an image.") from exc
    if compress:
        compressed = _compress_image(converted, quality=quality)
        converted.close()
        return compressed
    return converted


def image_to_page_asset(path: Path, display_name: str | None = None) -> PageAsset:
    if not is_supported_image(path):
        raise InvalidImageError(
            f"Unsupported file type for '{path.name}'. Allowed: {', '.join(sorted(SUPPORTED_IMAGE_EXTENSIONS))}."
        )
    return PageAsset(
        id=str(uuid4()),
        kind="image",
        source_path=path,
        display_name=display_name or path.name,
        preview_path=path,
        page_index=0,
        temp_preview=False,
    )


def pdf_to_page_assets(
    path: Path, *, temp_tracker: "TempFileTracker" | None = None
) -> List[PageAsset]:
    if not is_supported_pdf(path):
        raise InvalidImageError("Please upload PDF files with a .pdf extension.")

    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception as exc:  # pragma: no cover
        raise InvalidImageError(f"Unable to render '{path.name}' for preview.") from exc

    assets: List[PageAsset] = []
    try:
        total_pages = len(doc)
        for page_index in range(total_pages):
            page = doc.get_page(page_index)
            bitmap = page.render(scale=PDF_PREVIEW_SCALE)
            pil_image = bitmap.to_pil()
            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".png",
                prefix=f"{path.stem}_p{page_index + 1}_",
            ) as tmp:
                pil_image.save(tmp, format="PNG")
                preview_path = Path(tmp.name)
            if temp_tracker is not None:
                temp_tracker.add(preview_path)
            else:
                register_temp_path(preview_path)
            pil_image.close()
            bitmap.close()
            page.close()
            display_name = f"{path.stem} — Page {page_index + 1}"
            assets.append(
                PageAsset(
                    id=str(uuid4()),
                    kind="pdf",
                    source_path=path,
                    display_name=display_name,
                    preview_path=preview_path,
                    page_index=page_index,
                    temp_preview=True,
                )
            )
    finally:
        doc.close()

    return assets


def _image_asset_to_reader(
    asset: PageAsset, *, compress: bool, quality: int
) -> PdfReader:
    buffer = io.BytesIO()
    image_obj: Image.Image | None = None
    try:
        with Image.open(asset.source_path) as img:
            rgb_image = img.convert("RGB") if img.mode != "RGB" else img.copy()
        image_obj = rgb_image
        if compress:
            compressed = _compress_image(rgb_image, quality=quality)
            rgb_image.close()
            image_obj = compressed
        image_obj.save(buffer, format="PDF")
        image_obj.close()
    except (OSError, ValueError) as exc:
        if image_obj is not None:
            with contextlib.suppress(Exception):
                image_obj.close()
        raise InvalidImageError(
            f"Unable to process '{asset.source_path.name}' for PDF conversion."
        ) from exc
    buffer.seek(0)
    reader = PdfReader(buffer)
    setattr(reader, "_pdf_creator_buffer", buffer)
    return reader


def assets_to_pdf_bytes(
    assets: Sequence[PageAsset], *, compress: bool = True, compression_quality: int = 80
) -> bytes:
    if not assets:
        raise InvalidImageError("Please add at least one page before converting to PDF.")

    writer = PdfWriter()
    pdf_cache: dict[Path, PdfReader] = {}
    auxiliary_readers: List[PdfReader] = []

    for asset in assets:
        if asset.kind == "pdf":
            reader = pdf_cache.get(asset.source_path)
            if reader is None:
                reader = PdfReader(str(asset.source_path))
                pdf_cache[asset.source_path] = reader
                auxiliary_readers.append(reader)
            writer.add_page(reader.pages[asset.page_index])
        elif asset.kind == "image":
            reader = _image_asset_to_reader(
                asset, compress=compress, quality=compression_quality
            )
            auxiliary_readers.append(reader)
            writer.add_page(reader.pages[0])
        else:  # pragma: no cover - safeguard for unexpected kinds
            raise InvalidImageError(f"Unsupported page type '{asset.kind}'.")

    output = io.BytesIO()
    writer.write(output)
    writer.close()
    output.seek(0)
    return output.read()


def persist_pdf(
    bytes_payload: bytes,
    filename: str | Path | None = None,
    *,
    temp_tracker: "TempFileTracker" | None = None,
) -> Path:
    """Persist a PDF payload to a temporary file suitable for downloading."""
    suffix = ".pdf"
    name = Path(filename or "output.pdf").stem
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix=f"{name}_") as tmp:
        tmp.write(bytes_payload)
        path = Path(tmp.name)
    if temp_tracker is not None:
        temp_tracker.add(path)
    else:
        register_temp_path(path)
    return path
