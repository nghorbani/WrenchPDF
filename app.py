"""Hugging Face entrypoint for the WrentchPDF Gradio app."""

from __future__ import annotations

import os

from wrentchpdf.app import run


def main() -> None:
    """Launch the Gradio interface on the port expected by Hugging Face."""
    port = int(os.environ.get("PORT", "7860"))
    run(server_name="0.0.0.0", server_port=port)


if __name__ == "__main__":
    main()
