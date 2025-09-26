"""pdf_creator package."""

from .app import run  # type: ignore
from ._version import version as __version__

__all__ = ["run", "__version__"]
