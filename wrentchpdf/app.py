"""Gradio application wiring for the PDF creator UI."""

from __future__ import annotations

import contextlib
from pathlib import Path
import html
from typing import Any, Dict, Iterable, List, Sequence

import gradio as gr
from gradio.utils import NamedString

from wrentchpdf.tempfiles import TempFileTracker, remove_temp_path
from wrentchpdf.version import version as APP_VERSION
from wrentchpdf.utils import (
    InvalidImageError,
    PageAsset,
    assets_to_pdf_bytes,
    image_to_page_asset,
    is_supported_image,
    is_supported_pdf,
    persist_pdf,
    pdf_to_page_assets,
    sanitize_filename,
)

APP_TITLE = "WrenchPDF - Offline PDF Editor"
APP_TAGLINE = "Merge, reorder, and compress PDFs locally with complete privacy."
DEFAULT_COMPRESSION_LEVEL = "Medium"
COMPRESSION_LEVELS: Dict[str, int | None] = {
    "No compression": None,
    "Medium": 85,
    "Aggressive": 70,
}
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
FAVICON_PATH = ASSETS_DIR / "favicon.png"


def _load_favicon_data_uri() -> str | None:
    if not FAVICON_PATH.exists():
        return None
    try:
        import base64

        encoded = base64.b64encode(FAVICON_PATH.read_bytes()).decode("ascii")
        mime = "image/png" if FAVICON_PATH.suffix.lower() == ".png" else "image/x-icon"
        return f"data:{mime};base64,{encoded}"
    except OSError:
        return None


FAVICON_DATA_URI = _load_favicon_data_uri()
CSS = """
#page-gallery .gallery img { width: 120px !important; height: auto; }
#page-gallery .grid-container { gap: 0.25rem !important; }
#page-gallery button[aria-label="preview"] { cursor: zoom-in; }
.tip-text { font-size: 0.85rem; color: var(--body-text-color-subdued); }
.status-text { min-height: 1.2rem; }
#file-uploader .file { cursor: grab; user-select: none; }
#file-uploader .file:active { cursor: grabbing; }
#file-uploader .file td { cursor: inherit; }
#file-uploader .file.drop-target[data-drop-target="after"] { border-bottom: 2px solid var(--color-primary-500); }
#file-uploader .file.drop-target[data-drop-target="before"] { border-top: 2px solid var(--color-primary-500); }
#file-uploader .file .filename { user-select: none; pointer-events: none; }
#file-uploader .file .download { pointer-events: none; }
#file-uploader .file .download a { pointer-events: auto; cursor: pointer; }
#file-uploader .label-clear-button { pointer-events: auto; cursor: pointer; }
#file-uploader .drag-handle { display: none; }
#auto-download { opacity: 0; height: 0; width: 0; pointer-events: none; }
.app-header { display: inline-flex; align-items: center; gap: 0.4rem; margin-bottom: 0.5rem; }
.app-header img { height: 44px; width: auto; display: block; }
.app-title { font-size: 2rem; font-weight: 600; margin: 0; display: inline-flex; align-items: baseline; gap: 0.5rem; }
.app-tagline { font-size: 1rem; color: var(--body-text-color-subdued); margin: 0; }
.app-version { font-size: 1rem; font-weight: 500; color: var(--body-text-color-subdued); }
#action-button a,
#action-button button {
    width: 100%;
}
#action-button.download-ready {
    --button-secondary-fill: #16a34a;
    --button-secondary-fill-hover: #15803d;
    --button-secondary-border: #15803d;
    --button-secondary-border-hover: #166534;
    --button-secondary-text: #ffffff;
}
#action-button.download-ready button,
#action-button.download-ready a {
    background: #16a34a !important;
    border-color: #15803d !important;
    background-image: none !important;
    color: #ffffff !important;
}
"""


def _ensure_sequence(files: Any) -> Sequence[Any]:
    if files is None:
        return []
    if isinstance(files, (str, Path)):
        return [files]
    if isinstance(files, Sequence):
        return files
    return [files]


def _extract_path_and_name(uploaded: Any) -> tuple[Path | None, str | None]:
    if uploaded is None:
        return None, None
    if isinstance(uploaded, Path):
        return uploaded, uploaded.name
    if isinstance(uploaded, dict):  # Gradio FileData payload
        path_str = uploaded.get("path")
        if not path_str:
            return None, None
        display = uploaded.get("orig_name") or Path(path_str).name
        return Path(path_str), display
    if isinstance(uploaded, str):
        name_attr = getattr(uploaded, "name", None)
        return Path(uploaded), name_attr or Path(uploaded).name
    path_str = getattr(uploaded, "name", None) or getattr(uploaded, "path", None)
    if path_str is None:
        return None, None
    display = (
        getattr(uploaded, "orig_name", None)
        or getattr(uploaded, "label", None)
        or getattr(uploaded, "name", None)
    )
    return Path(path_str), display


def _asset_to_named_string(asset: PageAsset) -> NamedString:
    file_ref = NamedString(str(asset.preview_path))
    file_ref.name = asset.display_name
    return file_ref


def _build_gallery_payload(assets: Sequence[PageAsset]) -> List[tuple]:
    items: List[tuple] = []
    for index, asset in enumerate(assets, start=1):
        caption = f"{index}. {asset.display_name}"
        items.append((str(asset.preview_path), caption))
    return items


def _cleanup_temp(
    path: str | Path | None, *, temp_tracker: TempFileTracker | None = None
) -> None:
    if not path:
        return
    if temp_tracker is not None:
        temp_tracker.discard(path, remove=True)
    else:
        remove_temp_path(path)


def _cleanup_assets(
    assets: Iterable[PageAsset],
    *,
    temp_tracker: TempFileTracker | None = None,
) -> None:
    for asset in assets:
        if asset.temp_preview:
            if temp_tracker is not None:
                temp_tracker.discard(asset.preview_path, remove=True)
            else:
                remove_temp_path(asset.preview_path)


def _format_status(message: str, success: bool = True) -> str:
    icon = "✅" if success else "⚠️"
    return f"{icon} {message}"


def _resolve_compression(level: str | None) -> tuple[bool, int]:
    value = COMPRESSION_LEVELS.get(level, COMPRESSION_LEVELS[DEFAULT_COMPRESSION_LEVEL])
    if value is None:
        return False, 85
    return True, value


def _reconcile_assets(
    files: Any,
    current_assets: Sequence[PageAsset] | None,
    *,
    temp_tracker: TempFileTracker | None = None,
) -> tuple[List[PageAsset], List[NamedString], List[PageAsset]]:
    existing_assets = list(current_assets or [])
    current_map: Dict[str, PageAsset] = {
        str(asset.preview_path): asset for asset in existing_assets
    }
    ordered_assets: List[PageAsset] = []
    component_files: List[NamedString] = []

    for uploaded in _ensure_sequence(files):
        path, display_name = _extract_path_and_name(uploaded)
        if path is None:
            continue
        key = str(path)
        if key in current_map:
            asset = current_map.pop(key)
            ordered_assets.append(asset)
            component_files.append(_asset_to_named_string(asset))
            continue

        if is_supported_image(path):
            asset = image_to_page_asset(path, display_name=display_name)
            ordered_assets.append(asset)
            component_files.append(_asset_to_named_string(asset))
        elif is_supported_pdf(path):
            new_pages = pdf_to_page_assets(path, temp_tracker=temp_tracker)
            ordered_assets.extend(new_pages)
            component_files.extend(_asset_to_named_string(page) for page in new_pages)
        else:
            raise InvalidImageError(
                f"Unsupported file '{path.name}'. Please add images or PDF documents."
            )

    removed_assets = list(current_map.values())
    return ordered_assets, component_files, removed_assets


def _handle_files(
    files: Any,
    current_assets: Sequence[PageAsset] | None = None,
    current_pdf: str | None = None,
    temp_tracker: TempFileTracker | None = None,
):
    if temp_tracker is None:
        temp_tracker = TempFileTracker()

    if current_pdf:
        _cleanup_temp(current_pdf, temp_tracker=temp_tracker)

    try:
        assets, component_files, removed = _reconcile_assets(
            files, current_assets, temp_tracker=temp_tracker
        )
    except InvalidImageError as exc:
        existing_assets = list(current_assets or [])
        gallery_payload = _build_gallery_payload(existing_assets)
        return (
            gr.update(
                value=[_asset_to_named_string(asset) for asset in existing_assets] or None
            ),
            existing_assets,
            gr.update(value=gallery_payload or None, visible=bool(gallery_payload)),
            gr.update(
                value=None,
                label="Create PDF",
                variant="primary",
                elem_classes=[],
                interactive=True,
            ),
            _format_status(str(exc), success=False),
            current_pdf,
            temp_tracker,
        )

    _cleanup_assets(removed, temp_tracker=temp_tracker)

    if not assets:
        return (
            gr.update(value=None, visible=False),
            [],
            gr.update(value=None, visible=False),
            gr.update(
                value=None,
                label="Create PDF",
                variant="primary",
                elem_classes=[],
                interactive=True,
            ),
            _format_status("Upload images or PDFs to get started."),
            None,
            temp_tracker,
        )

    gallery_payload = _build_gallery_payload(assets)
    pages_count = len(assets)
    status = _format_status(
        f"Loaded {pages_count} page{'s' if pages_count != 1 else ''}. Drag rows on the left to reorder, click thumbnails to preview."
    )
    return (
        gr.update(value=component_files or None, visible=True),
        assets,
        gr.update(value=gallery_payload, visible=True),
        gr.update(
            value=None,
            label="Create PDF",
            variant="primary",
            elem_classes=[],
            interactive=True,
        ),
        status,
        None,
        temp_tracker,
    )


def _handle_upload(
    files: Any,
    current_assets: Sequence[PageAsset] | None = None,
    current_pdf: str | None = None,
    temp_tracker: TempFileTracker | None = None,
):
    if not files:
        return (
            gr.update(value=None),
            gr.update(),
            current_assets or [],
            gr.update(),
            gr.update(
                value=None,
                label="Create PDF",
                variant="primary",
                elem_classes=[],
                interactive=True,
            ),
            gr.update(),
            current_pdf,
            temp_tracker or TempFileTracker(),
        )

    existing_tokens = [
        _asset_to_named_string(asset) for asset in (current_assets or [])
    ]
    combined_inputs = existing_tokens + list(_ensure_sequence(files))

    (
        pages_update,
        assets,
        gallery_update,
        download_update,
        status,
        pdf_token,
        temp_tracker,
    ) = _handle_files(
        combined_inputs,
        current_assets=current_assets,
        current_pdf=current_pdf,
        temp_tracker=temp_tracker,
    )

    return (
        gr.update(value=None),
        pages_update,
        assets,
        gallery_update,
        download_update,
        status,
        pdf_token,
        temp_tracker,
    )


def _handle_convert(
    assets: Sequence[PageAsset],
    desired_name: str,
    compression_level: str,
    previous_pdf: str | None,
    temp_tracker: TempFileTracker | None,
):
    tracker = temp_tracker or TempFileTracker()
    if previous_pdf:
        path = Path(previous_pdf)
        if path.exists():
            _cleanup_temp(path, temp_tracker=tracker)
            message = _format_status(
                f"Ready to create another PDF after downloading '{path.name}'."
            )
            return (
                gr.update(
                    value=None,
                    label="Create PDF",
                    variant="primary",
                    elem_classes=[],
                    interactive=True,
                ),
            message,
            None,
            tracker,
        )
        # previous path missing, reset gracefully
        return (
            gr.update(
                value=None,
                label="Create PDF",
                variant="primary",
                elem_classes=[],
                interactive=True,
            ),
            _format_status("Previous PDF no longer available. Generate a new one."),
            None,
            tracker,
        )

    if not assets:
        return (
            gr.update(
                value=None,
                label="Create PDF",
                variant="primary",
                elem_classes=[],
                interactive=True,
            ),
            _format_status("Add at least one page before converting.", success=False),
            previous_pdf,
            tracker,
        )
    target_name = sanitize_filename(desired_name or "output.pdf")
    try:
        compress, quality = _resolve_compression(compression_level)
        pdf_bytes = assets_to_pdf_bytes(
            assets, compress=compress, compression_quality=quality
        )
    except InvalidImageError as exc:
        return (
            gr.update(
                value=None,
                label="Create PDF",
                variant="primary",
                elem_classes=[],
                interactive=True,
            ),
            _format_status(str(exc), success=False),
            previous_pdf,
            tracker,
        )
    pdf_path = persist_pdf(pdf_bytes, filename=target_name, temp_tracker=tracker)
    if previous_pdf and previous_pdf != str(pdf_path):
        _cleanup_temp(previous_pdf, temp_tracker=tracker)
    message = _format_status(
        f"Created '{target_name}' with {len(assets)} page{'s' if len(assets) != 1 else ''}."
    )
    return (
        gr.update(
            value=str(pdf_path),
            label="Download PDF",
            variant="secondary",
            elem_classes=["download-ready"],
            interactive=True,
        ),
        message,
        str(pdf_path),
        tracker,
    )


def _handle_clear(
    current_assets: Sequence[PageAsset],
    current_pdf: str | None,
    temp_tracker: TempFileTracker | None,
):
    tracker = temp_tracker or TempFileTracker()
    assets_list = list(current_assets) if current_assets else []
    assets_removed = len(assets_list)
    pdf_removed = 1 if current_pdf else 0
    _cleanup_assets(assets_list, temp_tracker=tracker)
    _cleanup_temp(current_pdf, temp_tracker=tracker)
    tracker.cleanup()
    removed_parts: list[str] = []
    removed_parts.append(
        f"{assets_removed} document{'s' if assets_removed != 1 else ''}"
    )
    if pdf_removed:
        removed_parts.append("the generated PDF")
    removed_summary = " and ".join(removed_parts)
    status_message = _format_status(
        f"Removed {removed_summary}. All contents have been cleared."
    )
    with contextlib.suppress(Exception):  # non-blocking toast for user feedback
        gr.Info(status_message)
    status_update = gr.update(value=status_message)
    return (
        gr.update(value=None),
        gr.update(value=None, visible=False),
        [],
        gr.update(value=None, visible=False),
        gr.update(
            value=None,
            label="Create PDF",
            variant="primary",
            elem_classes=[],
            interactive=True,
        ),
        status_update,
        None,
        gr.update(value=DEFAULT_COMPRESSION_LEVEL, interactive=True),
        tracker,
    )


def build_interface() -> gr.Blocks:
    with gr.Blocks(title=APP_TITLE, css=CSS, fill_height=True) as demo:
        pages_state = gr.State([])
        pdf_state = gr.State(None)
        temp_tracker_state = gr.State(None)

        logo_html = "<div class='app-header'>"
        if FAVICON_DATA_URI:
            logo_html += (
                f"<img src='{FAVICON_DATA_URI}' alt='WrenchPDF logo' width='44' height='44'>"
            )
        version_badge = f"<span class='app-version'>v{html.escape(APP_VERSION)}</span>"
        logo_html += (
            "<div>"
            f"<span class='app-title'>WrenchPDF {version_badge}</span>"
            f"<p class='app-tagline'>{APP_TAGLINE}</p>"
            "</div>"
        )
        logo_html += "</div>"
        gr.HTML(logo_html)

        gr.Markdown(
            """
            1. Use **Add images / PDFs** to upload files in batches.
            2. Reorder or remove individual pages in *Current pages*.
            3. Click a thumbnail to open a larger overlay preview.
            4. Name your PDF and hit **Create PDF**.
            """
        )

        with gr.Row():
            with gr.Column(scale=1, min_width=260):
                upload_input = gr.File(
                    label="Add images / PDFs",
                    file_count="multiple",
                    file_types=["image", ".pdf"],
                    interactive=True,
                    elem_id="add-files",
                )
                pages_input = gr.File(
                    label="Current pages",
                    file_count="multiple",
                    interactive=True,
                    allow_reordering=True,
                    elem_id="file-uploader",
                    visible=False,
                )
                gr.Markdown(
                    "Drop new files above. Drag rows below to reorder or remove with ✕.",
                    elem_classes=["tip-text"],
                )
            with gr.Column(scale=2):
                gallery = gr.Gallery(
                    label="Page order preview",
                    allow_preview=True,
                    show_label=True,
                    elem_id="page-gallery",
                    columns=[6, 4, 3],
                    height="auto",
                )

        with gr.Row():
            filename_input = gr.Textbox(
                label="PDF filename",
                value="MyDocument.pdf",
                placeholder="e.g. trip-photos.pdf",
            )
            compression_level = gr.Radio(
                label="Compression level",
                choices=list(COMPRESSION_LEVELS.keys()),
                value=DEFAULT_COMPRESSION_LEVEL,
            )

        with gr.Row():
            download = gr.DownloadButton(
                label="Create PDF",
                value=None,
                variant="primary",
                elem_id="action-button",
            )
            clear_btn = gr.Button("Clear", variant="secondary")

        status = gr.Markdown(elem_classes=["status-text"])

        pages_input.change(
            fn=_handle_files,
            inputs=[pages_input, pages_state, pdf_state, temp_tracker_state],
            outputs=[
                pages_input,
                pages_state,
                gallery,
                download,
                status,
                pdf_state,
                temp_tracker_state,
            ],
        )

        upload_input.change(
            fn=_handle_upload,
            inputs=[upload_input, pages_state, pdf_state, temp_tracker_state],
            outputs=[
                upload_input,
                pages_input,
                pages_state,
                gallery,
                download,
                status,
                pdf_state,
                temp_tracker_state,
            ],
        )

        download.click(
            fn=_handle_convert,
            inputs=[
                pages_state,
                filename_input,
                compression_level,
                pdf_state,
                temp_tracker_state,
            ],
            outputs=[download, status, pdf_state, temp_tracker_state],
        )

        clear_btn.click(
            fn=_handle_clear,
            inputs=[pages_state, pdf_state, temp_tracker_state],
            outputs=[
                upload_input,
                pages_input,
                pages_state,
                gallery,
                download,
                status,
                pdf_state,
                compression_level,
                temp_tracker_state,
            ],
        )

    return demo


def run(**launch_kwargs):
    """Launch the Gradio interface."""
    app = build_interface()
    if FAVICON_PATH.exists():
        launch_kwargs.setdefault("favicon_path", str(FAVICON_PATH))
    app.launch(**launch_kwargs)
