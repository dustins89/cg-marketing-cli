"""Match TV airings to SF Leads — v2 with source-signal aware attribution.

Algorithm:
  1. Pull SF Leads in the date range. Fields: Id, CreatedDate, LeadSource,
     How_Did_You_Hear_About_Us__c, IsConverted, ConvertedDate, GCLID__c, FBCLID__c.
  2. For each tv_airing, walk every minute from 0 to 15 min AFTER air time
     (NO halo — strict 15-min primary window only).
  3. For each lead found in window, write one row per (airing, lead) pair
     into tv_airing_leads with the lead's source fields + attribution_strength.

  attribution_strength values:
    'strong'  — Lead.LeadSource = 'TV' OR How_Did_You_Hear = 'TV' (self-reported)
    'medium'  — timing match, NO conflicting paid source (no GCLID, no FBCLID,
                LeadSource is not Google PPC / Facebook / Direct Mail / Google Search)
    'weak'    — timing match BUT has GCLID/FBCLID or paid LeadSource — likely
                the lead came from paid search/social and the TV window match
                is coincidental.

  Deduplication: per-lead counts at the dashboard layer use COUNT(DISTINCT
  lead_id) so a single lead with both LeadSource='TV' and HDYH='TV' counts once.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from collections import defaultdict

from ingest.core import neon_conn, run_logger
from ingest.ingest_sf import sf_client

PLATFORM = "tv_match"
PRIMARY_WINDOW_MIN = 15

# Lead sources that indicate the lead clearly came from a non-TV paid channel.
# If any of these are set, a timing-only match should be classified 'weak'.
NON_TV_PAID_SOURCES = {
    "Google PPC", "Google Ads", "Google Search",
    "Facebook", "Facebook Ads", "Facebook Retargeting", "Meta",
    "Bing", "Bing Ads", "Microsoft Ads",
    "Direct Mail", "Direct mail",
}

# Lead sources/HDYH values that clearly indicate TV.
TV_SOURCES = {"TV", "tv", "Television", "television"}


def _parse_sf_dt(s: str) -> dt.datetime:
    s = s.replace("Z", "+0000")
    if len(s) >= 5 and (s[-5] in "+-") and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    return dt.datetime.fromisoformat(s)


def _classify(lead: dict, has_timing_match: bool) -> str | None:
    """Return attribution_strength or None if not TV-attributed."""
    ls = (lead.get("LeadSource") or "").strip()
    hdyha = (lead.get("How_Did_You_Hear_About_Us__c") or "").strip()
    has_self_report = (ls in TV_SOURCES) or (hdyha in TV_SOURCES)

    if has_self_report:
        return "strong"
    if not has_timing_match:
        return None

    # Timing match — check for conflicting paid signal
    has_gclid = bool(lead.get("GCLID__c"))
    has_fbclid = bool(lead.get("FBCLID__c"))
    has_paid_source = ls in NON_TV_PAID_SOURCES
    if has_gclid or has_fbclid or has_paid_source:
        return "weak"
    return "medium"


def main(days: int = 120) -> int:
    with run_logger(PLATFORM) as state:
        conn = neon_conn()
        try:
            # 1) Get airings in scope
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, station, air_datetime_et
                    FROM tv_airings
                    WHERE air_datetime_et >= now() - (%s || ' days')::interval
                    ORDER BY air_datetime_et
                    """,
                    (str(days),),
                )
                airings = cur.fetchall()
            if not airings:
                state["meta"] = {"airings": 0}
                print("no airings to match")
                return 0

            min_air = min(a["air_datetime_et"] for a in airings)
            max_air = max(a["air_datetime_et"] for a in airings)
            sf_start = min_air.isoformat()
            sf_end = (max_air + dt.timedelta(minutes=PRIMARY_WINDOW_MIN + 5)).isoformat()

            # 2) Pull SF Leads with the source fields we care about
            sf = sf_client()
            soql = f"""
                SELECT Id, CreatedDate, LeadSource,
                       How_Did_You_Hear_About_Us__c,
                       IsConverted, ConvertedDate,
                       GCLID__c, FBCLID__c
                FROM Lead
                WHERE CreatedDate >= {sf_start} AND CreatedDate <= {sf_end}
            """
            try:
                leads = sf.query_all(soql).get("records", [])
            except Exception as e:
                print(f"SF query failed: {e}", file=sys.stderr)
                leads = []

            # 3) Bucket leads by minute for fast lookup
            leads_by_minute: dict[dt.datetime, list[dict]] = defaultdict(list)
            for L in leads:
                created = _parse_sf_dt(L["CreatedDate"])
                bucket = created.replace(second=0, microsecond=0)
                leads_by_minute[bucket].append(L)

            # Track which leads got matched to at least one airing — used to
            # avoid double-inserting source-only rows for leads that ALSO had
            # a timing match.
            timing_matched_lead_ids: set[str] = set()

            inserted = 0
            for a in airings:
                aid = a["id"]
                air_dt = a["air_datetime_et"]
                for offset in range(0, PRIMARY_WINDOW_MIN + 1):
                    bucket = (air_dt + dt.timedelta(minutes=offset)).replace(
                        second=0, microsecond=0
                    )
                    for L in leads_by_minute.get(bucket, []):
                        created = _parse_sf_dt(L["CreatedDate"])
                        delta_min = (created - air_dt).total_seconds() / 60.0
                        if delta_min < 0 or delta_min > PRIMARY_WINDOW_MIN:
                            continue

                        strength = _classify(L, has_timing_match=True)
                        # Even 'weak' matches get inserted — dashboard filters them.

                        converted_at = None
                        if L.get("ConvertedDate"):
                            try:
                                converted_at = _parse_sf_dt(L["ConvertedDate"] + "T00:00:00.000+0000")
                            except Exception:
                                converted_at = None

                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                INSERT INTO tv_airing_leads
                                  (airing_id, lead_id, lead_created_at_et,
                                   minutes_after_air, window_class,
                                   attribution_strength, lead_source,
                                   how_did_you_hear, converted, converted_at,
                                   gclid_present, fbclid_present)
                                VALUES (%s, %s, %s, %s, 'primary',
                                        %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (airing_id, lead_id) DO UPDATE SET
                                    attribution_strength = EXCLUDED.attribution_strength,
                                    lead_source          = EXCLUDED.lead_source,
                                    how_did_you_hear     = EXCLUDED.how_did_you_hear,
                                    converted            = EXCLUDED.converted,
                                    converted_at         = EXCLUDED.converted_at,
                                    gclid_present        = EXCLUDED.gclid_present,
                                    fbclid_present       = EXCLUDED.fbclid_present
                                """,
                                (aid, L["Id"], created, delta_min,
                                 strength, L.get("LeadSource"),
                                 L.get("How_Did_You_Hear_About_Us__c"),
                                 bool(L.get("IsConverted")), converted_at,
                                 bool(L.get("GCLID__c")), bool(L.get("FBCLID__c"))),
                            )
                            if cur.rowcount > 0:
                                inserted += 1
                            timing_matched_lead_ids.add(L["Id"])
                conn.commit()

            # ── Source-only attribution ──────────────────────────────────────
            # For leads with LeadSource='TV' or How_Did_You_Hear='TV' that did
            # NOT get a timing match, insert a row with airing_id=NULL and
            # window_class='source_only'. This captures real TV leads that
            # happened to be created outside any 15-min airing window
            # (e.g. someone saw the ad earlier and called hours later).
            source_only = 0
            for L in leads:
                if L["Id"] in timing_matched_lead_ids:
                    continue
                ls = (L.get("LeadSource") or "").strip()
                hdyha = (L.get("How_Did_You_Hear_About_Us__c") or "").strip()
                if ls not in TV_SOURCES and hdyha not in TV_SOURCES:
                    continue
                created = _parse_sf_dt(L["CreatedDate"])
                converted_at = None
                if L.get("ConvertedDate"):
                    try:
                        converted_at = _parse_sf_dt(L["ConvertedDate"] + "T00:00:00.000+0000")
                    except Exception:
                        converted_at = None
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO tv_airing_leads
                          (airing_id, lead_id, lead_created_at_et,
                           minutes_after_air, window_class,
                           attribution_strength, lead_source,
                           how_did_you_hear, converted, converted_at,
                           gclid_present, fbclid_present)
                        VALUES (NULL, %s, %s, NULL, 'source_only',
                                'strong', %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (airing_id, lead_id) DO UPDATE SET
                            lead_source      = EXCLUDED.lead_source,
                            how_did_you_hear = EXCLUDED.how_did_you_hear,
                            converted        = EXCLUDED.converted,
                            converted_at     = EXCLUDED.converted_at,
                            gclid_present    = EXCLUDED.gclid_present,
                            fbclid_present   = EXCLUDED.fbclid_present
                        """,
                        (L["Id"], created, L.get("LeadSource"),
                         L.get("How_Did_You_Hear_About_Us__c"),
                         bool(L.get("IsConverted")), converted_at,
                         bool(L.get("GCLID__c")), bool(L.get("FBCLID__c"))),
                    )
                    if cur.rowcount > 0:
                        source_only += 1
            conn.commit()
            inserted += source_only

            state["rows_written"] = inserted
            state["meta"] = {
                "airings": len(airings),
                "leads_seen": len(leads),
                "source_only": source_only,
                "days": days,
            }
            print(f"tv_match: {inserted} links "
                  f"({inserted - source_only} timing + {source_only} source-only) "
                  f"across {len(airings)} airings × {len(leads)} leads")
        finally:
            conn.close()
    return 0


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    sys.exit(main(days))
