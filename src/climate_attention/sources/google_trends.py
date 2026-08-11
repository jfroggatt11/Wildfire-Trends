"""Placeholder for Google's official Trends API."""

from __future__ import annotations

from ..models import CollectionRequest, ProviderResult
from .base import AttentionProvider, ProviderUnavailableError


class GoogleTrendsProvider(AttentionProvider):
    name = "google_trends"

    def collect(self, request: CollectionRequest) -> ProviderResult:
        del request
        raise ProviderUnavailableError(
            "Google Trends collection is not available yet. Official Google Trends "
            "API access and credentials are required; this project deliberately does "
            "not use pytrends or unofficial scraping."
        )

