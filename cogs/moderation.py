import asyncio
from datetime import datetime, timedelta, timezone
import re

import aiosqlite
import discord
from discord.ext import commands

import access_control
import database
from logging_utils import LOG_TITLES, LOG_TYPES, send_log

BLUE = 0x176BFF


def duration_seconds(text):
    match = re.fullmatch(r"(\d+)\s*(s|m|h|d|w)", text.lower())
    if not match:
        return None
    number, unit = int(match.group(1)), match.group(2)
    return number * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def log_case(self, ctx, member_id, action, reason, expires_at=None):
        stamp = datetime.now(timezone.utc).isoformat()
        case_id = await database.add_case(ctx.guild.id, member_id, ctx.author.id, action, reason, stamp, expires_at)
        embed = discord.Embed(title=f"🛡️ Case #{case_id} • {action.title()}", color=BLUE, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Member", value=f"<@{member_id}> (`{member_id}`)", inline=True)
        embed.add_field(name="Moderator", value=ctx.author.mention, inline=True)
        embed.add_field(name="Reason", value=reason[:1000], inline=False)
        if expires_at:
            embed.add_field(name="Expires", value=f"<t:{int(datetime.fromisoformat(expires_at).timestamp())}:R>", inline=True)
        category = "warn" if action == "warn" else "timeout" if "timeout" in action else "ban" if action in {"ban", "unban", "softban", "autoban"} else "moderation"
        await send_log(ctx.guild, category, embed, include_moderation=category != "moderation")
        return case_id

    async def _recent_bot_case(self, guild_id, member_id, actions):
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=15)).isoformat()
        marks = ",".join("?" for _ in actions)
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute(
                f"SELECT 1 FROM cases WHERE guild_id=? AND user_id=? AND action IN ({marks}) AND created_at>=? LIMIT 1",
                (guild_id, member_id, *actions, cutoff),
            ) as cur:
                return await cur.fetchone() is not None

    async def _audit_actor(self, guild, action, member_id):
        try:
            async for entry in guild.audit_logs(limit=6, action=action):
                if getattr(entry.target, "id", None) == member_id and (discord.utils.utcnow() - entry.created_at).total_seconds() < 20:
                    return entry.user, entry.reason or "No reason provided"
        except (discord.Forbidden, discord.HTTPException):
            pass
        return None, "No reason provided"

    async def target_ok(self, ctx, member):
        if member.id == ctx.author.id:
            await ctx.reply("You can't moderate yourself.", mention_author=False)
            return False
        if member.id == ctx.guild.owner_id:
            await ctx.reply("I can't moderate the server owner.", mention_author=False)
            return False
        if ctx.author.id != ctx.guild.owner_id and member.top_role >= ctx.author.top_role:
            await ctx.reply("Your highest role must be above the target's role.", mention_author=False)
            return False
        if ctx.guild.me.top_role <= member.top_role:
            await ctx.reply("Move Time Bot's role above the target's role.", mention_author=False)
            return False
        return True

    @commands.command(name="setlog")
    async def setlog(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        await database.set_setting(ctx.guild.id, "modlog_channel", channel.id)
        await ctx.reply(f"🩵 Moderation and action logs will go to {channel.mention}.", mention_author=False)

    @commands.command(name="logchannel")
    async def logchannel(self, ctx, category: str, destination: str):
        """Set a log destination, e.g. ?logchannel ban #ban-logs; use off to clear it."""
        category = category.lower()
        if category not in LOG_TYPES:
            return await ctx.reply("Log types: `ban`, `warn`, `timeout`, `join`, `leave`, `invite`, `server`, `moderation`.", mention_author=False)
        key = f"log_channel_{category}"
        if destination.lower() in {"off", "none", "disable"}:
            await database.set_setting(ctx.guild.id, key, None)
            return await ctx.reply(f"{LOG_TITLES[category]} cleared. Any legacy log channel may still receive those events.", mention_author=False)
        try:
            channel = await commands.TextChannelConverter().convert(ctx, destination)
        except commands.BadArgument:
            return await ctx.reply("Mention a text channel or provide its channel ID, e.g. `?logchannel ban #ban-logs`.", mention_author=False)
        await database.set_setting(ctx.guild.id, key, channel.id)
        await ctx.reply(f"✅ {LOG_TITLES[category]} will go to {channel.mention}.", mention_author=False)

    @commands.command(name="logchannels")
    async def logchannels(self, ctx):
        rows = []
        for category in LOG_TYPES:
            channel_id = await database.get_setting(ctx.guild.id, f"log_channel_{category}")
            if not channel_id:
                legacy_key = "modlog_channel" if category in {"ban", "warn", "timeout", "moderation"} else "actionlog_channel"
                channel_id = await database.get_setting(ctx.guild.id, legacy_key)
            channel = ctx.guild.get_channel(channel_id) if channel_id else None
            rows.append(f"**{LOG_TITLES[category]}:** {channel.mention if channel else 'Not set'}")
        embed = discord.Embed(title="📋 Time Bot log channels", description="\n".join(rows), color=BLUE)
        embed.set_footer(text="Set one with ?logchannel <type> #channel")
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="config")
    async def config(self, ctx):
        fields = []
        for key, title in (("modlog_channel", "Mod logs"), ("welcome_channel", "Welcome"), ("autorole_id", "Autorole"), ("starboard_channel", "Starboard")):
            value = await database.get_setting(ctx.guild.id, key)
            fields.append(f"**{title}:** {f'<#{value}>' if key.endswith('channel') and value else f'<@&{value}>' if value else 'Not set'}")
        await ctx.reply(embed=discord.Embed(title="⚙️ Server configuration", description="\n".join(fields), color=BLUE), mention_author=False)

    @commands.command(name="ban")
    async def ban(self, ctx, member: discord.Member, *, reason="No reason provided"):
        if not await self.target_ok(ctx, member): return
        try:
            await member.send(f"You were banned from **{ctx.guild.name}**. Reason: {reason[:500]}")
        except discord.HTTPException:
            pass
        await member.ban(reason=f"{ctx.author}: {reason}", delete_message_seconds=0)
        case = await self.log_case(ctx, member.id, "ban", reason)
        await ctx.reply(f"🔨 Banned **{member}**. Case `#{case}`.", mention_author=False)

    @commands.command(name="unban")
    async def unban(self, ctx, user_id: int, *, reason="No reason provided"):
        user = await self.bot.fetch_user(user_id)
        await ctx.guild.unban(user, reason=f"{ctx.author}: {reason}")
        case = await self.log_case(ctx, user_id, "unban", reason)
        await ctx.reply(f"✅ Unbanned **{user}**. Case `#{case}`.", mention_author=False)

    @commands.command(name="kick")
    async def kick(self, ctx, member: discord.Member, *, reason="No reason provided"):
        if not await self.target_ok(ctx, member): return
        try:
            await member.send(f"You were kicked from **{ctx.guild.name}**. Reason: {reason[:500]}")
        except discord.HTTPException:
            pass
        await member.kick(reason=f"{ctx.author}: {reason}")
        case = await self.log_case(ctx, member.id, "kick", reason)
        await ctx.reply(f"👢 Kicked **{member}**. Case `#{case}`.", mention_author=False)

    @commands.command(name="timeout", aliases=["mute"])
    async def timeout(self, ctx, member: discord.Member, duration: str, *, reason="No reason provided"):
        if not await self.target_ok(ctx, member): return
        seconds = duration_seconds(duration)
        if not seconds or seconds > 28 * 86400:
            return await ctx.reply("Use `10m`, `2h`, or `3d` (maximum 28 days).", mention_author=False)
        until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        await member.timeout(until, reason=f"{ctx.author}: {reason}")
        case = await self.log_case(ctx, member.id, "timeout", reason, until.isoformat())
        await ctx.reply(f"🔇 Timed out **{member}** for `{duration}`. Case `#{case}`.", mention_author=False)

    @commands.command(name="untimeout", aliases=["unmute"])
    async def untimeout(self, ctx, member: discord.Member, *, reason="No reason provided"):
        if not await self.target_ok(ctx, member): return
        await member.timeout(None, reason=f"{ctx.author}: {reason}")
        case = await self.log_case(ctx, member.id, "untimeout", reason)
        await ctx.reply(f"🔊 Timeout removed for **{member}**. Case `#{case}`.", mention_author=False)

    @commands.command(name="warn")
    async def warn(self, ctx, member: discord.Member, *, reason="No reason provided"):
        if not await self.target_ok(ctx, member): return
        case = await self.log_case(ctx, member.id, "warn", reason)
        try:
            await member.send(f"You were warned in **{ctx.guild.name}**. Reason: {reason[:500]}")
        except discord.HTTPException:
            pass
        await ctx.reply(f"⚠️ Warned **{member}**. Case `#{case}`.", mention_author=False)

    async def list_cases(self, ctx, member, actions=None):
        query = "SELECT id, action, reason, created_at FROM cases WHERE guild_id=? AND user_id=?"
        params = [ctx.guild.id, member.id]
        if actions:
            query += " AND action IN (" + ",".join("?" for _ in actions) + ")"
            params.extend(actions)
        query += " ORDER BY id DESC LIMIT 15"
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute(query, params) as cur:
                rows = await cur.fetchall()
        return rows

    @commands.command(name="warnings")
    async def warnings(self, ctx, member: discord.Member):
        rows = await self.list_cases(ctx, member, ["warn"])
        text = "\n".join(f"`#{i}` • {reason[:140]}" for i, _, reason, _ in rows) or "No warnings recorded."
        await ctx.reply(embed=discord.Embed(title=f"⚠️ Warnings • {member}", description=text, color=BLUE), mention_author=False)

    @commands.command(name="clearwarnings", aliases=["clearnotes"])
    async def clearwarnings(self, ctx, member: discord.Member):
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute("DELETE FROM cases WHERE guild_id=? AND user_id=? AND action IN ('warn','note')", (ctx.guild.id, member.id))
            await db.commit()
        await ctx.reply(f"🧹 Cleared stored warnings and notes for {member.mention}.", mention_author=False)

    @commands.command(name="note")
    async def note(self, ctx, member: discord.Member, *, text):
        case = await self.log_case(ctx, member.id, "note", text)
        await ctx.reply(f"📝 Note saved for **{member}** as case `#{case}`.", mention_author=False)

    @commands.command(name="notes")
    async def notes(self, ctx, member: discord.Member):
        rows = await self.list_cases(ctx, member, ["note"])
        text = "\n".join(f"`#{i}` • {reason[:140]}" for i, _, reason, _ in rows) or "No notes saved."
        await ctx.reply(embed=discord.Embed(title=f"📝 Notes • {member}", description=text, color=BLUE), mention_author=False)

    @commands.command(name="modlogs", aliases=["modlog"])
    async def modlogs(self, ctx, member: discord.Member):
        rows = await self.list_cases(ctx, member)
        text = "\n".join(f"`#{i}` **{action}** • {reason[:100]}" for i, action, reason, _ in rows) or "No moderation history."
        await ctx.reply(embed=discord.Embed(title=f"🛡️ Cases • {member}", description=text, color=BLUE), mention_author=False)

    @commands.command(name="case")
    async def case(self, ctx, case_id: int):
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT user_id,moderator_id,action,reason,created_at FROM cases WHERE id=? AND guild_id=?", (case_id, ctx.guild.id)) as cur:
                row = await cur.fetchone()
        if not row:
            return await ctx.reply("I couldn't find that case.", mention_author=False)
        uid, modid, action, reason, stamp = row
        embed = discord.Embed(title=f"🛡️ Case #{case_id} • {action.title()}", description=reason, color=BLUE)
        embed.add_field(name="Member", value=f"<@{uid}> (`{uid}`)", inline=True)
        embed.add_field(name="Moderator", value=f"<@{modid}>", inline=True)
        embed.timestamp = datetime.fromisoformat(stamp)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="purge", aliases=["clean"])
    async def purge(self, ctx, amount: int):
        if not 1 <= amount <= 100:
            return await ctx.reply("Choose between 1 and 100 messages.", mention_author=False)
        deleted = await ctx.channel.purge(limit=amount + 1)
        note = await ctx.send(f"🧹 Deleted **{max(0, len(deleted)-1)}** messages.")
        await note.delete(delay=5)

    @commands.command(name="softban")
    async def softban(self, ctx, member: discord.Member, *, reason="No reason provided"):
        if not await self.target_ok(ctx, member): return
        uid = member.id
        await member.ban(reason=f"Softban by {ctx.author}: {reason}", delete_message_seconds=86400)
        await ctx.guild.unban(discord.Object(id=uid), reason="BlueGuard softban complete")
        case = await self.log_case(ctx, uid, "softban", reason)
        await ctx.reply(f"🧹 Softbanned **{member}**. Case `#{case}`.", mention_author=False)

    @commands.command(name="lock")
    async def lock(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Locked by {ctx.author}")
        await ctx.reply(f"🔒 Locked {channel.mention}.", mention_author=False)

    @commands.command(name="unlock")
    async def unlock(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Unlocked by {ctx.author}")
        await ctx.reply(f"🔓 Unlocked {channel.mention}.", mention_author=False)

    @commands.command(name="slowmode")
    async def slowmode(self, ctx, seconds: int):
        if not 0 <= seconds <= 21600:
            return await ctx.reply("Slowmode must be between 0 and 21,600 seconds.", mention_author=False)
        await ctx.channel.edit(slowmode_delay=seconds, reason=f"Changed by {ctx.author}")
        await ctx.reply(f"🐢 Slowmode set to **{seconds}s**.", mention_author=False)

    @commands.command(name="deafen")
    async def deafen(self, ctx, member: discord.Member, *, reason="No reason provided"):
        if not member.voice:
            return await ctx.reply("That member is not in voice.", mention_author=False)
        await member.edit(deafen=True, reason=f"{ctx.author}: {reason}")
        await self.log_case(ctx, member.id, "deafen", reason)
        await ctx.reply(f"🔇 Deafened {member.mention}.", mention_author=False)

    @commands.command(name="undeafen")
    async def undeafen(self, ctx, member: discord.Member):
        if not member.voice:
            return await ctx.reply("That member is not in voice.", mention_author=False)
        await member.edit(deafen=False, reason=f"Undeafened by {ctx.author}")
        await ctx.reply(f"🔊 Undeafened {member.mention}.", mention_author=False)

    @commands.command(name="role")
    async def role(self, ctx, member: discord.Member, role: discord.Role):
        if access_control.is_access_role(ctx.guild.id, role.id) and not access_control.can_manage_access_roles(ctx.guild.id, ctx.author.id):
            return await ctx.reply("Only the configured Time Bot role manager can assign or remove access roles.", mention_author=False)
        if role >= ctx.guild.me.top_role or (ctx.author.id != ctx.guild.owner_id and role >= ctx.author.top_role):
            return await ctx.reply("I can't change that role because of role hierarchy.", mention_author=False)
        if role in member.roles:
            await member.remove_roles(role, reason=f"Role command by {ctx.author}")
            action = "Removed"
        else:
            await member.add_roles(role, reason=f"Role command by {ctx.author}")
            action = "Added"
        await ctx.reply(f"✅ {action} {role.mention} {'from' if action == 'Removed' else 'to'} {member.mention}.", mention_author=False)

    async def change_role(self, ctx, member, role, adding):
        if access_control.is_access_role(ctx.guild.id, role.id) and not access_control.can_manage_access_roles(ctx.guild.id, ctx.author.id):
            return await ctx.reply("Only the configured Time Bot role manager can assign or remove access roles.", mention_author=False)
        if role.is_default() or role.managed or role >= ctx.guild.me.top_role:
            return await ctx.reply("I can't assign that role. Check that it isn't managed and move Time Bot's role above it.", mention_author=False)
        if ctx.author.id != ctx.guild.owner_id and role >= ctx.author.top_role:
            return await ctx.reply("Your highest role must be above the role you want to edit.", mention_author=False)
        try:
            if adding:
                if role in member.roles:
                    return await ctx.reply(f"{member.mention} already has {role.mention}.", mention_author=False)
                await member.add_roles(role, reason=f"Time Bot command by {ctx.author}")
                result = "Added"
            else:
                if role not in member.roles:
                    return await ctx.reply(f"{member.mention} doesn't have {role.mention}.", mention_author=False)
                await member.remove_roles(role, reason=f"Time Bot command by {ctx.author}")
                result = "Removed"
        except discord.Forbidden:
            return await ctx.reply("Time Bot needs Manage Roles, and its top role must be above the target role.", mention_author=False)
        await ctx.reply(f"🎭 {result} {role.mention} {'to' if adding else 'from'} {member.mention}.", mention_author=False)

    @commands.command(name="addrole")
    async def addrole(self, ctx, member: discord.Member, role: discord.Role):
        await self.change_role(ctx, member, role, True)

    @commands.command(name="removerole")
    async def removerole(self, ctx, member: discord.Member, role: discord.Role):
        await self.change_role(ctx, member, role, False)

    @commands.command(name="nick", aliases=["setnick"])
    async def nick(self, ctx, member: discord.Member, *, nickname=None):
        if not await self.target_ok(ctx, member): return
        await member.edit(nick=nickname, reason=f"Nickname changed by {ctx.author}")
        await ctx.reply(f"✅ Updated nickname for {member.mention}.", mention_author=False)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        embed = discord.Embed(title="📥 Member joined", description=f"Member: {member.mention}\nUser ID: `{member.id}`\nAccount created: {discord.utils.format_dt(member.created_at, style='F')}", color=BLUE, timestamp=datetime.now(timezone.utc))
        embed.set_thumbnail(url=member.display_avatar.url)
        await send_log(member.guild, "join", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        embed = discord.Embed(title="📤 Member left", description=f"Member: {discord.utils.escape_markdown(str(member))}\nUser ID: `{member.id}`", color=BLUE, timestamp=datetime.now(timezone.utc))
        await send_log(member.guild, "leave", embed)
        await asyncio.sleep(2)
        if await self._recent_bot_case(member.guild.id, member.id, ("kick",)):
            return
        moderator, reason = await self._audit_actor(member.guild, discord.AuditLogAction.kick, member.id)
        if moderator:
            embed = discord.Embed(title="👢 Member kicked", description=f"Member: {member} (`{member.id}`)\nModerator: {moderator.mention}\nReason: {reason}", color=BLUE, timestamp=datetime.now(timezone.utc))
            await send_log(member.guild, "moderation", embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        await asyncio.sleep(2)
        if await self._recent_bot_case(guild.id, user.id, ("ban", "softban", "autoban")):
            return
        moderator, reason = await self._audit_actor(guild, discord.AuditLogAction.ban, user.id)
        embed = discord.Embed(title="🔨 Member banned", description=f"Member: {user} (`{user.id}`)\nModerator: {moderator.mention if moderator else 'Unknown'}\nReason: {reason}", color=BLUE, timestamp=datetime.now(timezone.utc))
        await send_log(guild, "ban", embed, include_moderation=True)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        await asyncio.sleep(2)
        if await self._recent_bot_case(guild.id, user.id, ("unban",)):
            return
        moderator, reason = await self._audit_actor(guild, discord.AuditLogAction.unban, user.id)
        embed = discord.Embed(title="🔓 Member unbanned", description=f"Member: {user} (`{user.id}`)\nModerator: {moderator.mention if moderator else 'Unknown'}\nReason: {reason}", color=BLUE, timestamp=datetime.now(timezone.utc))
        await send_log(guild, "ban", embed, include_moderation=True)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.timed_out_until == after.timed_out_until:
            return
        action = "timeout" if after.is_timed_out() else "untimeout"
        await asyncio.sleep(2)
        if await self._recent_bot_case(after.guild.id, after.id, (action,)):
            return
        moderator, reason = await self._audit_actor(after.guild, discord.AuditLogAction.member_update, after.id)
        until = f"\nExpires: {discord.utils.format_dt(after.timed_out_until, style='R')}" if after.timed_out_until else ""
        embed = discord.Embed(title="🔇 Member timed out" if action == "timeout" else "🔊 Timeout removed", description=f"Member: {after.mention} (`{after.id}`)\nModerator: {moderator.mention if moderator else 'Unknown'}\nReason: {reason}{until}", color=BLUE, timestamp=datetime.now(timezone.utc))
        await send_log(after.guild, "timeout", embed, include_moderation=True)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot:
            return
        excerpt = message.content[:900] or "(no text content)"
        embed = discord.Embed(title="🗑️ Message deleted", description=f"**Author:** {message.author.mention}\n**Channel:** {message.channel.mention}\n**Content:** {excerpt}", color=BLUE, timestamp=datetime.now(timezone.utc))
        await send_log(message.guild, "server", embed)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
