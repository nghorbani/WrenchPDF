---
title: WrenchPDF
emoji: 🔧
colorFrom: blue
colorTo: yellow
sdk: gradio
sdk_version: "4.19.1"
app_file: app.py
pinned: false
---

# WrenchPDF — Offline PDF Editor (merge • reorder • compress)

WrenchPDF is a **local, privacy-first PDF editor**. Combine images/PDFs, **drag-to-reorder pages**, set filename, and export—**no uploads, no tracking**.

Simple desktop-hosted web UI for assembling a single PDF from a mix of images and existing PDF documents.

**Keywords:** pdf editor, merge pdf, reorder pages, compress pdf, offline, local, open-source, gradio


<p align="center">
  <img src="wrentchpdf/assets/screenshot.png" alt="WrentchPDF application screenshot" width="600" />
</p>

<a href="https://huggingface.co/spaces/nghorbani/wrentchpdf" title="Open the Hugging Face demo" target="_blank">
  <img src="https://img.shields.io/badge/Gradio%20Demo-Hugging%20Face-%23ff8c00?logo=huggingface&logoColor=white" alt="Hugging Face demo badge" />
</a>

## Gradio Interface

The app runs on a single `gr.Blocks` layout with:
- **Header badge** showing the project name and current version.
- **File uploader** that accepts mixed images/PDFs and exposes drag-to-reorder controls.
- **Thumbnail gallery** with clickable previews for every page in the assembled document.
- **Compression selector** with presets for no compression, medium, and aggressive optimization.
- **Auto-download button** that saves the merged PDF locally without ever leaving the browser session.

## Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) for dependency management (recommended)

## Installation

```bash
uv sync
```

This installs runtime dependencies (`gradio`, `Pillow`, `pypdf`, `pypdfium2`) into a local virtual environment.

## Running the app

Launch the Gradio server with either command:

```bash
uv run runserver
# or
uv run python main.py
```

After the server starts, open the printed local URL (typically http://127.0.0.1:7860/) in your browser.

## Workflow

1. Open the browser UI.
2. Use **Add images / PDFs** to upload one or more batches of files.
   - Images are accepted as pages.
   - PDF uploads are expanded automatically into individual pages.
3. Fine-tune the order in **Current pages** by dragging rows or removing any unwanted page with the ✕ icon.
4. Inspect page thumbnails via the gallery preview (click for full overlay).
5. Set the output name in **PDF filename**.
6. Pick a compression setting (No compression / Medium / Aggressive) to balance quality and size.
7. Press **Create PDF** – the combined PDF downloads automatically once ready and a status message confirms the result.

## Features

- Drag-and-drop upload for mixed images and multi-page PDFs
- Automatic PDF page expansion with per-page reorder and delete controls
- Compact thumbnail gallery with overlay preview
- Sanitised output filename input
- Selectable compression levels with auto-download on completion
- Persistent temporary cleanup to avoid leftover files

## License

WrenchPDF is released under the [Apache License 2.0](LICENSE). Use it freely in personal and commercial projects with attribution.

## Development scripts

- Format/lint: `uv run ruff .`
- The project currently relies on manual testing (recommended cases: single image, multi-image reorder, PDF + image mix, aggressive compression).

## Notes

- The app keeps work in memory; very large batches may require further optimisation.
- Auto-download is triggered via a hidden button in the UI—most browsers will show the standard download prompt.
