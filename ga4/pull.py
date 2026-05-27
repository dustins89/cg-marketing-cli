"""GA4 Data API pullers — RunReport requests returning lists of dicts.

Each function takes (client, property_id, days, since, limit) and returns rows
the CLI passes to format.emit().

Reference: https://developers.google.com/analytics/devguides/reporting/data/v1/basics
"""
from __future__ import annotations

from datetime import date, timedelta

from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    OrderBy,
    RunReportRequest,
)

from .format import cast_metric


def _date_window(days: int | None, since: str | None) -> tuple[str, str]:
    end = date.today()
    if since:
        start = date.fromisoformat(since)
    else:
        start = end - timedelta(days=days or 30)
    return start.isoformat(), end.isoformat()


def _run(
    client,
    property_id: str,
    dimensions: list[str],
    metrics: list[str],
    days: int | None,
    since: str | None,
    limit: int,
    order_by_metric: str | None = None,
):
    start, end = _date_window(days, since)
    order_by = []
    if order_by_metric:
        order_by = [OrderBy(metric=OrderBy.MetricOrderBy(metric_name=order_by_metric), desc=True)]
    req = RunReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        date_ranges=[DateRange(start_date=start, end_date=end)],
        order_bys=order_by,
        limit=limit,
    )
    resp = client.run_report(req)
    rows = []
    for r in resp.rows:
        row = {}
        for i, d in enumerate(dimensions):
            row[d] = r.dimension_values[i].value
        for i, m in enumerate(metrics):
            row[m] = cast_metric(m, r.metric_values[i].value)
        rows.append(row)
    return rows


def pull_landing_pages(client, property_id, days, since, limit):
    return _run(
        client, property_id,
        dimensions=["landingPage"],
        metrics=["sessions", "screenPageViews", "conversions", "bounceRate", "userEngagementDuration"],
        days=days, since=since, limit=limit,
        order_by_metric="sessions",
    )


def pull_channels(client, property_id, days, since, limit):
    return _run(
        client, property_id,
        dimensions=["sessionDefaultChannelGroup"],
        metrics=["sessions", "conversions", "totalRevenue"],
        days=days, since=since, limit=limit,
        order_by_metric="sessions",
    )


def pull_source_medium(client, property_id, days, since, limit):
    return _run(
        client, property_id,
        dimensions=["sessionSourceMedium"],
        metrics=["sessions", "conversions"],
        days=days, since=since, limit=limit,
        order_by_metric="sessions",
    )


def pull_geo(client, property_id, days, since, limit):
    return _run(
        client, property_id,
        dimensions=["city", "region"],
        metrics=["sessions", "conversions"],
        days=days, since=since, limit=limit,
        order_by_metric="sessions",
    )


def pull_devices(client, property_id, days, since, limit):
    return _run(
        client, property_id,
        dimensions=["deviceCategory"],
        metrics=["sessions", "conversions"],
        days=days, since=since, limit=limit,
        order_by_metric="sessions",
    )


def pull_conversions_by_page(client, property_id, days, since, limit):
    return _run(
        client, property_id,
        dimensions=["landingPage", "eventName"],
        metrics=["eventCount", "conversions"],
        days=days, since=since, limit=limit,
        order_by_metric="conversions",
    )


def pull_events(client, property_id, days, since, limit):
    return _run(
        client, property_id,
        dimensions=["eventName"],
        metrics=["eventCount", "eventValue"],
        days=days, since=since, limit=limit,
        order_by_metric="eventCount",
    )


COLUMNS = {
    "landing-pages": ["landingPage", "sessions", "screenPageViews", "conversions",
                      "bounceRate", "userEngagementDuration"],
    "channels": ["sessionDefaultChannelGroup", "sessions", "conversions", "totalRevenue"],
    "source-medium": ["sessionSourceMedium", "sessions", "conversions"],
    "geo": ["city", "region", "sessions", "conversions"],
    "devices": ["deviceCategory", "sessions", "conversions"],
    "conversions-by-page": ["landingPage", "eventName", "eventCount", "conversions"],
    "events": ["eventName", "eventCount", "eventValue"],
    "key-events": ["event_name", "counting_method", "create_time", "name"],
}


# ─── Admin API: key events (formerly conversions) ─────────────────────────────

def list_key_events(admin_service, property_id: str) -> list[dict]:
    parent = f"properties/{property_id}"
    resp = admin_service.properties().keyEvents().list(parent=parent).execute()
    return [_key_event_row(e) for e in resp.get("keyEvents", [])]


def create_key_event(admin_service, property_id: str, event_name: str,
                     counting_method: str = "ONCE_PER_EVENT") -> dict:
    parent = f"properties/{property_id}"
    body = {"eventName": event_name, "countingMethod": counting_method}
    created = admin_service.properties().keyEvents().create(parent=parent, body=body).execute()
    return _key_event_row(created)


def _key_event_row(e: dict) -> dict:
    return {
        "name": e.get("name"),
        "event_name": e.get("eventName"),
        "counting_method": e.get("countingMethod"),
        "create_time": e.get("createTime"),
    }


# ─── Realtime API ────────────────────────────────────────────────────────────

def pull_realtime(client, property_id: str, dimensions: list[str] | None = None,
                 metrics: list[str] | None = None, limit: int = 100) -> list[dict]:
    """Real-time report — events from the last 30 minutes (no date range)."""
    from google.analytics.data_v1beta.types import RunRealtimeReportRequest
    dims = dimensions or ["unifiedScreenName", "country"]
    mets = metrics or ["activeUsers", "screenPageViews", "eventCount"]
    req = RunRealtimeReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name=d) for d in dims],
        metrics=[Metric(name=m) for m in mets],
        limit=limit,
    )
    resp = client.run_realtime_report(req)
    rows = []
    for r in resp.rows:
        row = {}
        for i, d in enumerate(dims):
            row[d] = r.dimension_values[i].value
        for i, m in enumerate(mets):
            row[m] = cast_metric(m, r.metric_values[i].value)
        rows.append(row)
    return rows


# ─── Pivot Report ────────────────────────────────────────────────────────────

def pull_pivot(client, property_id: str, row_dim: str, col_dim: str,
              metric: str, days: int | None, since: str | None,
              limit: int = 100) -> list[dict]:
    """2D pivot — rows × columns × metric.

    Example: row_dim='sessionSource', col_dim='landingPage', metric='conversions'.
    """
    from google.analytics.data_v1beta.types import (
        RunPivotReportRequest, Pivot
    )
    start, end = _date_window(days, since)
    req = RunPivotReportRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name=row_dim), Dimension(name=col_dim)],
        metrics=[Metric(name=metric)],
        date_ranges=[DateRange(start_date=start, end_date=end)],
        pivots=[
            Pivot(field_names=[row_dim], limit=limit),
            Pivot(field_names=[col_dim], limit=limit),
        ],
    )
    resp = client.run_pivot_report(req)
    rows = []
    for r in resp.rows:
        rows.append({
            row_dim: r.dimension_values[0].value,
            col_dim: r.dimension_values[1].value,
            metric: cast_metric(metric, r.metric_values[0].value),
        })
    return rows


# ─── Batch Reports ───────────────────────────────────────────────────────────

def batch_run(client, property_id: str, queries: list[dict]) -> list[list[dict]]:
    """Run multiple reports in a single round-trip.

    queries: list of dicts with keys `dimensions`, `metrics`, `days`/`since`, `limit`,
    `order_by_metric` (optional). Returns parallel list of row lists.
    """
    from google.analytics.data_v1beta.types import BatchRunReportsRequest
    reqs = []
    for q in queries:
        start, end = _date_window(q.get("days"), q.get("since"))
        order_by = []
        if q.get("order_by_metric"):
            order_by = [OrderBy(
                metric=OrderBy.MetricOrderBy(metric_name=q["order_by_metric"]),
                desc=True,
            )]
        reqs.append(RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[Dimension(name=d) for d in q["dimensions"]],
            metrics=[Metric(name=m) for m in q["metrics"]],
            date_ranges=[DateRange(start_date=start, end_date=end)],
            order_bys=order_by,
            limit=q.get("limit", 100),
        ))
    batch_req = BatchRunReportsRequest(
        property=f"properties/{property_id}",
        requests=reqs,
    )
    resp = client.batch_run_reports(batch_req)
    results = []
    for i, r in enumerate(resp.reports):
        dims = queries[i]["dimensions"]
        mets = queries[i]["metrics"]
        rows = []
        for row in r.rows:
            d = {}
            for j, dn in enumerate(dims):
                d[dn] = row.dimension_values[j].value
            for j, mn in enumerate(mets):
                d[mn] = cast_metric(mn, row.metric_values[j].value)
            rows.append(d)
        results.append(rows)
    return results


# ─── Funnel Report (preview) ─────────────────────────────────────────────────

def pull_funnel(client, property_id: str, steps: list[dict],
               days: int | None, since: str | None,
               dimension: str | None = None) -> list[dict]:
    """Funnel report — sequential step abandonment.

    `steps` is a list of {name, event} pairs; each step matches when `event_name = event`.
    Optional `dimension` (e.g. 'deviceCategory') splits the funnel.

    NOTE: Funnel is a preview/Alpha feature — server may return UNIMPLEMENTED.
    """
    from google.analytics.data_v1beta.types import (
        RunFunnelReportRequest, Funnel, FunnelStep,
        FunnelFilterExpression, FunnelEventFilter,
    )
    start, end = _date_window(days, since)
    funnel_steps = []
    for s in steps:
        funnel_steps.append(FunnelStep(
            name=s["name"],
            filter_expression=FunnelFilterExpression(
                funnel_event_filter=FunnelEventFilter(event_name=s["event"]),
            ),
        ))
    req = RunFunnelReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        funnel=Funnel(steps=funnel_steps),
        funnel_breakdown=({"breakdown_dimension": Dimension(name=dimension)}
                          if dimension else None),
    )
    resp = client.run_funnel_report(req)
    out = []
    if resp.funnel_visualization:
        for row in resp.funnel_visualization.rows:
            entry = {}
            for i, dv in enumerate(row.dimension_values):
                entry[resp.funnel_visualization.dimension_headers[i].name] = dv.value
            for i, mv in enumerate(row.metric_values):
                entry[resp.funnel_visualization.metric_headers[i].name] = mv.value
            out.append(entry)
    return out


# ─── Metadata API ────────────────────────────────────────────────────────────

def get_metadata(client, property_id: str) -> dict:
    """Discover available dimensions + metrics (including custom ones) for a property."""
    from google.analytics.data_v1beta.types import GetMetadataRequest
    req = GetMetadataRequest(name=f"properties/{property_id}/metadata")
    resp = client.get_metadata(req)
    return {
        "dimensions": [
            {
                "api_name": d.api_name,
                "ui_name": d.ui_name,
                "description": d.description,
                "category": d.category,
                "custom_definition": d.custom_definition,
            }
            for d in resp.dimensions
        ],
        "metrics": [
            {
                "api_name": m.api_name,
                "ui_name": m.ui_name,
                "description": m.description,
                "type": m.type_.name if m.type_ else None,
                "category": m.category,
                "custom_definition": m.custom_definition,
            }
            for m in resp.metrics
        ],
    }


# ─── checkCompatibility ──────────────────────────────────────────────────────

def check_compatibility(client, property_id: str, dimensions: list[str],
                       metrics: list[str]) -> dict:
    """Verify that a set of dimensions + metrics are compatible before running a report."""
    from google.analytics.data_v1beta.types import CheckCompatibilityRequest
    req = CheckCompatibilityRequest(
        property=f"properties/{property_id}",
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
    )
    resp = client.check_compatibility(req)
    return {
        "dimension_compatibilities": [
            {"name": dc.dimension_metadata.api_name,
             "compatibility": dc.compatibility.name}
            for dc in resp.dimension_compatibilities
        ],
        "metric_compatibilities": [
            {"name": mc.metric_metadata.api_name,
             "compatibility": mc.compatibility.name}
            for mc in resp.metric_compatibilities
        ],
    }


# ─── Audience Exports (Admin API) ────────────────────────────────────────────

def list_audience_exports(admin_service, property_id: str) -> list[dict]:
    """List existing audience export snapshots for the property."""
    parent = f"properties/{property_id}"
    resp = admin_service.properties().audienceExports().list(parent=parent).execute()
    return [{
        "name": a.get("name"),
        "audience": a.get("audience"),
        "audience_display_name": a.get("audienceDisplayName"),
        "state": a.get("state"),
        "begin_creating_time": a.get("beginCreatingTime"),
        "creation_quota_tokens_charged": a.get("creationQuotaTokensCharged"),
        "row_count": a.get("rowCount"),
        "error_message": a.get("errorMessage"),
    } for a in resp.get("audienceExports", [])]


def create_audience_export(admin_service, property_id: str, audience_resource: str,
                          dimensions: list[str] | None = None) -> dict:
    """Kick off an audience export snapshot. Audience resource = 'properties/X/audiences/Y'."""
    parent = f"properties/{property_id}"
    body = {
        "audience": audience_resource,
        "dimensions": [{"dimensionName": d}
                       for d in (dimensions or ["deviceId"])],
    }
    return admin_service.properties().audienceExports().create(
        parent=parent, body=body
    ).execute()


def list_audiences(admin_service, property_id: str) -> list[dict]:
    """List audiences defined on the property (sources for audience exports)."""
    parent = f"properties/{property_id}"
    resp = admin_service.properties().audiences().list(parent=parent).execute()
    return [{
        "name": a.get("name"),
        "display_name": a.get("displayName"),
        "description": (a.get("description") or "")[:200],
        "membership_duration_days": a.get("membershipDurationDays"),
        "ads_personalization_enabled": a.get("adsPersonalizationEnabled"),
        "create_time": a.get("createTime"),
    } for a in resp.get("audiences", [])]


# ─── BigQuery export helper ──────────────────────────────────────────────────

def bq_export_settings(admin_service, property_id: str) -> list[dict]:
    """List BigQuery export links configured on the property.

    Surfaces dataset names + which streams are exported. Doesn't query BQ itself —
    use a BQ client (or the gads CLI's pattern) for that.
    """
    parent = f"properties/{property_id}"
    resp = admin_service.properties().bigQueryLinks().list(parent=parent).execute()
    return [{
        "name": b.get("name"),
        "project": b.get("project"),
        "dataset_location": b.get("datasetLocation"),
        "create_time": b.get("createTime"),
        "daily_export_enabled": b.get("dailyExportEnabled"),
        "streaming_export_enabled": b.get("streamingExportEnabled"),
        "fresh_daily_export_enabled": b.get("freshDailyExportEnabled"),
        "include_advertising_id": b.get("includeAdvertisingId"),
        "excluded_events": ", ".join(b.get("excludedEvents") or []),
        "export_streams": ", ".join(b.get("exportStreams") or []),
    } for b in resp.get("bigqueryLinks", [])]


# Extend COLUMNS with the new commands
COLUMNS.update({
    "realtime": ["unifiedScreenName", "country", "activeUsers",
                 "screenPageViews", "eventCount"],
    "pivot": [],  # built dynamically — caller passes row_dim/col_dim/metric
    "funnel": [],  # dynamic
    "audiences": ["display_name", "membership_duration_days",
                  "ads_personalization_enabled", "create_time", "name"],
    "audience-exports": ["audience_display_name", "state", "row_count",
                         "begin_creating_time", "creation_quota_tokens_charged",
                         "error_message", "name"],
    "bq-exports": ["project", "dataset_location", "daily_export_enabled",
                   "streaming_export_enabled", "fresh_daily_export_enabled",
                   "create_time", "name"],
    "metadata-dimensions": ["api_name", "ui_name", "category", "custom_definition"],
    "metadata-metrics": ["api_name", "ui_name", "type", "category", "custom_definition"],
    "compatibility": ["name", "compatibility"],
})
