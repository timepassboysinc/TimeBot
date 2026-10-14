from datetime import datetime, timezone

import discord
from discord.ext import commands

from cogs.core import BLUE
from logging_utils import send_log


class ServerLogs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        embed = discord.Embed(title="🆕 Channel created", description=f"{channel.mention if hasattr(channel, 'mention') else channel.name}\nID: `{channel.id}`", color=BLUE, timestamp=datetime.now(timezone.utc))
        if getattr(channel, "category", None):
            embed.add_field(name="Category", value=channel.category.name, inline=True)
        await send_log(channel.guild, "server", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        embed = discord.Embed(title="🗑️ Channel deleted", description=f"**{discord.utils.escape_markdown(channel.name)}** (`{channel.id}`)", color=BLUE, timestamp=datetime.now(timezone.utc))
        if getattr(channel, "category", None):
            embed.add_field(name="Category", value=channel.category.name, inline=True)
        await send_log(channel.guild, "server", embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        if getattr(before, "topic", None) != getattr(after, "topic", None):
            changes.append(f"**Topic:** {(before.topic or 'none')[:300]} → {(after.topic or 'none')[:300]}")
        if getattr(before, "category_id", None) != getattr(after, "category_id", None):
            old_cat = before.category.name if getattr(before, "category", None) else "none"
            new_cat = after.category.name if getattr(after, "category", None) else "none"
            changes.append(f"**Category:** {old_cat} → {new_cat}")
        if not changes:
            return
        embed = discord.Embed(title="✏️ Channel updated", description=f"{after.mention if hasattr(after, 'mention') else after.name} (`{after.id}`)\n" + "\n".join(changes), color=BLUE, timestamp=datetime.now(timezone.utc))
        await send_log(after.guild, "server", embed)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        embed = discord.Embed(title="🆕 Role created", description=f"{role.mention} (`{role.id}`)", color=BLUE, timestamp=datetime.now(timezone.utc))
        await send_log(role.guild, "server", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        embed = discord.Embed(title="🗑️ Role deleted", description=f"**{discord.utils.escape_markdown(role.name)}** (`{role.id}`)", color=BLUE, timestamp=datetime.now(timezone.utc))
        await send_log(role.guild, "server", embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        if before.permissions != after.permissions:
            changed = [name.replace("_", " ").title() for name, old in before.permissions if getattr(after.permissions, name) != old]
            changes.append("**Permissions changed:** " + (", ".join(changed) if changed else "updated"))
        if before.hoist != after.hoist:
            changes.append(f"**Hoisted:** {before.hoist} → {after.hoist}")
        if before.mentionable != after.mentionable:
            changes.append(f"**Mentionable:** {before.mentionable} → {after.mentionable}")
        if not changes:
            return
        embed = discord.Embed(title="✏️ Role updated", description=f"{after.mention} (`{after.id}`)\n" + "\n".join(changes), color=BLUE, timestamp=datetime.now(timezone.utc))
        await send_log(after.guild, "server", embed)

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        if before.verification_level != after.verification_level:
            changes.append(f"**Verification level:** {before.verification_level} → {after.verification_level}")
        if before.explicit_content_filter != after.explicit_content_filter:
            changes.append(f"**Explicit content filter:** {before.explicit_content_filter} → {after.explicit_content_filter}")
        if before.default_notifications != after.default_notifications:
            changes.append(f"**Default notifications:** {before.default_notifications} → {after.default_notifications}")
        if not changes:
            return
        embed = discord.Embed(title="⚙️ Server settings updated", description="\n".join(changes), color=BLUE, timestamp=datetime.now(timezone.utc))
        await send_log(after, "server", embed)


async def setup(bot):
    await bot.add_cog(ServerLogs(bot))
