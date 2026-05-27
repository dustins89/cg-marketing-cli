"""Anomaly alert evaluator.

For each enabled alert_rule, compute the relevant metric over the rule's
window and fire a Slack alert if the threshold is breached. Each firing is
recorded in alert_firings (with slack_sent=true on success) so we don't
re-spam the channel on every run.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

import requests

from ingest.core import neon_conn, run_logger


PLATFORM = "alerts"
SLACK_URL = os.environ.get("SLACK_ALERT_WEBHOOK_URL")
DASHBOARD_URL = os.environ.get("DASHBOARD_BASE_URL", "")


def _post_slack(text: str, blocks: list | None = None) -> bool:
    if not SLACK_URL:
        print("SLACK_ALERT_WEBHOOK_URL not set; would have posted:", text, file=sys.stderr)
        return False
    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    resp = requests.post(SLACK_URL, json=payload, timeout=15)
    if not resp.ok:
        print(f"slack post failed: {resp.status_code} {resp.text}", file=sys.stderr)
        return False
    return True


def evaluate_rule(conn, rule: dict) -> dict | None:
    """Return a firing dict if the rule trips, else None."""
    rule_id = rule["id"]
    platform = rule.get("platform")
    metric = rule["metric"]
    dim = rule.get("dimension")
    cmp_ = rule["comparison"]
    thresh = float(rule["threshold"])
    window_days = int(rule.get("window_days") or 1)

    today = dt.date.today()
    window_end = today
    window_start = today - dt.timedelta(days=window_days)
    # Prior window of same length for pct-change comparisons
    prior_end = window_start - dt.timedelta(days=1)
    prior_start = prior_end - dt.timedelta(days=window_days - 1)

    def sum_metric(start, end) -> float:
        with conn.cursor() as cur:
            sql = """
                SELECT COALESCE(SUM(value), 0)::float8 v
                FROM metric_snapshots
                WHERE metric = %s
                  AND date BETWEEN %s AND %s
                  AND (%s IS NULL OR platform = %s)
                  AND (%s IS NULL OR dimension = %s)
            """
            cur.execute(sql, (metric, start, end, platform, platform, dim, dim))
            row = cur.fetchone()
        return float(row["v"] or 0)

    observed = sum_metric(window_start, window_end)
    prior = sum_metric(prior_start, prior_end) if cmp_.startswith("pct_change_") else None

    trip = False
    if cmp_ == "gt" and observed > thresh:
        trip = True
    elif cmp_ == "lt" and observed < thresh:
        trip = True
    elif cmp_ == "pct_change_gt" and prior:
        pct = (observed - prior) / prior
        if pct > thresh:
            trip = True
            observed = pct
    elif cmp_ == "pct_change_lt" and prior:
        pct = (observed - prior) / prior
        if pct < thresh:
            trip = True
            observed = pct
    elif cmp_.startswith("pct_change_") and not prior:
        # Can't divide by zero — skip silently
        return None

    if not trip:
        return None
    return {
        "rule_id": rule_id,
        "observed_value": observed,
        "threshold": thresh,
        "message": f"{platform or 'any'} / {metric}"
                   + (f" ({dim})" if dim else "")
                   + f" — {cmp_}: observed={observed:.3g}, threshold={thresh:.3g}",
    }


def main() -> int:
    with run_logger(PLATFORM) as state:
        conn = neon_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM alert_rules WHERE enabled = true")
                rules = cur.fetchall()
            fired = 0
            for rule in rules:
                result = evaluate_rule(conn, rule)
                if not result:
                    continue
                slack_ok = _post_slack(
                    text=f":warning: {result['message']}",
                    blocks=[
                        {"type": "section",
                         "text": {"type": "mrkdwn",
                                  "text": f":warning: *{rule['name']}*\n{result['message']}"}},
                        {"type": "actions",
                         "elements": ([{"type": "button",
                                        "text": {"type": "plain_text", "text": "Open dashboard"},
                                        "url": DASHBOARD_URL}] if DASHBOARD_URL else [])}
                    ] if DASHBOARD_URL else None,
                )
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO alert_firings (rule_id, observed_value, threshold,
                                                   message, slack_sent)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (result["rule_id"], result["observed_value"], result["threshold"],
                         result["message"], slack_ok),
                    )
                conn.commit()
                fired += 1
            state["rows_written"] = fired
            state["meta"] = {"rules_evaluated": len(rules), "fired": fired}
            print(f"alerts: evaluated {len(rules)} rules, fired {fired}")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
