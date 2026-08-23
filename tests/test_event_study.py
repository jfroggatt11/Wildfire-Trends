from datetime import date, datetime, timedelta, timezone

import pyarrow.parquet as pq
import pytest

from climate_attention.event_study import (
    build_daily_attention_regions,
    build_daily_event_activity,
    build_event_study,
    write_event_study,
)


def _event(event_id, hazard, alert, start, end, countries):
    return {
        "record_id": event_id,
        "hazard_type": hazard,
        "alert_level": alert,
        "alert_score": 2.0,
        "name": event_id,
        "start_at": datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
        "end_at": datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc),
        "geography_ids": countries,
    }


def _attention_rows():
    rows = []
    event_start = date(2025, 2, 1)
    for offset in range(-35, 36):
        day = event_start + timedelta(days=offset)
        for topic in ("climate_change", "electric_vehicles"):
            for geography in ("italy", "france", "brazil"):
                baseline = 10 if topic == "climate_change" else 2
                matched = baseline * (2 if offset >= 0 else 1)
                political = matched * (0.3 if offset >= 0 else 0.2)
                rows.append(
                    {
                        "date": day,
                        "source": "gdelt_ngrams",
                        "topic_id": topic,
                        "geography": geography,
                        "matched_count": matched,
                        "political_count": political,
                    }
                )
    return rows


def test_event_study_builds_both_topics_and_mutually_exclusive_scopes():
    events = [
        _event("major", "wildfire", "Orange", date(2025, 2, 1), date(2025, 2, 2), ["italy"]),
        _event("green", "flood", "Green", date(2025, 2, 1), date(2025, 2, 2), ["france"]),
        _event("cyclone", "tropical_cyclone", "Red", date(2025, 2, 1), date(2025, 2, 2), ["brazil"]),
    ]

    payload = build_event_study(events, _attention_rows())

    assert [event["id"] for event in payload["events"]] == ["major"]
    assert payload["topics"] == ["climate_change", "electric_vehicles"]
    assert payload["scopes"] == ["affected", "other_eu27", "rest_world", "global"]
    effect = next(
        row for row in payload["effects"]
        if row["eventId"] == "major"
        and row["scope"] == "affected"
        and row["topicId"] == "electric_vehicles"
        and row["windowDays"] == 7
        and row["timing"] == "onset"
    )
    assert effect["complete"] is True
    assert effect["overlap"] is False
    assert effect["matchedPreMean"] == 2
    assert effect["matchedPostMean"] == 4
    assert effect["matchedPercentChange"] == 100
    assert effect["politicalSharePre"] == 20
    assert effect["politicalSharePost"] == 30
    assert effect["politicalShareChange"] == pytest.approx(10)


def test_event_study_flags_same_country_overlaps():
    events = [
        _event("first", "flood", "Orange", date(2025, 2, 1), date(2025, 2, 2), ["italy"]),
        _event("second", "wildfire", "Red", date(2025, 2, 5), date(2025, 2, 6), ["italy"]),
    ]

    payload = build_event_study(events, _attention_rows())
    selected = [
        row for row in payload["effects"]
        if row["eventId"] == "first"
        and row["scope"] == "affected"
        and row["topicId"] == "climate_change"
        and row["windowDays"] == 7
        and row["timing"] == "onset"
    ]

    assert len(selected) == 1
    assert selected[0]["overlap"] is True


def test_political_share_remains_missing_when_topic_denominator_is_zero():
    rows = _attention_rows()
    for row in rows:
        if row["geography"] == "italy" and row["date"] < date(2025, 2, 1):
            row["matched_count"] = 0
            row["political_count"] = 0
    payload = build_event_study(
        [_event("major", "wildfire", "Orange", date(2025, 2, 1), date(2025, 2, 2), ["italy"])],
        rows,
    )
    effect = next(
        row for row in payload["effects"]
        if row["scope"] == "affected"
        and row["topicId"] == "climate_change"
        and row["windowDays"] == 7
        and row["timing"] == "onset"
    )

    assert effect["politicalSharePre"] is None
    assert effect["politicalShareChange"] is None


def test_event_study_writes_parquet_and_browser_json(tmp_path):
    payload = build_event_study(
        [_event("major", "wildfire", "Orange", date(2025, 2, 1), date(2025, 2, 2), ["italy"])],
        _attention_rows(),
    )
    parquet_path = tmp_path / "event_effects.parquet"
    json_path = tmp_path / "event-study.json"

    write_event_study(payload, parquet_path=parquet_path, json_path=json_path)

    assert json_path.exists()
    assert pq.read_table(parquet_path).num_rows == len(payload["effects"])


def test_daily_event_activity_counts_country_exposure_and_regions_once():
    events = [
        _event(
            "multi-country",
            "flood",
            "Green",
            date(2025, 2, 1),
            date(2025, 2, 3),
            ["italy", "france"],
        )
    ]

    rows = build_daily_event_activity(events)

    global_start = next(
        row for row in rows
        if row["geography"] == "__global__" and row["activityDate"] == "2025-02-01"
    )
    eu_start = next(
        row for row in rows
        if row["geography"] == "__eu27__" and row["activityDate"] == "2025-02-01"
    )
    italy_middle = next(
        row for row in rows
        if row["geography"] == "italy" and row["activityDate"] == "2025-02-02"
    )
    assert global_start["eventsStarted"] == 1
    assert eu_start["eventsStarted"] == 1
    assert italy_middle["eventsActive"] == 1
    assert italy_middle["eventsStarted"] == 0


def test_daily_attention_regions_sum_global_and_eu_without_inventing_shares():
    rows = [
        {
            "date": date(2025, 2, 1),
            "source": "gdelt_ngrams",
            "topic_id": "climate_change",
            "geography": "italy",
            "matched_count": 10,
            "political_count": 2,
        },
        {
            "date": date(2025, 2, 1),
            "source": "gdelt_ngrams",
            "topic_id": "climate_change",
            "geography": "brazil",
            "matched_count": 30,
            "political_count": 3,
        },
    ]

    result = build_daily_attention_regions(rows)

    global_row = next(row for row in result if row["regionId"] == "global")
    eu_row = next(row for row in result if row["regionId"] == "eu27")
    assert global_row["matchedCount"] == 40
    assert global_row["politicalShare"] == 12.5
    assert eu_row["matchedCount"] == 10
    assert eu_row["politicalShare"] == 20
