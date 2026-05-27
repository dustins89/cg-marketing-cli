"""yt — Click CLI for YouTube Data + Analytics."""
from __future__ import annotations

import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="google.*")
warnings.filterwarnings("ignore", message=".*LibreSSL.*")

import click
from rich.console import Console

from . import __version__
from . import pull as pull_mod
from .client import get_service, get_channel_id
from .format import emit

console = Console()


@click.group(help="Personal YouTube CLI — channels, videos, search, analytics.")
@click.version_option(__version__, prog_name="yt")
def cli() -> None:
    pass


def _fmt(f):
    return click.option(
        "--format", "fmt", type=click.Choice(["table", "json"]), default="table",
    )(f)


@cli.group("pull")
def pull_group() -> None:
    """Read commands — pull data from YouTube."""


@pull_group.command("channels")
@_fmt
def channels_cmd(fmt):
    """List YouTube channels owned by the authenticated user (mine=true)."""
    svc = get_service("data")
    rows = pull_mod.pull_my_channels(svc)
    emit(rows, pull_mod.COLUMNS["channels"], fmt, title=f"My channels ({len(rows)})")


@pull_group.command("videos")
@click.option("--channel", default=None, help="Channel ID. Defaults to youtube_channel_id from yaml.")
@click.option("--limit", default=50, type=int, help="Max videos to fetch (default 50).")
@_fmt
def videos_cmd(channel, limit, fmt):
    """List recent videos from a channel."""
    svc = get_service("data")
    ch = channel or get_channel_id()
    if not ch:
        raise click.ClickException(
            "No channel specified. Pass --channel UCxxx or add youtube_channel_id to google-ads.yaml."
        )
    rows = pull_mod.pull_videos(svc, ch, limit)
    emit(rows, pull_mod.COLUMNS["videos"], fmt, title=f"Videos for {ch} ({len(rows)})")


@pull_group.command("search")
@click.argument("query", nargs=-1, required=True)
@click.option("--channel", default=None, help="Restrict to a channel ID.")
@click.option("--limit", default=25, type=int, help="Max results (default 25).")
@_fmt
def search_cmd(query, channel, limit, fmt):
    """Search YouTube. Optionally restrict to one channel."""
    svc = get_service("data")
    q = " ".join(query)
    rows = pull_mod.pull_search(svc, q, channel, limit)
    emit(rows, pull_mod.COLUMNS["search"], fmt, title=f"Search '{q}' ({len(rows)})")


@pull_group.command("analytics")
@click.option("--channel", default=None, help="Channel ID. Defaults to youtube_channel_id from yaml.")
@click.option("--days", default=30, type=int, help="Lookback days (default 30).")
@click.option("--dimensions", default="day", help="YT Analytics dimensions (default 'day').")
@click.option("--metrics", default=None, help="Override default metric set.")
@_fmt
def analytics_cmd(channel, days, dimensions, metrics, fmt):
    """YouTube Analytics for a channel — views, watch time, subscriber changes by day."""
    svc = get_service("analytics")
    ch = channel or get_channel_id()
    if not ch:
        raise click.ClickException(
            "No channel specified. Pass --channel UCxxx or add youtube_channel_id to google-ads.yaml."
        )
    rows = pull_mod.pull_analytics(svc, ch, days, dimensions, metrics)
    cols = list(rows[0].keys()) if rows else []
    emit(rows, cols, fmt, title=f"Analytics ({days}d, by {dimensions}) — {ch}")


def _channel_or_yaml(channel):
    ch = channel or get_channel_id()
    if not ch:
        raise click.ClickException("Pass --channel UCxxx or add youtube_channel_id to yaml.")
    return ch


@pull_group.command("comments")
@click.option("--video", "video_id", default=None,
              help="Video ID (one or the other required).")
@click.option("--channel", default=None,
              help="Channel ID — pulls comments from all videos.")
@click.option("--limit", default=100, type=int)
@click.option("--order", type=click.Choice(["time", "relevance"]), default="time")
@_fmt
def comments_cmd(video_id, channel, limit, order, fmt):
    """Top-level comment threads on a video or all videos in a channel."""
    svc = get_service("data")
    rows = pull_mod.pull_comments(svc, video_id=video_id, channel_id=channel,
                                 max_results=limit, order=order)
    emit(rows, pull_mod.COLUMNS["comments"], fmt, title=f"Comments ({len(rows)})")


@pull_group.command("captions")
@click.argument("video_id")
@_fmt
def captions_cmd(video_id, fmt):
    """List caption tracks on a video."""
    svc = get_service("data")
    rows = pull_mod.pull_captions(svc, video_id)
    emit(rows, pull_mod.COLUMNS["captions"], fmt,
         title=f"Captions ({len(rows)}) — video {video_id}")


@pull_group.command("playlists")
@click.option("--channel", default=None, help="Channel ID (omit for --mine).")
@click.option("--mine", is_flag=True, help="Playlists owned by the authenticated user.")
@click.option("--limit", default=50, type=int)
@_fmt
def playlists_cmd(channel, mine, limit, fmt):
    """List playlists on a channel (or yours)."""
    svc = get_service("data")
    ch = channel if channel else (None if mine else _channel_or_yaml(None))
    rows = pull_mod.pull_playlists(svc, channel_id=ch, mine=mine, max_results=limit)
    emit(rows, pull_mod.COLUMNS["playlists"], fmt,
         title=f"Playlists ({len(rows)})")


@pull_group.command("playlist-items")
@click.argument("playlist_id")
@click.option("--limit", default=200, type=int)
@_fmt
def playlist_items_cmd(playlist_id, limit, fmt):
    """Videos in a playlist (in playlist order)."""
    svc = get_service("data")
    rows = pull_mod.pull_playlist_items(svc, playlist_id, max_results=limit)
    emit(rows, pull_mod.COLUMNS["playlist-items"], fmt,
         title=f"Playlist items ({len(rows)}) — {playlist_id}")


@pull_group.command("subscriptions")
@click.option("--channel", default=None, help="Channel whose subscriptions to list (omit for --mine).")
@click.option("--mine/--not-mine", default=True)
@click.option("--limit", default=200, type=int)
@_fmt
def subscriptions_cmd(channel, mine, limit, fmt):
    """Channels the authenticated user (or `--channel`) is subscribed to."""
    svc = get_service("data")
    rows = pull_mod.pull_subscriptions(svc, mine=mine and not channel,
                                       channel_id=channel, max_results=limit)
    emit(rows, pull_mod.COLUMNS["subscriptions"], fmt,
         title=f"Subscriptions ({len(rows)})")


@pull_group.command("video-categories")
@click.option("--region", default="US")
@_fmt
def video_categories_cmd(region, fmt):
    """YouTube video categories for a region."""
    svc = get_service("data")
    rows = pull_mod.pull_video_categories(svc, region_code=region)
    emit(rows, pull_mod.COLUMNS["video-categories"], fmt,
         title=f"Video categories ({len(rows)}) — {region}")


# ─── analytics presets — common report shapes ────────────────────────────────

@cli.group("analytics")
def analytics_group() -> None:
    """Curated YouTube Analytics reports — traffic sources, demographics, retention, etc."""


def _run_preset(fn, channel, days, fmt, **extra):
    svc = get_service("analytics")
    ch = _channel_or_yaml(channel)
    rows = fn(svc, ch, days=days, **extra) if "days" in fn.__code__.co_varnames else fn(svc, ch, days, **extra)
    cols = list(rows[0].keys()) if rows else []
    emit(rows, cols, fmt, title=f"{fn.__name__} ({days}d, {len(rows)}) — {ch}")


@analytics_group.command("traffic-sources")
@click.option("--channel", default=None)
@click.option("--days", default=30, type=int)
@_fmt
def traffic_sources_cmd(channel, days, fmt):
    """Where viewers come from (search / browse / suggested / external)."""
    _run_preset(pull_mod.analytics_traffic_sources, channel, days, fmt)


@analytics_group.command("search-terms")
@click.option("--channel", default=None)
@click.option("--days", default=30, type=int)
@click.option("--limit", default=50, type=int)
@_fmt
def search_terms_cmd(channel, days, limit, fmt):
    """Top YouTube-search terms that brought viewers."""
    svc = get_service("analytics")
    ch = _channel_or_yaml(channel)
    rows = pull_mod.analytics_search_terms(svc, ch, days=days, max_results=limit)
    cols = list(rows[0].keys()) if rows else []
    emit(rows, cols, fmt, title=f"YT search terms ({days}d) — {ch}")


@analytics_group.command("demographics")
@click.option("--channel", default=None)
@click.option("--days", default=30, type=int)
@_fmt
def demographics_cmd(channel, days, fmt):
    """Viewer age × gender."""
    _run_preset(pull_mod.analytics_demographics, channel, days, fmt)


@analytics_group.command("geography")
@click.option("--channel", default=None)
@click.option("--days", default=30, type=int)
@_fmt
def geography_cmd(channel, days, fmt):
    """Top countries by views."""
    _run_preset(pull_mod.analytics_geography, channel, days, fmt)


@analytics_group.command("devices")
@click.option("--channel", default=None)
@click.option("--days", default=30, type=int)
@_fmt
def devices_cmd(channel, days, fmt):
    """Mobile / desktop / TV split."""
    _run_preset(pull_mod.analytics_devices, channel, days, fmt)


@analytics_group.command("top-videos")
@click.option("--channel", default=None)
@click.option("--days", default=30, type=int)
@click.option("--limit", default=25, type=int)
@_fmt
def top_videos_cmd(channel, days, limit, fmt):
    """Top-performing videos in the window."""
    svc = get_service("analytics")
    ch = _channel_or_yaml(channel)
    rows = pull_mod.analytics_top_videos(svc, ch, days=days, max_results=limit)
    cols = list(rows[0].keys()) if rows else []
    emit(rows, cols, fmt, title=f"Top videos ({days}d) — {ch}")


@analytics_group.command("retention")
@click.option("--channel", default=None)
@click.option("--video", "video_id", required=True)
@click.option("--days", default=30, type=int)
@_fmt
def retention_cmd(channel, video_id, days, fmt):
    """Audience retention curve for one video."""
    svc = get_service("analytics")
    ch = _channel_or_yaml(channel)
    rows = pull_mod.analytics_retention(svc, ch, video_id, days=days)
    cols = list(rows[0].keys()) if rows else []
    emit(rows, cols, fmt, title=f"Retention — {video_id}")


@analytics_group.command("cards")
@click.option("--channel", default=None)
@click.option("--days", default=30, type=int)
@_fmt
def cards_cmd(channel, days, fmt):
    """Card impressions + clicks + CTR (creative effectiveness)."""
    _run_preset(pull_mod.analytics_cards, channel, days, fmt)


@analytics_group.command("end-screens")
@click.option("--channel", default=None)
@click.option("--days", default=30, type=int)
@_fmt
def end_screens_cmd(channel, days, fmt):
    """End-screen element impressions + clicks."""
    _run_preset(pull_mod.analytics_end_screens, channel, days, fmt)


@analytics_group.command("subscriber-status")
@click.option("--channel", default=None)
@click.option("--days", default=30, type=int)
@_fmt
def subscriber_status_cmd(channel, days, fmt):
    """Watch behavior split by subscribed vs not-subscribed viewers."""
    _run_preset(pull_mod.analytics_subscriber_status, channel, days, fmt)


def main():
    try:
        cli()
    except Exception as e:
        console.print(f"[red]error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
