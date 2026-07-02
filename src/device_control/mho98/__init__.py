"""Minimum triggered DAQ support for MHO98/RIGOL-like oscilloscopes."""

from .acquisition import RigolScope, WaveformRecord
from .storage import ScopeHDF5Writer

__all__ = ["RigolScope", "ScopeHDF5Writer", "WaveformRecord"]
