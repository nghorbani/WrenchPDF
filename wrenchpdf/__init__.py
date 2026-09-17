"""pdf_creator package."""

from ._version import version as __version__
from .app import run  # type: ignore

__all__ = ["run", "__version__"]
