"""Exceptions used by the strategy layer."""


class StrategyLayerError(Exception):
    """Base strategy layer exception."""


class ManifestValidationError(StrategyLayerError):
    """Raised when a strategy manifest is invalid."""
