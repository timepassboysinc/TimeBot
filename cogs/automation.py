import asyncio
import re
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

import access_control
import database
from logging_utils import send_log

BLUE = 0x176BFF
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class Automation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.scheduler.start()

    def cog_unload(self):
        self.scheduler.cancel()

    @commands.command(name="setactionlog")
    async def setactionlog(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        await database.set_setting(ctx.guild.id, "actionlog_channel", channel.id)
        await ctx.reply(f"🩵 Server event logs will go to {channel.mention}.", mention_author=False)

    @commands.command(name="setwelcome")
    async def setwelcome(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        await database.set_setting(ctx.guild.id, "welcome_channel", channel.id)
        await ctx.reply(f"👋 Welcome messages will go to {channel.mention}.", mention_author=False)

    @commands.command(name="welcometext")
    async def welcometext(self, ctx, *, text):
        if len(text) > 1600:
            return await ctx.reply("Welcome text must be 1,600 characters or fewer.", mention_author=False)
        await database.set_setting(ctx.guild.id, "welcome_text", text)
        await ctx.reply("✅ Welcome text saved. Use `{mention}` for the member and `{server}` for the server name.", mention_author=False)

    @commands.command(name="setleave", aliases=["setleavechannel"])
    async def setleave(self, ctx, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        await database.set_setting(ctx.guild.id, "leave_channel", channel.id)
        await ctx.reply(f"👋 Leave notices will go to {channel.mention}.", mention_author=False)

    @commands.command(name="leavetext")
    async def leavetext(self, ctx, *, text):
        if len(text) > 1600:
            return await ctx.reply("Leave text must be 1,600 characters or fewer.", mention_author=False)
        await database.set_setting(ctx.guild.id, "leave_text", text)
        await ctx.reply("✅ Leave text saved. You can use `{username}` and `{server}`.", mention_author=False)

    @commands.command(name="setautorole")
    async def setautorole(self, ctx, role: discord.Role):
        if access_control.is_access_role(ctx.guild.id, role.id):
            return await ctx.reply("Access-control roles can't be assigned automatically to new members.", mention_author=False)
        if role >= ctx.guild.me.top_role:
            return await ctx.reply("Move Time Bot's role above that role first.", mention_author=False)
        await database.set_setting(ctx.guild.id, "autorole_id", role.id)
        await ctx.reply(f"✅ New members will receive {role.mention}.", mention_author=False)

    @commands.command(name="autorole")
    async def autorole_toggle(self, ctx, state: str):
        if state.lower() not in {"on", "off"}:
            return await ctx.reply("Use `?autorole on` or `?autorole off`.", mention_author=False)
        await database.set_setting(ctx.guild.id, "autorole_enabled", state.lower() == "on")
        await ctx.reply(f"Autorole is now **{state.lower()}**.", mention_author=False)

    @commands.command(name="automod")
    async def automod(self, ctx, feature: str = None, action: str = None, *, value: str = None):
        config = await database.get_setting(ctx.guild.id, "automod", {"enabled": True, "words": [], "links": False, "caps": False})
        if not feature:
            return await ctx.reply("Automod controls: `?automod word add <text>`, `?automod word remove <text>`, `?automod links on/off`, `?automod caps on/off`.", mention_author=False)
        feature = feature.lower()
        if feature == "word" and action and value:
            value = value.strip().lower()
            if action.lower() == "add" and value not in config["words"]:
                config["words"].append(value)
            elif action.lower() == "remove":
                config["words"] = [word for word in config["words"] if word != value]
            else:
                return await ctx.reply("Use `?automod word add/remove <text>`.", mention_author=False)
        elif feature in {"links", "caps"} and action and action.lower() in {"on", "off"}:
            config[feature] = action.lower() == "on"
        else:
            return await ctx.reply("Use `?automod word add/remove <text>`, `?automod links on/off`, or `?automod caps on/off`.", mention_author=False)
        await database.set_setting(ctx.guild.id, "automod", config)
        await ctx.reply(f"🛡️ Automod updated: **{feature}**.", mention_author=False)

    @commands.command(name="autodelete")
    async def autodelete(self, ctx, feature: str, state: str):
        if feature.lower() != "links" or state.lower() not in {"on", "off"}:
            return await ctx.reply("Use `?autodelete links on/off`.", mention_author=False)
        await database.set_setting(ctx.guild.id, "autodelete_links", state.lower() == "on")
        await ctx.reply(f"Link auto-delete is **{state.lower()}**.", mention_author=False)

    @commands.command(name="autoresponse")
    async def autoresponse(self, ctx, action: str = None, *, payload: str = None):
        responses = await database.get_setting(ctx.guild.id, "autoresponses", {})
        if action == "add" and payload and "|" in payload:
            trigger, reply = (part.strip() for part in payload.split("|", 1))
            if not trigger or not reply:
                return await ctx.reply("Provide a trigger and response: `?autoresponse add hello | Hi!`.", mention_author=False)
            responses[trigger.lower()] = reply[:1800]
        elif action == "remove" and payload:
            responses.pop(payload.strip().lower(), None)
        else:
            listing = "\n".join(f"• `{key}` → {value[:120]}" for key, value in responses.items()) or "No autoresponses configured."
            return await ctx.reply(f"**Autoresponses**\n{listing}\n\nAdd with `?autoresponse add trigger | reply`.", mention_author=False)
        await database.set_setting(ctx.guild.id, "autoresponses", responses)
        await ctx.reply("✅ Autoresponse saved.", mention_author=False)

    @commands.command(name="custom")
    async def custom(self, ctx, action: str = "list", *, payload: str = None):
        custom = await database.get_setting(ctx.guild.id, "custom_commands", {})
        if action == "add" and payload and "|" in payload:
            trigger, response = (part.strip() for part in payload.split("|", 1))
            trigger = trigger.lower().removeprefix("?")
            if not trigger or not response or len(trigger) > 32:
                return await ctx.reply("Use `?custom add command | response` (command max 32 characters).", mention_author=False)
            custom[trigger] = response[:1800]
        elif action == "remove" and payload:
            custom.pop(payload.lower().removeprefix("?"), None)
        elif action == "list":
            listing = ", ".join(f"`?{key}`" for key in custom) or "none"
            return await ctx.reply(f"**Custom commands:** {listing}", mention_author=False)
        else:
            return await ctx.reply("Use `?custom add command | response`, `?custom remove command`, or `?custom list`.", mention_author=False)
        await database.set_setting(ctx.guild.id, "custom_commands", custom)
        await ctx.reply("✅ Custom command saved.", mention_author=False)

    @commands.command(name="announce")
    async def announce(self, ctx, channel: discord.TextChannel, *, text):
        embed = discord.Embed(title="📣 Announcement", description=text[:4000], color=BLUE, timestamp=datetime.now(timezone.utc))
        embed.set_footer(text=f"Posted by {ctx.author.display_name}")
        await channel.send(embed=embed)
        await ctx.reply(f"✅ Announcement posted in {channel.mention}.", mention_author=False)

    @commands.command(name="automessage")
    async def automessage(self, ctx, channel: discord.TextChannel, interval: str, *, text):
        seconds = self.parse_interval(interval)
        if not seconds or seconds < 3600:
            return await ctx.reply("Use an interval of at least 1 hour, such as `6h` or `1d`.", mention_author=False)
        schedules = await database.get_setting(ctx.guild.id, "automessages", [])
        schedules.append({"channel_id": channel.id, "interval": seconds, "text": text[:1800], "next_at": time.time() + seconds})
        await database.set_setting(ctx.guild.id, "automessages", schedules)
        await ctx.reply(f"✅ Scheduled a message in {channel.mention} every `{interval}`.", mention_author=False)

    @commands.command(name="autopurge")
    async def autopurge(self, ctx, channel: discord.TextChannel, age: str):
        seconds = self.parse_interval(age)
        if not seconds or seconds < 86400:
            return await ctx.reply("Use a minimum age of 1 day, such as `7d`.", mention_author=False)
        rules = await database.get_setting(ctx.guild.id, "autopurge", {})
        rules[str(channel.id)] = seconds
        await database.set_setting(ctx.guild.id, "autopurge", rules)
        await ctx.reply(f"✅ Auto-purge enabled in {channel.mention} for messages older than `{age}`. It checks hourly.", mention_author=False)

    @commands.command(name="autoban")
    async def autoban(self, ctx, setting: str = None, days: int = None):
        if setting != "age" or days is None or not 0 <= days <= 365:
            return await ctx.reply("Use `?autoban age <days>` (0 disables it).", mention_author=False)
        await database.set_setting(ctx.guild.id, "autoban_account_age_days", days)
        await ctx.reply(f"🛡️ Auto-ban for accounts younger than **{days} days** is {'off' if days == 0 else 'on'}.", mention_author=False)

    @staticmethod
    def parse_interval(raw):
        match = re.fullmatch(r"(\d+)\s*(m|h|d)", raw.lower())
        if not match:
            return None
        number, unit = int(match.group(1)), match.group(2)
        return number * {"m": 60, "h": 3600, "d": 86400}[unit]

    @tasks.loop(seconds=60)
    async def scheduler(self):
        now = time.time()
        async with __import__("aiosqlite").connect(database.DB_PATH) as db:
            async with db.execute("SELECT guild_id,value FROM settings WHERE key='automessages'") as cur:
                rows = await cur.fetchall()
        for guild_id, raw in rows:
            try:
                schedules = __import__("json").loads(raw)
            except (ValueError, TypeError):
                continue
            changed = False
            for entry in schedules:
                if entry.get("next_at", now + 1) > now:
                    continue
                channel = self.bot.get_channel(int(entry["channel_id"]))
                if channel:
                    try:
                        await channel.send(entry["text"])
                    except discord.HTTPException:
                        pass
                entry["next_at"] = now + int(entry["interval"])
                changed = True
            if changed:
                await database.set_setting(int(guild_id), "automessages", schedules)
        if int(now // 3600) != self._last_purge_hour:
            self._last_purge_hour = int(now // 3600)
            await self.run_autopurge(now)

    async def run_autopurge(self, now):
        async with __import__("aiosqlite").connect(database.DB_PATH) as db:
            async with db.execute("SELECT guild_id,value FROM settings WHERE key='autopurge'") as cur:
                rows = await cur.fetchall()
        for guild_id, raw in rows:
            try:
                rules = __import__("json").loads(raw)
            except (ValueError, TypeError):
                continue
            guild = self.bot.get_guild(int(guild_id))
            if not guild:
                continue
            for channel_id, age in rules.items():
                channel = guild.get_channel(int(channel_id))
                if not channel:
                    continue
                try:
                    await channel.purge(limit=100, before=datetime.fromtimestamp(now - int(age), timezone.utc), bulk=True)
                except (discord.Forbidden, discord.HTTPException):
                    pass

    @property
    def _last_purge_hour(self):
        return getattr(self, "_purge_hour", -1)

    @_last_purge_hour.setter
    def _last_purge_hour(self, value):
        self._purge_hour = value

    @scheduler.before_loop
    async def before_scheduler(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        role_id = await database.get_setting(member.guild.id, "autorole_id")
        enabled = await database.get_setting(member.guild.id, "autorole_enabled", True)
        role = member.guild.get_role(role_id) if role_id and enabled else None
        if role and not access_control.is_access_role(member.guild.id, role.id) and role < member.guild.me.top_role:
            try:
                await member.add_roles(role, reason="Time Bot autorole")
            except discord.HTTPException:
                pass
        channel_id = await database.get_setting(member.guild.id, "welcome_channel")
        channel = member.guild.get_channel(channel_id) if channel_id else None
        if channel:
            template = await database.get_setting(member.guild.id, "welcome_text", "Welcome {mention} to **{server}**!")
            await channel.send(template.replace("{mention}", member.mention).replace("{server}", member.guild.name))
        age_days = await database.get_setting(member.guild.id, "autoban_account_age_days", 0)
        if age_days and (datetime.now(timezone.utc) - member.created_at).days < age_days:
            try:
                await member.ban(reason=f"Time Bot autoban: account younger than {age_days} days")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        channel_id = await database.get_setting(member.guild.id, "leave_channel")
        channel = member.guild.get_channel(channel_id) if channel_id else None
        if not channel:
            return
        template = await database.get_setting(member.guild.id, "leave_text", "**{username}** left **{server}**.")
        text = template.replace("{username}", discord.utils.escape_markdown(str(member))).replace("{server}", discord.utils.escape_markdown(member.guild.name))
        try:
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return
        if message.content.startswith("?"):
            custom = await database.get_setting(message.guild.id, "custom_commands", {})
            trigger = message.content[1:].strip().split(maxsplit=1)[0].lower() if message.content[1:].strip() else ""
            response = custom.get(trigger)
            if response:
                await message.channel.send(response[:1900].replace("{user}", message.author.mention), allowed_mentions=discord.AllowedMentions.none())
            return
        config = await database.get_setting(message.guild.id, "automod", {"enabled": True, "words": [], "links": False, "caps": False})
        if message.author.guild_permissions.manage_messages:
            return
        content = message.content.lower()
        reason = None
        for word in config.get("words", []):
            if word and word in content:
                reason = "blocked word"
                break
        if not reason and config.get("links") and URL_RE.search(message.content):
            reason = "unapproved link"
        if not reason and config.get("caps") and len(message.content) >= 12:
            letters = [char for char in message.content if char.isalpha()]
            if len(letters) >= 10 and sum(char.isupper() for char in letters) / len(letters) > 0.8:
                reason = "excessive caps"
        if reason:
            try:
                await message.delete()
                notice = await message.channel.send(f"🛡️ {message.author.mention}, your message was removed by AutoMod ({reason}).")
                await notice.delete(delay=6)
            except discord.HTTPException:
                pass
            return
        if await database.get_setting(message.guild.id, "autodelete_links", False) and URL_RE.search(message.content):
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            return
        responses = await database.get_setting(message.guild.id, "autoresponses", {})
        for trigger, reply in responses.items():
            if trigger in content:
                await message.channel.send(reply[:1900], allowed_mentions=discord.AllowedMentions.none())
                break

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not after.guild or after.author.bot or before.content == after.content:
            return
        embed = discord.Embed(title="✏️ Message edited", description=f"**Author:** {after.author.mention}\n**Channel:** {after.channel.mention}\n[Jump to message]({after.jump_url})", color=BLUE, timestamp=datetime.now(timezone.utc))
        embed.add_field(name="Before", value=before.content[:900] or "(empty)", inline=False)
        embed.add_field(name="After", value=after.content[:900] or "(empty)", inline=False)
        await send_log(after.guild, "server", embed)


async def setup(bot):
    await bot.add_cog(Automation(bot))
