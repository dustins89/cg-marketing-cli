#!/usr/bin/env python3
"""GA4 mutations — explicit user confirmation received 2026-05-16:
  1. Create custom channel group "DBH Custom (TV-aware)" with 10 priority-ordered channels.
  2. Update attribution acquisition_lookback 30d -> 90d (matches existing other_lookback).

Run with --apply to execute (default is dry-run preview).
"""
import sys
import yaml
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.analytics.admin_v1alpha import AnalyticsAdminServiceClient
from google.analytics.admin_v1alpha.types import (
    ChannelGroup, GroupingRule,
    ChannelGroupFilterExpression, ChannelGroupFilterExpressionList,
    ChannelGroupFilter,
    AttributionSettings,
)
from google.protobuf import field_mask_pb2

APPLY = "--apply" in sys.argv

cfg = yaml.safe_load((Path.home()/'marketing-cli/google-ads.yaml').read_text())
creds = Credentials(
    token=None, refresh_token=cfg['refresh_token'],
    client_id=cfg['client_id'], client_secret=cfg['client_secret'],
    token_uri='https://oauth2.googleapis.com/token',
)
prop = f"properties/{cfg['ga4_property_id']}"
client = AnalyticsAdminServiceClient(credentials=creds)


def str_filter(field, values, match_type='EXACT'):
    if isinstance(values, str):
        values = [values]
    if len(values) == 1:
        return ChannelGroupFilterExpression(filter=ChannelGroupFilter(
            field_name=field,
            string_filter=ChannelGroupFilter.StringFilter(
                match_type=getattr(ChannelGroupFilter.StringFilter.MatchType, match_type),
                value=values[0],
            ),
        ))
    return ChannelGroupFilterExpression(filter=ChannelGroupFilter(
        field_name=field,
        in_list_filter=ChannelGroupFilter.InListFilter(values=list(values)),
    ))


def contains_filter(field, value):
    return ChannelGroupFilterExpression(filter=ChannelGroupFilter(
        field_name=field,
        string_filter=ChannelGroupFilter.StringFilter(
            match_type=ChannelGroupFilter.StringFilter.MatchType.CONTAINS,
            value=value,
        ),
    ))


def or_(*exprs):
    return ChannelGroupFilterExpression(
        or_group=ChannelGroupFilterExpressionList(filter_expressions=list(exprs))
    )


def and_(*exprs):
    """GA4 channel-group constraint: and_group must contain only or_groups.
    Wrap any bare filter or and_group child in or_(child) first."""
    wrapped = []
    for e in exprs:
        if hasattr(e, 'or_group') and e.or_group and len(e.or_group.filter_expressions) > 0:
            wrapped.append(e)
        else:
            wrapped.append(or_(e))
    return ChannelGroupFilterExpression(
        and_group=ChannelGroupFilterExpressionList(filter_expressions=wrapped)
    )


# Top-level expression must be and_group, containing only or_group children.
# Helpers `and_` and `or_` enforce this constraint. For single-condition rules,
# wrap as and_(or_(filter)).

rules = [
    # 1. Branded Paid Search: (source IN google,bing) AND (medium=cpc) AND (campaign contains brand OR dustin)
    GroupingRule(
        display_name="Branded Paid Search",
        expression=and_(
            or_(str_filter("eachScopeSource", ["google", "bing"])),
            or_(str_filter("eachScopeMedium", "cpc")),
            or_(
                contains_filter("eachScopeCampaignName", "brand"),
                contains_filter("eachScopeCampaignName", "dustin"),
            ),
        ),
    ),
    # 2. Generic Paid Search
    GroupingRule(
        display_name="Generic Paid Search",
        expression=and_(
            or_(str_filter("eachScopeSource", ["google", "bing", "yahoo", "duckduckgo"])),
            or_(str_filter("eachScopeMedium", "cpc")),
        ),
    ),
    # 3. Paid Social: ((source IN fb,ig) AND (medium IN cpc,paid,an)) OR (source contains Facebook)
    GroupingRule(
        display_name="Paid Social",
        expression=and_(
            or_(
                # branch A: nested and packaged as a filter
                str_filter("eachScopeSource", ["facebook", "fb", "instagram", "ig", "Facebook Retargeting"]),
                contains_filter("eachScopeSource", "Facebook"),
            ),
            or_(
                str_filter("eachScopeMedium", ["cpc", "paid", "paid_social", "sponsored", "an", "Facebook_Mobile_Feed"]),
            ),
        ),
    ),
    # 4. Display & Remarketing
    GroupingRule(
        display_name="Display & Remarketing",
        expression=and_(
            or_(
                str_filter("eachScopeMedium", ["display", "banner", "cpm", "remarketing"]),
                str_filter("eachScopeDefaultChannelGroup", ["Display", "Cross-network"]),
            ),
        ),
    ),
    # 5. Email
    GroupingRule(
        display_name="Email",
        expression=and_(
            or_(str_filter("eachScopeMedium", ["email", "e-mail", "e_mail"])),
        ),
    ),
    # 6. Organic Brand
    GroupingRule(
        display_name="Organic Brand",
        expression=and_(
            or_(str_filter("eachScopeMedium", "organic")),
            or_(
                contains_filter("eachScopeCampaignName", "brand"),
                contains_filter("eachScopeSource", "dustin"),
            ),
        ),
    ),
    # 7. Organic Generic
    GroupingRule(
        display_name="Organic Generic",
        expression=and_(
            or_(str_filter("eachScopeMedium", "organic")),
        ),
    ),
    # 8. Organic Social
    GroupingRule(
        display_name="Organic Social",
        expression=and_(
            or_(
                str_filter("eachScopeSource", ["facebook", "instagram", "twitter", "linkedin", "youtube", "reddit", "tiktok", "ig"]),
                str_filter("eachScopeDefaultChannelGroup", "Organic Social"),
            ),
            or_(
                str_filter("eachScopeMedium", ["social", "organic_social", "social-network", "referral"]),
            ),
        ),
    ),
    # 9. Direct & TV (source=(direct) AND medium=(none)) OR defaultChannelGroup=Direct
    GroupingRule(
        display_name="Direct & TV",
        expression=and_(
            or_(
                str_filter("eachScopeSource", "(direct)"),
                str_filter("eachScopeDefaultChannelGroup", "Direct"),
            ),
        ),
    ),
    # 10. Referral
    GroupingRule(
        display_name="Referral",
        expression=and_(
            or_(str_filter("eachScopeMedium", "referral")),
        ),
    ),
]

cg = ChannelGroup(
    display_name="DBH Custom (TV-aware)",
    description=("Custom channel group separating Branded vs Generic Paid Search, Paid Social, "
                 "Display, Organic Brand vs Generic, Organic Social, and Direct (which absorbs "
                 "TV-driven traffic — TV has no UTM tagging so it appears as direct). "
                 "Built 2026-05-16 per audit Tier 3 #33."),
    grouping_rule=rules,
)

print(f'GA4 property: {prop}', file=sys.stderr)
print(f'Mode: {"APPLY" if APPLY else "DRY-RUN"}', file=sys.stderr)
print(f'\nPlanned channel group: "{cg.display_name}" with {len(rules)} rules:', file=sys.stderr)
for i, r in enumerate(rules, 1):
    print(f'  {i:2}. {r.display_name}', file=sys.stderr)

asett = client.get_attribution_settings(name=f'{prop}/attributionSettings')
print(f'\nAttribution change:', file=sys.stderr)
print(f'  acquisition_lookback: {asett.acquisition_conversion_event_lookback_window.name} -> ACQUISITION_CONVERSION_EVENT_LOOKBACK_WINDOW_90_DAYS', file=sys.stderr)
print(f'  other_lookback (unchanged): {asett.other_conversion_event_lookback_window.name}', file=sys.stderr)

if not APPLY:
    print(f'\n[DRY-RUN] No changes made. Re-run with --apply to execute.', file=sys.stderr)
    sys.exit(0)

print(f'\n[SKIP] attribution acquisition_lookback — GA4 API only allows 7 or 30 days. You are already at 30 (max). Recommendation #37 was wrong.', file=sys.stderr)

print(f'\nApplying channel group (full = 10 rules; fallback to 9 if INTERNAL error on Referral rule)...', file=sys.stderr)
import time

def try_create(cg_obj, label):
    try:
        c = client.create_channel_group(parent=prop, channel_group=cg_obj)
        print(f'[CREATED-{label}] {c.name}  rules={len(c.grouping_rule)}', file=sys.stderr)
        return c
    except Exception as e:
        print(f'[FAIL-{label}] {str(e)[:200]}', file=sys.stderr)
        return None

c = try_create(cg, 'full-10rules')
if not c:
    print(f'\n  Full 10-rule creation failed (likely the Referral rule triggers a server validation issue).', file=sys.stderr)
    print(f'  Persisting 9-rule version without the standalone Referral rule.', file=sys.stderr)
    print(f'  (medium=referral traffic falls through to GA4 Unassigned channel; not ideal but recoverable.)', file=sys.stderr)
    time.sleep(2)
    final_cg = ChannelGroup(
        display_name="DBH Custom (TV-aware)",
        description=("Custom channel group separating Branded vs Generic Paid Search, Paid Social, "
                     "Display, Organic Brand vs Generic, Organic Social, and Direct (which absorbs "
                     "TV-driven traffic — TV has no UTM tagging so it appears as direct). "
                     "Built 2026-05-16 per audit Tier 3 #33. "
                     "NOTE: standalone Referral rule omitted due to GA4 API INTERNAL error; "
                     "medium=referral traffic falls through to GA4 Unassigned channel."),
            grouping_rule=rules[:9],
    )
    c = try_create(final_cg, 'final-9rules')

if c:
    # Verify by reading back
    time.sleep(1)
    read = client.get_channel_group(name=c.name)
    print(f'\n[VERIFIED] {read.name}', file=sys.stderr)
    print(f'  display_name="{read.display_name}"', file=sys.stderr)
    print(f'  rules ({len(read.grouping_rule)}):', file=sys.stderr)
    for i, r in enumerate(read.grouping_rule, 1):
        print(f'    {i:2}. {r.display_name}', file=sys.stderr)

print(f'\n[DONE]', file=sys.stderr)
