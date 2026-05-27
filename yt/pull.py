"""YouTube Data + Analytics pullers."""
from __future__ import annotations

from datetime import date, timedelta


def pull_my_channels(data_svc) -> list[dict]:
    """Channels owned by the authenticated user (mine=true)."""
    resp = data_svc.channels().list(
        part="id,snippet,statistics,contentDetails,status",
        mine=True,
        maxResults=50,
    ).execute()
    rows = []
    for ch in resp.get("items", []):
        s = ch.get("statistics", {})
        rows.append({
            "id": ch.get("id"),
            "title": (ch.get("snippet") or {}).get("title"),
            "customUrl": (ch.get("snippet") or {}).get("customUrl"),
            "subscribers": int(s.get("subscriberCount", 0)),
            "videoCount": int(s.get("videoCount", 0)),
            "viewCount": int(s.get("viewCount", 0)),
            "uploadsPlaylist": (ch.get("contentDetails", {}).get("relatedPlaylists") or {}).get("uploads"),
            "publishedAt": (ch.get("snippet") or {}).get("publishedAt"),
        })
    return rows


def pull_videos(data_svc, channel_id: str, max_results: int = 50) -> list[dict]:
    """Recent videos from a channel via the channel's uploads playlist."""
    # Get uploads playlist ID
    ch = data_svc.channels().list(part="contentDetails", id=channel_id).execute()
    items = ch.get("items", [])
    if not items:
        return []
    uploads_pl = (items[0].get("contentDetails", {}).get("relatedPlaylists") or {}).get("uploads")
    if not uploads_pl:
        return []

    # Page through uploads
    video_ids = []
    page_token = None
    while len(video_ids) < max_results:
        params = {"part": "contentDetails", "playlistId": uploads_pl, "maxResults": min(50, max_results - len(video_ids))}
        if page_token:
            params["pageToken"] = page_token
        plr = data_svc.playlistItems().list(**params).execute()
        for it in plr.get("items", []):
            video_ids.append(it["contentDetails"]["videoId"])
        page_token = plr.get("nextPageToken")
        if not page_token:
            break

    # Batch-fetch video details (50 at a time)
    rows = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        vr = data_svc.videos().list(
            part="id,snippet,statistics,contentDetails,status",
            id=",".join(batch),
        ).execute()
        for v in vr.get("items", []):
            sn = v.get("snippet", {})
            st = v.get("statistics", {})
            cd = v.get("contentDetails", {})
            rows.append({
                "id": v.get("id"),
                "title": sn.get("title"),
                "publishedAt": sn.get("publishedAt"),
                "duration": cd.get("duration"),
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)),
                "tags": ",".join(sn.get("tags", []) or [])[:120],
                "categoryId": sn.get("categoryId"),
                "privacyStatus": (v.get("status") or {}).get("privacyStatus"),
            })
    return rows


def pull_search(data_svc, query: str, channel_id: str | None = None, max_results: int = 25) -> list[dict]:
    """Search YouTube videos. Optionally restrict to a channel."""
    params = {"part": "id,snippet", "q": query, "type": "video", "maxResults": min(50, max_results), "order": "relevance"}
    if channel_id:
        params["channelId"] = channel_id
    resp = data_svc.search().list(**params).execute()
    rows = []
    for it in resp.get("items", []):
        sn = it.get("snippet", {})
        rows.append({
            "videoId": it.get("id", {}).get("videoId"),
            "title": sn.get("title"),
            "channelTitle": sn.get("channelTitle"),
            "publishedAt": sn.get("publishedAt"),
            "description": (sn.get("description") or "")[:120],
        })
    return rows


def pull_analytics(yta_svc, channel_id: str, days: int, dimensions: str = "day", metrics: str | None = None, sort: str | None = None) -> list[dict]:
    """YouTube Analytics for a channel.

    Common dimension/metric combos:
      day + views,estimatedMinutesWatched,averageViewDuration,subscribersGained
      video + views (top videos — must sort by metric, e.g., sort='-views')
      country + views (geo breakdown)
      insightTrafficSourceType + views (where viewers come from)
      deviceType + views (mobile vs desktop vs TV)

    `sort` defaults to the dimension name except for `video` which requires sort by metric.
    """
    if metrics is None:
        metrics = "views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost"
    if sort is None:
        # video dimension requires sort by metric (API constraint)
        sort = "-views" if dimensions == "video" else dimensions
    end = date.today() - timedelta(days=2)  # YT Analytics lags 1-2 days
    start = end - timedelta(days=days)
    resp = yta_svc.reports().query(
        ids=f"channel=={channel_id}",
        startDate=start.isoformat(),
        endDate=end.isoformat(),
        dimensions=dimensions,
        metrics=metrics,
        sort=sort,
        maxResults=200,
    ).execute()
    cols = [c["name"] for c in resp.get("columnHeaders", [])]
    rows = []
    for row in resp.get("rows", []) or []:
        rows.append(dict(zip(cols, row)))
    return rows


def pull_comments(data_svc, video_id: str | None = None, channel_id: str | None = None,
                 max_results: int = 100, order: str = "time") -> list[dict]:
    """Pull top-level comment threads on a video (or all videos in a channel).

    order: 'time' (newest first) or 'relevance' (top comments).
    """
    if not video_id and not channel_id:
        raise ValueError("Provide either video_id or channel_id.")
    rows = []
    page_token = None
    while len(rows) < max_results:
        params = {
            "part": "snippet,replies",
            "maxResults": min(100, max_results - len(rows)),
            "order": order,
            "textFormat": "plainText",
        }
        if video_id:
            params["videoId"] = video_id
        if channel_id:
            params["allThreadsRelatedToChannelId"] = channel_id
        if page_token:
            params["pageToken"] = page_token
        try:
            resp = data_svc.commentThreads().list(**params).execute()
        except Exception as e:
            # Comments disabled on the video returns a 403; surface a clear row.
            return [{"error": str(e)[:200]}]
        for thread in resp.get("items", []):
            top = (thread.get("snippet") or {}).get("topLevelComment") or {}
            ts = (top.get("snippet") or {})
            rows.append({
                "comment_id": top.get("id"),
                "video_id": ts.get("videoId"),
                "author": ts.get("authorDisplayName"),
                "author_channel_id": (ts.get("authorChannelId") or {}).get("value"),
                "text": (ts.get("textDisplay") or "")[:400],
                "like_count": int(ts.get("likeCount", 0) or 0),
                "reply_count": int((thread.get("snippet") or {}).get("totalReplyCount", 0) or 0),
                "published_at": ts.get("publishedAt"),
                "updated_at": ts.get("updatedAt"),
                "is_public": (thread.get("snippet") or {}).get("isPublic"),
                "can_reply": (thread.get("snippet") or {}).get("canReply"),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return rows


def pull_captions(data_svc, video_id: str) -> list[dict]:
    """List caption tracks on a video (does NOT download the caption text)."""
    resp = data_svc.captions().list(part="id,snippet", videoId=video_id).execute()
    rows = []
    for c in resp.get("items", []):
        s = c.get("snippet") or {}
        rows.append({
            "id": c.get("id"),
            "video_id": s.get("videoId"),
            "language": s.get("language"),
            "name": s.get("name"),
            "audio_track_type": s.get("audioTrackType"),
            "is_cc": s.get("isCC"),
            "is_draft": s.get("isDraft"),
            "is_auto_synced": s.get("isAutoSynced"),
            "track_kind": s.get("trackKind"),
            "status": s.get("status"),
            "last_updated": s.get("lastUpdated"),
        })
    return rows


def pull_playlists(data_svc, channel_id: str | None = None, mine: bool = False,
                  max_results: int = 50) -> list[dict]:
    """List playlists on a channel (or owned by the authenticated user)."""
    params = {"part": "id,snippet,contentDetails,status", "maxResults": min(50, max_results)}
    if mine:
        params["mine"] = True
    elif channel_id:
        params["channelId"] = channel_id
    else:
        raise ValueError("Provide channel_id or mine=True.")
    rows = []
    page_token = None
    while len(rows) < max_results:
        if page_token:
            params["pageToken"] = page_token
        resp = data_svc.playlists().list(**params).execute()
        for pl in resp.get("items", []):
            s = pl.get("snippet") or {}
            rows.append({
                "id": pl.get("id"),
                "title": s.get("title"),
                "description": (s.get("description") or "")[:200],
                "channel_id": s.get("channelId"),
                "published_at": s.get("publishedAt"),
                "video_count": int((pl.get("contentDetails") or {}).get("itemCount", 0) or 0),
                "privacy_status": (pl.get("status") or {}).get("privacyStatus"),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return rows


def pull_playlist_items(data_svc, playlist_id: str, max_results: int = 200) -> list[dict]:
    """Videos in a playlist (in playlist order)."""
    rows = []
    page_token = None
    while len(rows) < max_results:
        params = {"part": "id,snippet,contentDetails",
                  "playlistId": playlist_id,
                  "maxResults": min(50, max_results - len(rows))}
        if page_token:
            params["pageToken"] = page_token
        resp = data_svc.playlistItems().list(**params).execute()
        for it in resp.get("items", []):
            s = it.get("snippet") or {}
            cd = it.get("contentDetails") or {}
            rows.append({
                "position": s.get("position"),
                "video_id": cd.get("videoId"),
                "title": s.get("title"),
                "channel_id": s.get("videoOwnerChannelId"),
                "channel_title": s.get("videoOwnerChannelTitle"),
                "published_at": cd.get("videoPublishedAt"),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return rows


def pull_subscriptions(data_svc, mine: bool = True,
                      channel_id: str | None = None,
                      max_results: int = 200) -> list[dict]:
    """Channels the authenticated user is subscribed to (or `channel_id` if specified)."""
    params = {"part": "id,snippet,contentDetails",
              "maxResults": min(50, max_results)}
    if mine and not channel_id:
        params["mine"] = True
    elif channel_id:
        params["channelId"] = channel_id
    rows = []
    page_token = None
    while len(rows) < max_results:
        if page_token:
            params["pageToken"] = page_token
        resp = data_svc.subscriptions().list(**params).execute()
        for sub in resp.get("items", []):
            s = sub.get("snippet") or {}
            cd = sub.get("contentDetails") or {}
            rows.append({
                "subscription_id": sub.get("id"),
                "channel_id": (s.get("resourceId") or {}).get("channelId"),
                "channel_title": s.get("title"),
                "description": (s.get("description") or "")[:200],
                "published_at": s.get("publishedAt"),
                "total_item_count": cd.get("totalItemCount"),
                "new_item_count": cd.get("newItemCount"),
            })
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return rows


def pull_video_categories(data_svc, region_code: str = "US") -> list[dict]:
    """YouTube video categories for a region."""
    resp = data_svc.videoCategories().list(part="id,snippet", regionCode=region_code).execute()
    rows = []
    for c in resp.get("items", []):
        s = c.get("snippet") or {}
        rows.append({
            "id": c.get("id"),
            "title": s.get("title"),
            "channel_id": s.get("channelId"),
            "assignable": s.get("assignable"),
        })
    return rows


# ─── Analytics presets — common report shapes ────────────────────────────────

def analytics_traffic_sources(yta_svc, channel_id: str, days: int = 30) -> list[dict]:
    """Where viewers come from (search, browse features, suggested, external, etc.)."""
    return pull_analytics(
        yta_svc, channel_id, days=days,
        dimensions="insightTrafficSourceType",
        metrics="views,estimatedMinutesWatched,averageViewDuration",
        sort="-views",
    )


def analytics_search_terms(yta_svc, channel_id: str, days: int = 30,
                          max_results: int = 50) -> list[dict]:
    """Top YouTube search terms that brought viewers to your videos."""
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days)
    resp = yta_svc.reports().query(
        ids=f"channel=={channel_id}",
        startDate=start.isoformat(), endDate=end.isoformat(),
        dimensions="insightTrafficSourceDetail",
        metrics="views,estimatedMinutesWatched",
        filters="insightTrafficSourceType==YT_SEARCH",
        sort="-views", maxResults=max_results,
    ).execute()
    cols = [c["name"] for c in resp.get("columnHeaders", [])]
    return [dict(zip(cols, r)) for r in (resp.get("rows") or [])]


def analytics_demographics(yta_svc, channel_id: str, days: int = 30) -> list[dict]:
    """Viewer age × gender demographics."""
    return pull_analytics(
        yta_svc, channel_id, days=days,
        dimensions="ageGroup,gender",
        metrics="viewerPercentage",
        sort="-viewerPercentage",
    )


def analytics_geography(yta_svc, channel_id: str, days: int = 30,
                       max_results: int = 50) -> list[dict]:
    """Top countries by views."""
    return pull_analytics(
        yta_svc, channel_id, days=days,
        dimensions="country",
        metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained",
        sort="-views",
    )


def analytics_devices(yta_svc, channel_id: str, days: int = 30) -> list[dict]:
    """Mobile vs desktop vs TV breakdown."""
    return pull_analytics(
        yta_svc, channel_id, days=days,
        dimensions="deviceType",
        metrics="views,estimatedMinutesWatched,averageViewDuration",
        sort="-views",
    )


def analytics_top_videos(yta_svc, channel_id: str, days: int = 30,
                        max_results: int = 25) -> list[dict]:
    """Top-performing videos by views in the window."""
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days)
    resp = yta_svc.reports().query(
        ids=f"channel=={channel_id}",
        startDate=start.isoformat(), endDate=end.isoformat(),
        dimensions="video",
        metrics="views,estimatedMinutesWatched,averageViewDuration,"
                "averageViewPercentage,subscribersGained,likes,shares,comments",
        sort="-views", maxResults=max_results,
    ).execute()
    cols = [c["name"] for c in resp.get("columnHeaders", [])]
    return [dict(zip(cols, r)) for r in (resp.get("rows") or [])]


def analytics_retention(yta_svc, channel_id: str, video_id: str,
                       days: int = 30) -> list[dict]:
    """Audience-retention curve for a specific video (elapsed-time × retention %)."""
    end = date.today() - timedelta(days=2)
    start = end - timedelta(days=days)
    resp = yta_svc.reports().query(
        ids=f"channel=={channel_id}",
        startDate=start.isoformat(), endDate=end.isoformat(),
        dimensions="elapsedVideoTimeRatio",
        metrics="audienceWatchRatio,relativeRetentionPerformance",
        filters=f"video=={video_id}",
        sort="elapsedVideoTimeRatio",
    ).execute()
    cols = [c["name"] for c in resp.get("columnHeaders", [])]
    return [dict(zip(cols, r)) for r in (resp.get("rows") or [])]


def analytics_cards(yta_svc, channel_id: str, days: int = 30) -> list[dict]:
    """Card impressions + clicks + CTR — feeds creative effectiveness."""
    return pull_analytics(
        yta_svc, channel_id, days=days,
        dimensions="day",
        metrics="cardImpressions,cardClicks,cardClickRate,"
                "cardTeaserImpressions,cardTeaserClicks,cardTeaserClickRate",
        sort="day",
    )


def analytics_end_screens(yta_svc, channel_id: str, days: int = 30) -> list[dict]:
    """End-screen element impressions + clicks."""
    return pull_analytics(
        yta_svc, channel_id, days=days,
        dimensions="day",
        metrics="endScreenElementImpressions,endScreenElementClicks,"
                "endScreenElementClickRate",
        sort="day",
    )


def analytics_subscriber_status(yta_svc, channel_id: str, days: int = 30) -> list[dict]:
    """Watch behavior split by subscribed vs not-subscribed viewers."""
    return pull_analytics(
        yta_svc, channel_id, days=days,
        dimensions="subscribedStatus",
        metrics="views,estimatedMinutesWatched,averageViewDuration",
        sort="-views",
    )


COLUMNS = {
    "channels": ["id", "title", "customUrl", "subscribers", "videoCount", "viewCount", "publishedAt"],
    "videos": ["id", "title", "publishedAt", "duration", "views", "likes", "comments", "privacyStatus"],
    "search": ["videoId", "title", "channelTitle", "publishedAt", "description"],
    "comments": ["published_at", "author", "text", "like_count", "reply_count", "video_id"],
    "captions": ["language", "name", "track_kind", "is_cc", "is_auto_synced", "status", "last_updated"],
    "playlists": ["id", "title", "video_count", "privacy_status", "published_at"],
    "playlist-items": ["position", "video_id", "title", "channel_title", "published_at"],
    "subscriptions": ["channel_title", "channel_id", "total_item_count", "new_item_count", "published_at"],
    "video-categories": ["id", "title", "assignable", "channel_id"],
}
