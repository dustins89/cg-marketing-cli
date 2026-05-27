#!/usr/bin/env python3
"""GA4 deep: per-event parameter coverage matrix, audience definitions detail,
internal traffic filters, custom dimensions across multiple windows for trend."""
import json
import sys
from pathlib import Path
import yaml
from google.oauth2.credentials import Credentials
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import RunReportRequest, Dimension, Metric, DateRange, OrderBy
from google.analytics.admin_v1alpha import AnalyticsAdminServiceClient

cfg = yaml.safe_load((Path.home()/'marketing-cli/google-ads.yaml').read_text())
creds = Credentials(
    token=None,
    refresh_token=cfg['refresh_token'],
    client_id=cfg['client_id'],
    client_secret=cfg['client_secret'],
    token_uri='https://oauth2.googleapis.com/token',
)
prop = f"properties/{cfg['ga4_property_id']}"
data = BetaAnalyticsDataClient(credentials=creds)
admin = AnalyticsAdminServiceClient(credentials=creds)

out = {}

# === Per-event parameter coverage matrix ===
print('Pulling per-event x custom-dim parameter coverage...', file=sys.stderr)
events = ['page_view', 'session_start', 'first_visit', 'user_engagement', 'scroll',
          'form_submit', 'form_start', 'oc_lead_form', 'click', 'video_progress',
          'video_start', 'video_complete', 'phone_call', 'step_1_form_complete',
          'step_2_form_complete', 'contact_us_form_complete']
custom_dims = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
               'fbclid', 'lead_source', 'form_id']
matrix = {}
for ev in events:
    matrix[ev] = {}
    for dim in custom_dims:
        try:
            req = RunReportRequest(
                property=prop,
                dimensions=[Dimension(name=f'customEvent:{dim}')],
                metrics=[Metric(name='eventCount')],
                date_ranges=[DateRange(start_date='7daysAgo', end_date='today')],
                dimension_filter={'filter': {'field_name': 'eventName', 'string_filter': {'value': ev}}},
                limit=200,
            )
            r = data.run_report(req)
            total = sum(int(row.metric_values[0].value) for row in r.rows)
            filled = sum(int(row.metric_values[0].value) for row in r.rows if row.dimension_values[0].value not in ('(not set)','','(none)'))
            unique = len(set(row.dimension_values[0].value for row in r.rows if row.dimension_values[0].value not in ('(not set)','','(none)')))
            matrix[ev][dim] = {'total': total, 'filled': filled, 'unique': unique}
        except Exception as e:
            matrix[ev][dim] = {'err': str(e)[:100]}
out['param_coverage_7d'] = matrix

# === Audience definitions deep ===
print('Pulling audience definitions...', file=sys.stderr)
auds_full = []
for a in admin.list_audiences(parent=prop):
    auds_full.append({
        'name': a.display_name,
        'description': a.description,
        'days': a.membership_duration_days,
        'event_trigger': str(a.event_trigger) if a.event_trigger else None,
        'exclusion_duration_mode': a.exclusion_duration_mode.name,
        'filter_clauses_count': len(a.filter_clauses) if a.filter_clauses else 0,
    })
out['audiences_full'] = auds_full

# === Channel groups + their rule definitions ===
print('Pulling channel groups detail...', file=sys.stderr)
cgs = []
for cg in admin.list_channel_groups(parent=prop):
    cgs.append({
        'name': cg.display_name,
        'description': cg.description,
        'primary': cg.primary,
        'system_defined': cg.system_defined,
        'grouping_rules_count': len(cg.grouping_rule) if cg.grouping_rule else 0,
    })
out['channel_groups_full'] = cgs

# === Conversion events with custom counting + values ===
print('Key events detail...', file=sys.stderr)
ke_full = []
for k in admin.list_key_events(parent=prop):
    ke_full.append({
        'event_name': k.event_name,
        'counting_method': k.counting_method.name,
        'default_value_numeric': k.default_value.numeric_value if k.default_value else None,
        'default_value_currency': k.default_value.currency_code if k.default_value else None,
        'custom': k.custom,
        'create_time': str(k.create_time),
    })
out['key_events_full'] = ke_full

# === Data filters (internal traffic exclusion) ===
print('Data filters / streams...', file=sys.stderr)
streams = list(admin.list_data_streams(parent=prop))
out['streams_full'] = []
for s in streams:
    item = {
        'name': s.display_name,
        'type': s.type_.name,
    }
    if s.web_stream_data:
        item['measurement_id'] = s.web_stream_data.measurement_id
        item['default_uri'] = s.web_stream_data.default_uri
        item['firebase_app_id'] = s.web_stream_data.firebase_app_id
    out['streams_full'].append(item)
    # Try data redaction settings + measurement protocol secrets
    try:
        dr = admin.get_data_redaction_settings(name=f'{s.name}/dataRedactionSettings')
        item['redaction'] = {
            'email_redaction': dr.email_redaction_enabled,
            'query_param_redaction': dr.query_parameter_redaction_enabled,
            'query_keys': list(dr.query_parameter_keys),
        }
    except Exception as e:
        item['redaction_err'] = str(e)[:120]
    try:
        em = admin.get_enhanced_measurement_settings(name=f'{s.name}/enhancedMeasurementSettings')
        item['enhanced_measurement'] = {
            'scrolls': em.scrolls_enabled,
            'outbound_clicks': em.outbound_clicks_enabled,
            'site_search': em.site_search_enabled,
            'form_interactions': em.form_interactions_enabled,
            'video_engagement': em.video_engagement_enabled,
            'file_downloads': em.file_downloads_enabled,
            'page_changes': em.page_changes_enabled,
            'search_query_param': em.search_query_parameter,
            'uri_query_param': em.uri_query_parameter,
        }
    except Exception as e:
        item['em_err'] = str(e)[:120]

# === BigQuery link detail + excluded events ===
print('BQ links detail...', file=sys.stderr)
bqs = []
for b in admin.list_big_query_links(parent=prop):
    bqs.append({
        'project': b.project,
        'create_time': str(b.create_time),
        'daily_export_enabled': b.daily_export_enabled,
        'streaming_export_enabled': b.streaming_export_enabled,
        'fresh_daily_export_enabled': b.fresh_daily_export_enabled,
        'include_advertising_id': b.include_advertising_id,
        'export_streams': list(b.export_streams) if b.export_streams else [],
        'excluded_events': list(b.excluded_events),
        'dataset_location': b.dataset_location,
    })
out['bq_links_full'] = bqs

with open('/tmp/ga4_deep_v2.json', 'w') as f:
    json.dump(out, f, indent=2, default=str)
print(f'[done] /tmp/ga4_deep_v2.json', file=sys.stderr)
