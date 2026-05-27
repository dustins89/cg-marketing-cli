"""LSA pullers — search account-level reports for leads + detailed lead reports."""
from __future__ import annotations

from datetime import date, timedelta


def _date_param(prefix: str, d: date) -> dict:
    return {
        f"{prefix}_year": d.year,
        f"{prefix}_month": d.month,
        f"{prefix}_day": d.day,
    }


def pull_account_reports(svc, customer_id: str, days: int = 30) -> list[dict]:
    """Account-level performance reports (one row per day)."""
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days)
    params = {
        "query": f"manager_customer_id:{customer_id}",
    }
    params.update(_date_param("startDate", start))
    params.update(_date_param("endDate", end))
    rows = []
    page_token = None
    while True:
        if page_token:
            params["pageToken"] = page_token
        resp = svc.accountReports().search(**params).execute()
        for r in resp.get("accountReports", []):
            rows.append({
                "date": r.get("currentPeriodMetrics", {}).get("date"),
                "accountId": r.get("accountId"),
                "businessName": r.get("businessName"),
                "totalLeads": r.get("currentPeriodMetrics", {}).get("totalLeadsCount"),
                "answeredCalls": r.get("currentPeriodMetrics", {}).get("answeredCallsCount"),
                "phoneLeads": r.get("currentPeriodMetrics", {}).get("phoneLeadsCount"),
                "messageLeads": r.get("currentPeriodMetrics", {}).get("messageLeadsCount"),
                "bookingLeads": r.get("currentPeriodMetrics", {}).get("bookingLeadsCount"),
                "totalReviews": r.get("currentPeriodMetrics", {}).get("totalReviewsCount"),
                "averageFiveStarRating": r.get("currentPeriodMetrics", {}).get("averageFiveStarRating"),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return rows


def pull_detailed_leads(svc, customer_id: str, days: int = 30) -> list[dict]:
    """Detailed lead-level reports for the lookback window."""
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days)
    params = {
        "query": f"manager_customer_id:{customer_id}",
    }
    params.update(_date_param("startDate", start))
    params.update(_date_param("endDate", end))
    rows = []
    page_token = None
    while True:
        if page_token:
            params["pageToken"] = page_token
        resp = svc.detailedLeadReports().search(**params).execute()
        for r in resp.get("detailedLeadReports", []):
            rows.append({
                "leadId": r.get("leadId"),
                "leadCreationTimestamp": r.get("leadCreationTimestamp"),
                "leadType": r.get("leadType"),
                "leadCategory": r.get("leadCategory"),
                "leadPrice": r.get("leadPrice"),
                "businessName": r.get("businessName"),
                "accountId": r.get("accountId"),
                "geo": r.get("geo"),
                "disputeStatus": r.get("disputeStatus"),
                "currencyCode": r.get("currencyCode"),
                "timeZone": (r.get("timezone") or {}).get("id"),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return rows


COLUMNS = {
    "account": ["date", "accountId", "businessName", "totalLeads", "phoneLeads", "messageLeads", "bookingLeads", "averageFiveStarRating"],
    "leads": ["leadId", "leadCreationTimestamp", "leadType", "leadCategory", "leadPrice", "businessName", "disputeStatus"],
}
