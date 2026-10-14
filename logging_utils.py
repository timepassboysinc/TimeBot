"""Shared per-guild event-log routing for Time Bot."""

import discord

import database

LOG_TYPES = ("ban", "warn", "timeout", "join", "leave", "invite", "server", "moderation")
LOG_TITLES = {
    "ban": "Ban logs",
    "warn": "Warn logs",
    "timeout": "Timeout logs",
    "join": "Join logs",
    "leave": "Leave logs",
    "invite": "Invite logs",
    "server": "Server logs",
    "moderation": "Moderation logs",
}

LEGACY_CHANNEL_KEYS = {
    "ban": "modlog_channel",
    "warn": "modlog_channel",
    "timeout": "modlog_channel",
    "moderation": "modlog_channel",
    "join": "actionlog_channel",
    "leave": "actionlog_channel",
    "invite": "actionlog_channel",
    "server": "actionlog_channel",
}


async def send_log(guild, category, embed, *, include_moderation=False):
    """Send to a category channel and optionally the general moderation log."""
    if not guild or category not in LOG_TYPES:
        return

    categories = [category]
    if include_moderation and category != "moderation":
        categories.append("moderation")

    channel_ids = []
    for item in categories:
        channel_id = await database.get_setting(guild.id, f"log_channel_{item}")
        if not channel_id:
            legacy_key = LEGACY_CHANNEL_KEYS.get(item)
            channel_id = await database.get_setting(guild.id, legacy_key) if legacy_key else None
        if channel_id and channel_id not in channel_ids:
            channel_ids.append(channel_id)

    for channel_id in channel_ids:
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue
        if not hasattr(channel, "send"):
            continue
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except (discord.Forbidden, discord.HTTPException):
            continue
