"""aquap2py: an explicit R-free numerical port, not full R API compatibility."""
from .core import SpectralData, classic_aquagram, gdmm, getcm, pca, ttap
from .preprocessing import msc, preprocess, preprocess_spectra, sgolay, snv, detrend, emsc, gap_derivative, resample_nir
from .temperature import temperature_calibration, temperature_aquagram
from .plsr import plsr, predict_plsr, plsr_outlier_indices

__version__ = "0.3.1"
__all__ = ["SpectralData", "ttap", "preprocess", "snv", "msc", "sgolay", "pca",
           "classic_aquagram", "temperature_calibration", "temperature_aquagram", "plsr", "predict_plsr", "gdmm", "getcm", "preprocess_spectra", "detrend", "emsc", "gap_derivative", "resample_nir", "plsr_outlier_indices", "__version__"]
