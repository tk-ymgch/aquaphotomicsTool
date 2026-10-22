"""aquap2py: an explicit R-free numerical port, not full R API compatibility."""
from .core import SpectralData, classic_aquagram, gdmm, getcm, pca, ttap
from .preprocessing import msc, preprocess, sgolay, snv
from .temperature import temperature_calibration, temperature_aquagram
from .plsr import plsr, predict_plsr

__version__ = "0.2.0"
__all__ = ["SpectralData", "ttap", "preprocess", "snv", "msc", "sgolay", "pca",
           "classic_aquagram", "temperature_calibration", "temperature_aquagram", "plsr", "predict_plsr", "gdmm", "getcm", "__version__"]
