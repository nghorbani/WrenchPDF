"""Console entry point for launching the WrentchPDF Gradio app."""

from __future__ import annotations

import argparse
from typing import Sequence

from wrentchpdf.app import run


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch the WrentchPDF Gradio interface."
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        dest="port",
        help="Port to bind the HTTP server to (default chosen by Gradio).",
    )
    parser.add_argument(
        "--host",
        "--listen",
        dest="host",
        help="Host/IP address for the HTTP server (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--share",
        action="store_true",
        help="Enable Gradio sharing (public tunnel).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)

    launch_kwargs = {}
    if args.host:
        launch_kwargs["server_name"] = args.host
    if args.port is not None:
        launch_kwargs["server_port"] = args.port
    if args.share:
        launch_kwargs["share"] = True

    run(**launch_kwargs)


if __name__ == "__main__":  # pragma: no cover
    main()
