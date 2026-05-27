"""Ingest Salesforce KPIs + funnel snapshots into Neon.

Sources:
  - `Marketing_KPI_Line_Items__c` for Monthly_Spend__c, Projected_Revenue__c, etc.
  - `Lead` for funnel counts (Lead → Qualified → Appointment → Contract → Closed)
    keyed by LeadSource per day.

Auth: JWT bearer flow. Re-uses the SF connected app pattern from the lender-
portal repo. Requires env: SF_INSTANCE_URL, SF_CLIENT_ID, SF_USERNAME,
SF_PRIVATE_KEY (PEM).
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
from collections import defaultdict

import jwt
import requests
from simple_salesforce import Salesforce

from ingest.core import Row, run_logger, write_rows, neon_conn

PLATFORM = "sf"
LOOKBACK_DAYS_DEFAULT = 60


def sf_client() -> Salesforce:
    """Build a simple_salesforce client via JWT bearer flow."""
    inst = os.environ["SF_INSTANCE_URL"].rstrip("/")
    cid = os.environ["SF_CLIENT_ID"]
    user = os.environ["SF_USERNAME"]
    pkey = os.environ["SF_PRIVATE_KEY"].replace("\\n", "\n")

    payload = {
        "iss": cid,
        "sub": user,
        "aud": "https://login.salesforce.com",
        "exp": int(time.time()) + 300,
    }
    assertion = jwt.encode(payload, pkey, algorithm="RS256")
    resp = requests.post(
        "https://login.salesforce.com/services/oauth2/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion,
        },
        timeout=30,
    )
    resp.raise_for_status()
    tok = resp.json()
    return Salesforce(instance_url=tok["instance_url"], session_id=tok["access_token"])


def pull_funnel_daily(sf: Salesforce, days: int) -> list[Row]:
    """Per-day lead counts by funnel stage, broken down by LeadSource."""
    start_dt = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    # SOQL: counts of Leads by CreatedDate (DAY_ONLY) + LeadSource.
    # Funnel stages live on Lead via dates: Date_Lead_Qualified__c,
    # Date_Lead_Unqualified__c, etc. Adjust field names to actual API names.
    soql_leads = f"""
        SELECT DAY_ONLY(CreatedDate) day, LeadSource source, COUNT(Id) cnt
        FROM Lead
        WHERE CreatedDate >= {start_dt}T00:00:00Z
        GROUP BY DAY_ONLY(CreatedDate), LeadSource
    """
    # Date_Lead_Qualified__c is a DateTime field — use DAY_ONLY + datetime literal
    soql_qualified = f"""
        SELECT DAY_ONLY(Date_Lead_Qualified__c) day, LeadSource source, COUNT(Id) cnt
        FROM Lead
        WHERE Date_Lead_Qualified__c >= {start_dt}T00:00:00Z
        GROUP BY DAY_ONLY(Date_Lead_Qualified__c), LeadSource
    """
    # ConvertedDate is a Date field (not DateTime), so DAY_ONLY() doesn't apply
    # and the literal is a plain date.
    soql_converted = f"""
        SELECT ConvertedDate day, LeadSource source, COUNT(Id) cnt
        FROM Lead
        WHERE ConvertedDate >= {start_dt} AND IsConverted = true
        GROUP BY ConvertedDate, LeadSource
    """

    rows: list[Row] = []
    for query, metric in [
        (soql_leads,     "leads_count"),
        (soql_qualified, "qualified_count"),
        (soql_converted, "converted_count"),
    ]:
        try:
            result = sf.query_all(query)
        except Exception as e:
            print(f"sf {metric} query failed: {e}", file=sys.stderr)
            continue
        for r in result.get("records", []):
            day = r.get("day")
            if not day:
                continue
            d = dt.date.fromisoformat(day[:10])
            source = r.get("source") or "(none)"
            cnt = int(r.get("cnt", 0))
            # Source-dimensioned row
            rows.append(Row(PLATFORM, metric, d, float(cnt),
                            dimension=f"source:{source}"))

    # Aggregate to platform-level (dimension=NULL) for headline overview tiles
    agg: dict[tuple[str, dt.date], float] = defaultdict(float)
    for r in rows:
        agg[(r.metric, r.date)] += float(r.value or 0)
    for (metric, d), v in agg.items():
        rows.append(Row(PLATFORM, metric, d, v, dimension=None))
    return rows


_MONTH_TO_INT = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
}


def pull_kpi_line_items(sf: Salesforce) -> list[Row]:
    """Pull Marketing_KPI_Line_Items__c monthly aggregates.

    Field names verified via SF describe() against the live schema (2026-05-21).
    Object has 65 custom fields; we pull the high-leverage ones for dashboard tiles.
    """
    # Year lives on the parent Marketing_Report__r (its Name IS the year, e.g. "2026")
    soql = """
        SELECT Lead_Source__c, Month__c, Marketing_Report__r.Name,
               Monthly_Spend__c, Projected_Total_Revenue__c, Projected_ROAS__c, Actual_ROAS__c,
               Gross_Leads__c, Qualified_Leads__c, Unqualified_Leads__c,
               Contacted_Leads__c, Uncontacted_Leads__c,
               Appointments_Set__c, Appointments_Attended__c, Appointments_Cancelled__c,
               Contracts_Signed__c, Contracts_Cancelled__c,
               Closed_Deals__c, Pending_Deals__c, Offers_Made__c,
               Closed_Total_Profit__c, Closed_Wholesale_Profit__c,
               Closed_Flip_Profit__c, Closed_Novation_Profit__c, Closed_Rental_Profit__c,
               Cost_Per_Gross_Lead__c, Cost_Per_Qualified_Lead__c,
               Cost_Per_Attn_Appt__c, Cost_Per_Contract__c, Cost_Per_Closed_Deal__c,
               Created_By_Call__c, Created_By_Webform__c
        FROM Marketing_KPI_Line_Items__c
    """
    try:
        result = sf.query_all(soql)
    except Exception as e:
        print(f"sf KPI line items query failed: {e}", file=sys.stderr)
        return []
    rows: list[Row] = []
    # Map SF custom field → internal metric name
    # KPI-sourced lead counts go to separate metric names to avoid colliding
    # with the per-day funnel rows from pull_funnel_daily (which write
    # leads_count / qualified_count at granular dates). The KPI versions are
    # monthly aggregates dated to first-of-month — useful for the "official
    # report" view, but the headline tiles should use the granular funnel data.
    metric_map = {
        "Monthly_Spend__c":             "monthly_spend_usd",
        "Projected_Total_Revenue__c":   "projected_revenue_usd",
        "Projected_ROAS__c":            "projected_roas",
        "Actual_ROAS__c":               "actual_roas",
        "Gross_Leads__c":               "kpi_leads_count",
        "Qualified_Leads__c":           "kpi_qualified_count",
        "Unqualified_Leads__c":         "unqualified_count",
        "Contacted_Leads__c":           "contacted_count",
        "Uncontacted_Leads__c":         "uncontacted_count",
        "Appointments_Set__c":          "appointment_count",
        "Appointments_Attended__c":     "appt_attended_count",
        "Appointments_Cancelled__c":    "appt_cancelled_count",
        "Contracts_Signed__c":          "contract_count",
        "Contracts_Cancelled__c":       "contract_cancelled_count",
        "Closed_Deals__c":              "closed_count",
        "Pending_Deals__c":             "pending_deal_count",
        "Offers_Made__c":               "offers_made_count",
        "Closed_Total_Profit__c":       "closed_profit_usd",
        "Closed_Wholesale_Profit__c":   "closed_wholesale_profit_usd",
        "Closed_Flip_Profit__c":        "closed_flip_profit_usd",
        "Closed_Novation_Profit__c":    "closed_novation_profit_usd",
        "Closed_Rental_Profit__c":      "closed_rental_profit_usd",
        "Cost_Per_Gross_Lead__c":       "cpl_usd",
        "Cost_Per_Qualified_Lead__c":   "cpl_qualified_usd",
        "Cost_Per_Attn_Appt__c":        "cost_per_attended_appt_usd",
        "Cost_Per_Contract__c":         "cost_per_contract_usd",
        "Cost_Per_Closed_Deal__c":      "cost_per_closed_deal_usd",
        "Created_By_Call__c":           "leads_via_call",
        "Created_By_Webform__c":        "leads_via_webform",
    }
    # Aggregate per-source values into rollup totals BEFORE emitting null-dim rows.
    # Previously we wrote one null-dim row per (source, metric, date) carrying the
    # per-source value — that caused 6x+ inflation when the dashboard SUMmed them.
    totals: dict[tuple[str, dt.date], float] = defaultdict(float)
    for r in result.get("records", []):
        report = r.get("Marketing_Report__r") or {}
        y_str = report.get("Name") if isinstance(report, dict) else None
        try:
            y = int(y_str) if y_str else None
        except (TypeError, ValueError):
            y = None
        m = _MONTH_TO_INT.get(r.get("Month__c") or "")
        if not (y and m):
            continue
        d = dt.date(y, m, 1)
        ch = r.get("Lead_Source__c") or "(none)"
        for sf_key, metric in metric_map.items():
            v = r.get(sf_key)
            if v is None:
                continue
            rows.append(Row(PLATFORM, metric, d, float(v),
                            dimension=f"source:{ch}"))
            totals[(metric, d)] += float(v)
    # One rollup row per (metric, date) carrying the true total
    for (metric, d), total in totals.items():
        rows.append(Row(PLATFORM, metric, d, total, dimension=None))
    return rows


def pull_lead_heatmap(sf: Salesforce, days: int = 90,
                      *, channel: str = "phone") -> list[Row]:
    """Bucket inbound leads by day-of-week × hour-of-day for the last
    `days` days, partitioned by Created_By__c (a text field on Lead):
      channel='phone'   → Created_By__c matches Phone Call / Call / Phone, OR is blank
      channel='webform' → Created_By__c matches Webform / Web Form / Form

    Writes one Row per (dow, hour, source) bucket carrying the count. Also
    writes a per-(dow, hour) rollup with dimension carrying only dow|hour for
    the all-sources heatmap. Date stamp is today (snapshot semantics).

    America/New_York is the reference TZ — CreatedDate is UTC in SOQL, so we
    do the TZ shift in Python for accuracy.
    """
    from collections import Counter
    from zoneinfo import ZoneInfo

    NY = ZoneInfo("America/New_York")
    start_dt = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    # Created_By__c is a TEXT field on Lead. We pull every lead in the window
    # and Python-filter so any value variant ("Phone Call", "Call", "Webform",
    # "Web Form", etc.) is matched.
    metric_name = ("phone_lead_hour_count" if channel == "phone"
                   else "webform_lead_hour_count")
    log_label = f"{channel}-lead"
    soql = f"""
        SELECT Id, CreatedDate, LeadSource, Created_By__c
        FROM Lead
        WHERE CreatedDate >= {start_dt}T00:00:00Z
    """
    rows: list[Row] = []
    try:
        result = sf.query_all(soql)
    except Exception as e:
        print(f"sf {log_label} heatmap query failed: {e}", file=sys.stderr)
        return rows

    today = dt.date.today()
    by_src: Counter = Counter()    # (dow, hour, source) -> count
    by_all: Counter = Counter()    # (dow, hour) -> count

    def is_webform(v: object) -> bool:
        if v is None:
            return False
        s = str(v).strip().lower()
        return ("webform" in s) or ("web form" in s) or s == "form"

    def is_phone(v: object) -> bool:
        if v is None or str(v).strip() == "":
            return True  # blank = phone (per user)
        s = str(v).strip().lower()
        return ("phone" in s) or ("call" in s)

    matches = is_phone if channel == "phone" else is_webform

    for r in result.get("records", []):
        if not matches(r.get("Created_By__c")):
            continue
        created = r.get("CreatedDate")  # ISO 8601 UTC with millis, e.g. 2026-05-21T13:42:17.000+0000
        if not created:
            continue
        try:
            # Python's fromisoformat doesn't love the trailing +0000 — normalize
            iso = created.replace("Z", "+00:00")
            if iso.endswith("+0000"):
                iso = iso[:-5] + "+00:00"
            d = dt.datetime.fromisoformat(iso).astimezone(NY)
        except Exception:
            continue
        dow = d.weekday()          # 0=Mon, 6=Sun
        hour = d.hour
        src = (r.get("LeadSource") or "(none)").replace("|", "_")
        by_src[(dow, hour, src)] += 1
        by_all[(dow, hour)] += 1

    for (dow, hour, src), n in by_src.items():
        rows.append(Row(PLATFORM, metric_name, today, float(n),
                        dimension=f"dow:{dow}|hour:{hour}|source:{src}"))
    for (dow, hour), n in by_all.items():
        rows.append(Row(PLATFORM, metric_name, today, float(n),
                        dimension=f"dow:{dow}|hour:{hour}"))
    print(f"sf {log_label} heatmap: {len(by_all)} (dow,hour) buckets, {len(by_src)} with source")
    return rows


def pull_cohort_data(sf: Salesforce, months: int = 18) -> list[Row]:
    """Per-lead cohort progression through the funnel.

    Group leads by the calendar month they were CREATED (America/New_York TZ).
    For each cohort, count distinct leads that hit each stage:
      created   — every lead in the cohort (denominator)
      qualified — Date_Lead_Qualified__c is not null
      converted — IsConverted = true (lead became Opp/appt set)
      closed    — placeholder for v2 (would join ConvertedOpportunityId →
                  Opp.StageName = 'Closed Won' or equivalent)

    Writes one row per (cohort_month, stage) with the SAME date stamp (today)
    so the dashboard can read latest snapshot. Also writes per-LeadSource rows
    bucketed by COHORT QUARTER (less granular) for the source sub-table.

    Dimensions:
      cohort:YYYY-MM|stage:<stage>                  → overall cohort cell
      cohort_q:YYYY-Qn|source:<src>|stage:<stage>   → per-source quarter cell
    """
    from zoneinfo import ZoneInfo

    NY = ZoneInfo("America/New_York")
    today = dt.date.today()
    # Start of window: first of the month, `months` months back
    start_year = today.year
    start_month = today.month - (months - 1)
    while start_month <= 0:
        start_month += 12
        start_year -= 1
    start_date = dt.date(start_year, start_month, 1)
    start_iso = start_date.isoformat()

    soql = f"""
        SELECT Id, CreatedDate, LeadSource,
               Date_Lead_Qualified__c, Date_Lead_Unqualified__c,
               IsConverted, ConvertedDate, ConvertedOpportunityId
        FROM Lead
        WHERE CreatedDate >= {start_iso}T00:00:00Z
    """
    rows: list[Row] = []
    try:
        result = sf.query_all(soql)
    except Exception as e:
        print(f"sf cohort query failed: {e}", file=sys.stderr)
        return rows

    # (cohort_month_str, stage) -> distinct lead count
    by_cohort: dict[tuple[str, str], int] = defaultdict(int)
    # (cohort_quarter_str, source, stage) -> distinct lead count
    by_q_src: dict[tuple[str, str, str], int] = defaultdict(int)

    def quarter_label(d: dt.date) -> str:
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"

    for r in result.get("records", []):
        created = r.get("CreatedDate")
        if not created:
            continue
        try:
            iso = created.replace("Z", "+00:00")
            if iso.endswith("+0000"):
                iso = iso[:-5] + "+00:00"
            cdt = dt.datetime.fromisoformat(iso).astimezone(NY)
        except Exception:
            continue
        cohort_dt = cdt.date()
        cohort_m = f"{cohort_dt.year}-{cohort_dt.month:02d}"
        cohort_q = quarter_label(cohort_dt)
        src = (r.get("LeadSource") or "(none)").replace("|", "_")

        # Stage flags
        stages = ["created"]
        if r.get("Date_Lead_Qualified__c"):
            stages.append("qualified")
        if r.get("IsConverted"):
            stages.append("converted")
            # v1: treat converted as "closed lead" proxy
            stages.append("closed")

        for st in stages:
            by_cohort[(cohort_m, st)] += 1
            by_q_src[(cohort_q, src, st)] += 1

    for (cm, st), n in by_cohort.items():
        rows.append(Row(PLATFORM, "cohort_count", today, float(n),
                        dimension=f"cohort:{cm}|stage:{st}"))
    for (cq, src, st), n in by_q_src.items():
        rows.append(Row(PLATFORM, "cohort_count", today, float(n),
                        dimension=f"cohort_q:{cq}|source:{src}|stage:{st}"))

    print(f"sf cohort: {len(by_cohort)} (month,stage) cells, "
          f"{len(by_q_src)} (quarter,source,stage) cells "
          f"from {len(result.get('records', []))} leads in last {months} months")
    return rows


def pull_zip_profit(sf: Salesforce, days: int = 730) -> list[Row]:
    """Aggregate closed-transaction profit by property ZIP code.

    Uses sf.describe() to find the actual field names — DBH's Transaction
    object has ~370 custom fields and field naming varies. We try common
    variants for ZIP, profit, and closing date.

    Writes one Row per ZIP with the total profit dimensionalized as
    'zip:<zip>'. Also writes per-(zip × dispo) rows so the dashboard can
    split wholesale / flip / novation / rental.

    The 'date' on each row is today (snapshot semantics — this is a rolling
    aggregate, not a per-day metric).
    """
    today = dt.date.today()
    rows: list[Row] = []

    try:
        desc = sf.Left_Main__Transactions__c.describe()
    except Exception as e:
        print(f"sf transaction describe failed: {e}", file=sys.stderr)
        return rows

    field_names = {f["name"] for f in desc["fields"]}

    def pick(*candidates: str) -> str | None:
        for c in candidates:
            if c in field_names:
                return c
        return None

    # Debug probe — print all field names containing keyword roots so we can
    # identify the actual schema and update the candidate lists below.
    for keyword in ("dispo", "closing_date", "close_date", "contract_date",
                    "novation", "profit"):
        matches = sorted(n for n in field_names if keyword in n.lower())
        if matches:
            print(f"sf describe[{keyword}]: {matches}")

    # Known field names verified by user 2026-05-22:
    #   ZIP    = Property_Address__PostalCode__s  (compound-Address subfield)
    #   Profit = Actual_Profit__c
    # Per user, there are TWO closing dates:
    #   Left_Main__Closing_Date__c — buy-side close (wholesale OR flip purchase)
    #   Sold_Closing_Date__c       — sell-side close (flip/wholetail/novation sold)
    # Plus Novation_Contract_Date__c marks the start of novation contracts.
    # We pull both and consider a deal "closed" if EITHER date falls in window.
    zip_field = pick("Property_Address__PostalCode__s",
                     "Property_Postal_Code__c", "Property_Zip__c")
    profit_field = pick("Actual_Profit__c", "Net_Profit__c",
                        "Closed_Profit__c", "Total_Profit__c", "Profit__c")
    sold_close_field = pick("Sold_Closing_Date__c", "Closing_Date__c",
                            "Closed_Date__c", "Close_Date__c")
    buy_close_field = pick("Left_Main__Closing_Date__c",
                           "Closing_Date__c", "Buy_Closing_Date__c",
                           "Purchase_Closing_Date__c")
    novation_field = pick("Novation_Contract_Date__c", "Contract_Date__c")
    # Verified via describe() 2026-05-22: actual field is
    # Left_Main__Disposition_Decision__c (full word "Disposition", not abbreviated)
    dispo_field = pick("Left_Main__Disposition_Decision__c",
                       "Left_Main__Disposition__c",
                       "Disposition_Decision__c", "Dispo__c",
                       "Left_Main__Dispo__c")
    address_field = pick("Property_Address__Street__s", "Property_Address__c",
                         "PropertyAddress__c")

    print(f"sf zip-profit fields: zip={zip_field} profit={profit_field} "
          f"sold_close={sold_close_field} buy_close={buy_close_field} "
          f"novation={novation_field} dispo={dispo_field}")

    if not zip_field or not profit_field:
        print("sf zip-profit: zip or profit field missing — skipping.", file=sys.stderr)
        return rows
    if not (sold_close_field or buy_close_field):
        print("sf zip-profit: no closing-date field found — skipping.", file=sys.stderr)
        return rows

    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    # Build OR clauses across whichever closing-date fields exist
    date_clauses = []
    if sold_close_field:
        date_clauses.append(f"{sold_close_field} >= {cutoff}")
    if buy_close_field and buy_close_field != sold_close_field:
        date_clauses.append(f"{buy_close_field} >= {cutoff}")
    if novation_field:
        date_clauses.append(f"{novation_field} >= {cutoff}")
    closed_in_window = " OR ".join(date_clauses)

    select_fields = [zip_field, profit_field]
    if sold_close_field:        select_fields.append(sold_close_field)
    if buy_close_field and buy_close_field != sold_close_field:
        select_fields.append(buy_close_field)
    if novation_field:          select_fields.append(novation_field)
    if dispo_field:             select_fields.append(dispo_field)
    if address_field:           select_fields.append(address_field)
    soql = f"""
        SELECT Id, {', '.join(select_fields)}
        FROM Left_Main__Transactions__c
        WHERE ({closed_in_window})
          AND {profit_field} != null
          AND {profit_field} != 0
    """
    try:
        result = sf.query_all(soql)
    except Exception as e:
        print(f"sf zip-profit query failed: {e}", file=sys.stderr)
        return rows

    from collections import defaultdict
    by_zip: dict[str, float] = defaultdict(float)
    by_zip_count: dict[str, int] = defaultdict(int)
    by_zip_dispo: dict[tuple[str, str], float] = defaultdict(float)

    for r in result.get("records", []):
        z = r.get(zip_field)
        p = r.get(profit_field)
        if z is None or p is None:
            continue
        zip5 = str(z).strip()[:5]  # normalize to 5-digit ZIP
        if not zip5 or not zip5.isdigit():
            continue
        profit = float(p)
        by_zip[zip5] += profit
        by_zip_count[zip5] += 1
        if dispo_field:
            d = (r.get(dispo_field) or "(unspecified)")
            d = str(d).strip().replace("|", "_")[:40] or "(unspecified)"
            by_zip_dispo[(zip5, d)] += profit

    for zip5, total in by_zip.items():
        rows.append(Row(PLATFORM, "zip_profit_usd", today, total,
                        dimension=f"zip:{zip5}"))
        rows.append(Row(PLATFORM, "zip_deal_count", today,
                        float(by_zip_count[zip5]),
                        dimension=f"zip:{zip5}"))
    for (zip5, dispo), total in by_zip_dispo.items():
        rows.append(Row(PLATFORM, "zip_profit_usd", today, total,
                        dimension=f"zip:{zip5}|dispo:{dispo}"))

    print(f"sf zip-profit: {len(by_zip)} zips, {sum(by_zip_count.values())} closed deals "
          f"({days}d window), total profit ${sum(by_zip.values()):,.0f}")
    return rows


def main(days: int = LOOKBACK_DAYS_DEFAULT) -> int:
    with run_logger(PLATFORM) as state:
        sf = sf_client()
        rows = pull_funnel_daily(sf, days) + pull_kpi_line_items(sf)
        # Inbound-volume heatmaps — always 90 days, separate from configurable
        # `days` window. Each channel wrapped so failure doesn't kill the rest.
        for channel in ("phone", "webform"):
            try:
                rows += pull_lead_heatmap(sf, days=90, channel=channel)
            except Exception as e:
                print(f"sf {channel}-lead heatmap section failed: {e}", file=sys.stderr)
        # ZIP-level profit aggregation — 2 years of closed deals
        try:
            rows += pull_zip_profit(sf, days=730)
        except Exception as e:
            print(f"sf zip-profit section failed: {e}", file=sys.stderr)
        # Lead-cohort progression — 18 months of per-lead funnel tracking
        try:
            rows += pull_cohort_data(sf, months=18)
        except Exception as e:
            print(f"sf cohort section failed: {e}", file=sys.stderr)
        conn = neon_conn()
        try:
            n = write_rows(conn, rows)
            state["rows_written"] = n
            state["meta"] = {"days": days}
            print(f"sf: wrote {n} rows ({days}d)")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else LOOKBACK_DAYS_DEFAULT
    sys.exit(main(days))
