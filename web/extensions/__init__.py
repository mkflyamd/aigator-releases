"""Extension adapter framework — used by the agentic setup wizard."""
from .base import (
    ExtensionAdapter, ExtensionType, TestResult, InstallResult, FieldUpdate,
)
from .registry import get_adapter, KNOWN_TYPES

__all__ = [
    "ExtensionAdapter", "ExtensionType", "TestResult", "InstallResult",
    "FieldUpdate", "get_adapter", "KNOWN_TYPES",
]
