from datetime import date

import pytest

from climate_attention.models import CollectionRequest, QuerySpec, Topic
from climate_attention.sources import GoogleTrendsProvider, ProviderUnavailableError


def test_google_trends_fails_with_official_api_guidance():
    request = CollectionRequest(
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
        topics=[Topic(id="climate", label="Climate", queries=[QuerySpec(expression="climate")])],
    )
    with pytest.raises(ProviderUnavailableError, match="Official Google Trends API"):
        GoogleTrendsProvider().collect(request)

