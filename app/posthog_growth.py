"""Read-only, aggregate PostHog activity; no capture, identity export or arbitrary SQL."""
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import APIRouter, Depends

from .config import settings
from .staff_access import require_growth_read
from .services import DomainError

router = APIRouter(prefix="/api/v1/admin/growth", tags=["growth-analytics"])
EVENTS = {
    "page_viewed": "Page views",
    "booking_intent_clicked": "Booking intent",
    "booking_flow_started": "Booking flow started",
    "booking_preview_completed": "Booking preview completed",
    "booking_validation_failed": "Booking validation failures",
    "contact_intent_clicked": "Contact intent",
    "search_used": "Care searches",
}
HOSTS = {"https://us.posthog.com", "https://eu.posthog.com"}


def read_activity(sql: str):
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
        response = client.post(f"{settings.posthog_api_host}/api/projects/{settings.posthog_project_id}/query/",
            headers={"Authorization": "Bearer " + settings.posthog_read_key.get_secret_value()},
            json={"query": {"kind": "HogQLQuery", "query": sql}})
        response.raise_for_status()
        # Do not forward vendor metadata, queries, person IDs or unexpected result fields.
        return response.json()


def normalize_rows(data):
    rows = data.get("results") if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) > len(EVENTS):
        raise ValueError("Unexpected aggregate response")
    output = {key: {"event": key, "label": label, "events": 0, "visitors": 0} for key, label in EVENTS.items()}
    seen = set()
    for row in rows:
        if not isinstance(row, list) or len(row) != 3 or row[0] not in EVENTS or row[0] in seen:
            raise ValueError("Unexpected aggregate response")
        if any(type(value) is not int or value < 0 for value in row[1:]) or row[2] > row[1]:
            raise ValueError("Invalid aggregate counts")
        seen.add(row[0])
        output[row[0]].update(events=row[1], visitors=row[2])
    return list(output.values())


@router.get("/website-activity")
def website_activity(start_date: date | None = None, end_date: date | None = None,
                     traffic: Literal["production", "demo"] = "production",
                     reporting_timezone: str = "Asia/Kolkata", _=Depends(require_growth_read)):
    try:
        tz = ZoneInfo(reporting_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise DomainError("INVALID_TIMEZONE", "Choose a valid reporting timezone.", 422)
    end = end_date or datetime.now(tz).date()
    start = start_date or end - timedelta(days=29)
    if start > end or end == date.max or (end-start).days > 90:
        raise DomainError("INVALID_DATE_RANGE", "Choose an ordered range of at most 91 days for website activity.", 422)
    lower = datetime.combine(start, time.min, tz).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    upper = datetime.combine(end+timedelta(days=1), time.min, tz).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    result = {"provider": "posthog", "status": "disabled", "traffic": traffic, "rows": [],
              "scope": "whole_website", "filters": {"start_date": start, "end_date": end, "timezone": str(tz)},
              "retrieved_at": None, "visitor_to_appointment_conversion": None,
              "limitations": ["Consented visitors only; visitors are anonymous distinct IDs, not patients.",
                              "Counts by event are not an ordered funnel or an appointment conversion rate.",
                              "Frontend booking_preview_completed is a demo preview, not a persisted appointment.",
                              "The current frontend marks all events is_demo=true; production counts may be empty.",
                              "Website activity is global: current events do not provide branch attribution."]}
    if not settings.posthog_growth_enabled:
        return result
    if not settings.posthog_project_id or not settings.posthog_read_key.get_secret_value():
        return {**result, "status": "not_configured"}
    if settings.posthog_api_host not in HOSTS:
        return {**result, "status": "invalid_host"}
    names = ", ".join("'" + key + "'" for key in EVENTS)
    # All values are allowlisted constants or server-validated dates; callers never supply SQL.
    demo = "true" if traffic == "demo" else "false"
    environment = "" if traffic == "demo" else "AND properties.environment = 'production'"
    sql = f"""SELECT event, count() AS events, count(DISTINCT distinct_id) AS visitors
FROM events WHERE event IN ({names}) AND properties.schema_version = 1
AND properties.is_demo = {demo} {environment}
AND timestamp >= toDateTime('{lower}', 'UTC') AND timestamp < toDateTime('{upper}', 'UTC')
GROUP BY event LIMIT {len(EVENTS)}"""
    try:
        rows = normalize_rows(read_activity(sql))
    except (httpx.HTTPError, ValueError, TypeError):
        return {**result, "status": "unavailable"}
    return {**result, "status": "available", "rows": rows, "retrieved_at": datetime.now(timezone.utc)}
