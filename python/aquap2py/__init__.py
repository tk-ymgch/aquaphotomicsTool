"""aquap2py: an explicit R-free numerical port, not full R API compatibility."""
from .core import SpectralData, classic_aquagram, gdmm, getcm, pca, ttap
from .preprocessing import msc, preprocess, sgolay, snv

__version__ = "0.1.0"
__all__ = ["SpectralData", "ttap", "preprocess", "snv", "msc", "sgolay", "pca",
           "classic_aquagram", "gdmm", "getcm", "__version__"]
