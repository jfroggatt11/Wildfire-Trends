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


def test_confirmed_gdelt_outage_is_missing_not_zero():
    rows = _attention_rows()
    for day in (date(2025, 6, 14), date(2025, 7, 1)):
        for topic in ("climate_change", "electric_vehicles"):
            for geography in ("italy", "france", "brazil"):
                rows.append(
                    {
                        "date": day,
                        "source": "gdelt_ngrams",
                        "topic_id": topic,
                        "geography": geography,
                        "matched_count": 0,
                        "political_count": 0,
                    }
                )
    payload = build_event_study(
        [_event("gap", "flood", "Orange", date(2025, 6, 14), date(2025, 6, 15), ["italy"])],
        rows,
    )

    effect = next(
        row for row in payload["effects"]
        if row["scope"] == "affected"
        and row["topicId"] == "climate_change"
        and row["windowDays"] == 7
        and row["timing"] == "onset"
    )
    assert effect["complete"] is False
    assert effect["missingDays"] >= 7
    assert payload["coverage"]["excludedPeriods"][0]["start"] == "2025-06-14"
    assert not any(
        row["observationDate"] in {"2025-06-14", "2025-07-01"}
        for row in build_daily_attention_regions(rows)
    )


def _effect(payload, event_id, window=7, timing='onset', scope='affected'):
    return next(row for row in payload['effects'] if row['eventId'] == event_id
                and row['scope'] == scope and row['topicId'] == 'climate_change'
                and row['windowDays'] == window and row['timing'] == timing)


def test_windows_cross_year_boundaries_and_overlap_policy_is_fixed():
    rows = _attention_rows()
    events = [
        _event('january', 'flood', 'Orange', date(2025, 1, 4), date(2025, 1, 4), ['italy']),
        _event('previous', 'flood', 'Red', date(2024, 12, 30), date(2025, 1, 5), ['italy']),
        _event('green', 'wildfire', 'Green', date(2025, 2, 1), date(2025, 2, 2), ['france']),
        _event('major', 'flood', 'Orange', date(2025, 2, 1), date(2025, 2, 2), ['france']),
    ]
    major = build_event_study(iter(events), rows)
    all_alerts = build_event_study(events, rows, alerts={'Green', 'Orange', 'Red'})
    assert _effect(major, 'january')['complete'] is True
    assert _effect(major, 'january')['overlap'] is True
    assert _effect(major, 'major')['overlap'] is False  # Green is not contamination under this policy.
    assert _effect(all_alerts, 'major') == _effect(major, 'major')
    assert _effect(all_alerts, 'green')['overlap'] is True
    assert major['coverage']['start'] == '2025-01-01'


def test_unsupported_and_absent_affected_markets_are_incomplete_but_real_zeros_are_valid():
    rows = _attention_rows()
    for row in rows:
        if row['geography'] == 'italy':
            row['metadata_json'] = '{"country_mapping_supported": false}'
            row['matched_count'] = row['political_count'] = 0
        elif row['geography'] == 'france':
            row['matched_count'] = row['political_count'] = 0
    events = [_event(name, 'flood', 'Orange', date(2025, 2, 1), date(2025, 2, 2), countries)
              for name, countries in [('mixed', ['italy', 'brazil']), ('absent', ['missing', 'brazil']), ('zero', ['france'])]]
    study = build_event_study(events, rows)
    assert _effect(study, 'mixed')['complete'] is False
    assert _effect(study, 'absent')['complete'] is False
    assert _effect(study, 'mixed')['unsupportedGeographyIds'] == ['italy']
    assert _effect(study, 'zero')['complete'] is True
    assert _effect(study, 'zero')['matchedPreMean'] == 0
    assert _effect(study, 'mixed', scope='global')['complete'] is True
    assert study['coverage']['geographies'] == 2
    assert study['coverage']['unsupportedGeographies'] == ['italy']


def test_partial_markets_and_duplicate_rows_do_not_create_complete_regional_totals():
    rows = _attention_rows()
    rows = [row for row in rows if not (row['geography'] == 'brazil' and row['date'] == date(2025, 2, 1))]
    events = [_event('event', 'flood', 'Orange', date(2025, 2, 1), date(2025, 2, 2), ['italy'])]
    study = build_event_study(events, rows + rows)
    assert _effect(study, 'event')['complete'] is True
    assert _effect(study, 'event', scope='global')['complete'] is False
    regions = build_daily_attention_regions(rows + rows)
    assert not any(row['regionId'] == 'global' and row['observationDate'] == '2025-02-01' for row in regions)
    eu = next(row for row in regions if row['regionId'] == 'eu27' and row['observationDate'] == '2025-02-01' and row['topicId'] == 'climate_change')
    assert eu['matchedCount'] == 40


def test_loader_preserves_mapping_flags_and_full_post_event_window(tmp_path):
    import pyarrow as pa
    from climate_attention.event_study import load_event_study_inputs
    path = tmp_path / 'events/source=gdacs/events.parquet'
    path.parent.mkdir(parents=True)
    events = [_event('event', 'flood', 'Orange', date(2025, 12, 25), date(2026, 2, 1), ['italy'])]
    pq.write_table(pa.Table.from_pylist(events), path)
    path = tmp_path / 'trends/source=gdelt_ngrams/topic_id=climate_change/geography=italy/language=all/daily.parquet'
    path.parent.mkdir(parents=True)
    rows = [{**_attention_rows()[0], 'date': date(2026, 2, 20),
             'political_actor_count': 0, 'government_action_count': 0, 'party_politics_count': 0,
             'official_source_count': 0, 'metadata_json': '{"country_mapping_supported": false}'}]
    pq.write_table(pa.Table.from_pylist(rows), path)
    _, loaded = load_event_study_inputs(tmp_path, study_year=2025)
    assert loaded[0]['date'] == date(2026, 2, 20)
    assert loaded[0]['country_mapping_supported'] is False
    assert 'metadata_json' not in loaded[0]


def test_warehouse_builds_do_not_overwrite_another_year(tmp_path, monkeypatch):
    from climate_attention.event_study import build_analysis_warehouse
    events = [_event('event', 'wildfire', 'Orange', date(2025, 2, 1), date(2025, 2, 2), ['italy'])]
    monkeypatch.setattr('climate_attention.event_study.load_event_study_inputs', lambda *args, **kwargs: (events, _attention_rows()))
    first = build_analysis_warehouse(data_dir=tmp_path, study_year=2025)
    original = first['effectPath'].read_bytes()
    second = build_analysis_warehouse(data_dir=tmp_path, study_year=2026)
    assert first['effectPath'] != second['effectPath']
    assert first['effectPath'].read_bytes() == original
