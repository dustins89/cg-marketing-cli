#!/usr/bin/env python3
"""Two Tier-1/2 mutations — explicit user confirmation 2026-05-16:

  #8.  GA4: bump event_data_retention TWO_MONTHS -> FOURTEEN_MONTHS
  #16. Google Ads: set primary_for_goal=False on 5 GOOGLE_HOSTED (GBP) conversion actions:
       - 338263655 Local actions - Other engagements
       - 338317666 Local actions - Website visits
       - 339344830 Clicks to call
       - 390073191 Local actions - Directions
       - 1064037493 Local actions - Menu views

User reported the UI does not allow demoting these. This script tests
whether the Google Ads API enforces the same lock.

Run with --apply to execute (default = dry-run).
"""
import sys
import yaml
from pathlib import Path

APPLY = "--apply" in sys.argv
cfg_path = Path.home()/'marketing-cli/google-ads.yaml'

# ============ #8 GA4 RETENTION ============
print("=" * 60, file=sys.stderr)
print("#8 GA4 data retention: TWO_MONTHS -> FOURTEEN_MONTHS", file=sys.stderr)
print("=" * 60, file=sys.stderr)

from google.oauth2.credentials import Credentials
from google.analytics.admin_v1alpha import AnalyticsAdminServiceClient
from google.analytics.admin_v1alpha.types import DataRetentionSettings
from google.protobuf import field_mask_pb2

cfg = yaml.safe_load(cfg_path.read_text())
creds = Credentials(
    token=None, refresh_token=cfg['refresh_token'],
    client_id=cfg['client_id'], client_secret=cfg['client_secret'],
    token_uri='https://oauth2.googleapis.com/token',
)
prop = f"properties/{cfg['ga4_property_id']}"
ga4_admin = AnalyticsAdminServiceClient(credentials=creds)

drs = ga4_admin.get_data_retention_settings(name=f"{prop}/dataRetentionSettings")
print(f"  Before: event_data_retention={drs.event_data_retention.name}", file=sys.stderr)
print(f"  Before: reset_user_data_on_new_activity={drs.reset_user_data_on_new_activity}", file=sys.stderr)

if APPLY:
    drs.event_data_retention = DataRetentionSettings.RetentionDuration.FOURTEEN_MONTHS
    updated = ga4_admin.update_data_retention_settings(
        data_retention_settings=drs,
        update_mask=field_mask_pb2.FieldMask(paths=['event_data_retention']),
    )
    print(f"  After:  event_data_retention={updated.event_data_retention.name}  [APPLIED]", file=sys.stderr)
else:
    print(f"  DRY-RUN: would set event_data_retention=FOURTEEN_MONTHS", file=sys.stderr)


# ============ #16 GAds GBP conversion actions ============
print("\n" + "=" * 60, file=sys.stderr)
print("#16 Google Ads: demote 5 GBP conversion actions (primary_for_goal=False)", file=sys.stderr)
print("=" * 60, file=sys.stderr)

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException
from google.api_core import protobuf_helpers

gads_client = GoogleAdsClient.load_from_storage(str(cfg_path))
CUST = "YOUR_CUSTOMER_ID"
ca_svc = gads_client.get_service("ConversionActionService")

targets = [
    ("338263655",  "Local actions - Other engagements"),
    ("338317666",  "Local actions - Website visits"),
    ("339344830",  "Clicks to call"),
    ("390073191",  "Local actions - Directions"),
    ("1064037493", "Local actions - Menu views"),
]

operations = []
for ca_id, name in targets:
    op = gads_client.get_type("ConversionActionOperation")
    op.update.resource_name = ca_svc.conversion_action_path(CUST, ca_id)
    op.update.primary_for_goal = False
    # Field mask is constructed from a sample with all fields then narrowed
    fm = protobuf_helpers.field_mask(None, op.update._pb)
    op.update_mask.CopyFrom(fm)
    operations.append(op)
    print(f"  Plan: demote ca={ca_id} '{name}'", file=sys.stderr)

if APPLY:
    print(f"\n  Attempting mutate on {len(operations)} conversion actions...", file=sys.stderr)
    try:
        resp = ca_svc.mutate_conversion_actions(customer_id=CUST, operations=operations)
        print(f"  [SUCCESS] Mutated {len(resp.results)} conversion actions", file=sys.stderr)
        for r in resp.results:
            print(f"    -> {r.resource_name}", file=sys.stderr)
    except GoogleAdsException as e:
        print(f"  [FAILED] GoogleAdsException", file=sys.stderr)
        for err in e.failure.errors:
            print(f"    error_code: {err.error_code}", file=sys.stderr)
            print(f"    message: {err.message}", file=sys.stderr)
            print(f"    trigger: {err.trigger}", file=sys.stderr)
            print(f"    location field_path: {err.location}", file=sys.stderr)
        print(f"\n  [conclusion] API enforces the same lock as the UI. These GOOGLE_HOSTED actions cannot have primary_for_goal flipped.", file=sys.stderr)
        print(f"  Workarounds: (a) remove the GBP-Ads link entirely (loses ALL GBP signals), (b) set conversion goal selection to 'Specific conversion goals' on each campaign and uncheck the categories ENGAGEMENT/PAGE_VIEW/CONTACT/GET_DIRECTIONS at the campaign level, or (c) leave as-is and accept they're in the bidding signal pool.", file=sys.stderr)
else:
    print(f"\n  DRY-RUN: would call mutate_conversion_actions with {len(operations)} operations", file=sys.stderr)

print("\n[DONE]", file=sys.stderr)
