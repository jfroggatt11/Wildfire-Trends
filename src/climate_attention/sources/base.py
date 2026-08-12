"""Common provider interface and errors."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import CollectionRequest, ProviderResult, TrendProviderResult


class ProviderError(RuntimeError):
    """Base class for an explicit provider failure."""


class ProviderUnavailableError(ProviderError):
    """Raised when a provider is intentionally not configured."""


class ProviderCollectionError(ProviderError):
    """A failed run that may contain successfully collected partial data."""

    def __init__(
        self, message: str, result: ProviderResult | TrendProviderResult
    ):
        super().__init__(message)
        self.result = result


class AttentionProvider(ABC):
    name: str

    @abstractmethod
    def collect(self, request: CollectionRequest) -> ProviderResult:
        """Collect observations, raising on incomplete collection."""

        raise NotImplementedError

    def close(self) -> None:
        """Release provider resources."""

    def __enter__(self) -> "AttentionProvider":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
