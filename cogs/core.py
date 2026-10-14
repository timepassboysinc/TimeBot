import asyncio
import re
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

import database

BLUE = 0x176BFF
PALE_BLUE = 0x9BE7FF

HELP_CATEGORIES = ("Start here", "Utilities", "AI", "Moderation", "Automation", "Community", "Invites", "Feeds")


def help_embed(page="Start here", bot=None):
    embed = discord.Embed(
        title="🧊 TIME BOT  /  COMMAND CENTER",
        description=("╭────────────────────────────╮\n"
                     f"│  **TIME BOT**  •  `PREFIX {commands_prefix()}`\n"
                     "╰────────────────────────────╯\n"
                     "Choose a category below. Each page lists commands that are currently loaded."),
        color=BLUE,
        timestamp=datetime.now(timezone.utc),
    )
    if page == "Start here":
        embed.add_field(name="🌌 QUICK START", value="`?help`  •  Browse the command deck\n`?help serverinfo`  •  Command details\n`?ping`  •  Check response time", inline=False)
    elif bot is not None:
        category_map = {"Utilities": {"Core"}, "AI": {"AI"}, "Moderation": {"Moderation"}, "Automation": {"Automation"}, "Community": {"Community"}, "Invites": {"InviteTracking"}, "Feeds": {"Feeds"}}
        names = category_map.get(page, set())
        matching = sorted((command for command in bot.commands
                           if not command.hidden and command.cog and command.cog.qualified_name in names),
                          key=lambda command: command.name)
        rows = []
        for command in matching:
            usage = f" {command.signature}" if command.signature else ""
            summary = command.short_doc or "Server utility"
            rows.append(f"`?{command.name}{usage}` — {summary[:95]}")
        text = "\n".join(rows) or "No commands in this section are loaded."
        # Discord embed fields have a 1,024-character value cap.
        for part_index in range(0, len(text), 1000):
            embed.add_field(name=f"🩵 {page}" if part_index == 0 else f"🩵 {page} • continued", value=text[part_index:part_index + 1000], inline=False)
    embed.set_footer(text="TIME BOT  •  Deep blue tools, bright blue details  •  ?help <command>")
    return embed


def commands_prefix():
    return "?"


class HelpSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=page, value=page, emoji=emoji)
                   for page, emoji in zip(HELP_CATEGORIES, ("🔹", "🧰", "✨", "🛡️", "⚙️", "💬", "📨", "📡"))]
        super().__init__(placeholder="Browse command categories…", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=help_embed(self.values[0], interaction.client), view=self.view)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(HelpSelect())


def parse_duration(raw):
    match = re.fullmatch(r"\s*(\d+)\s*(s|sec|m|min|h|hr|d|day|w|week)s?\s*", raw.lower())
    if not match:
        return None
    n, unit = int(match.group(1)), match.group(2)
    scale = 1 if unit in {"s", "sec"} else 60 if unit in {"m", "min"} else 3600 if unit in {"h", "hr"} else 86400 if unit in {"d", "day"} else 604800
    return n * scale


class Core(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    @commands.command(name="help")
    async def help_command(self, ctx, *, command_name=None):
        if command_name:
            command = self.bot.get_command(command_name.lower())
            if not command:
                return await ctx.reply(f"I couldn't find `?{command_name}`. Try `?help`.", mention_author=False)
            help_text = command.help or command.short_doc or "No extra details are set."
            usage = f"?{command.qualified_name} {command.signature}".strip()
            embed = discord.Embed(title=f"🧊 TIME BOT  /  ?{command.qualified_name}", description=help_text, color=BLUE)
            embed.add_field(name="Usage", value=f"`{usage}`", inline=False)
            embed.set_footer(text="TIME BOT  •  Command details")
            return await ctx.reply(embed=embed, mention_author=False)
        await ctx.reply(embed=help_embed(bot=self.bot), view=HelpView(), mention_author=False)

    @commands.command(name="ping")
    async def ping(self, ctx):
        await ctx.reply(embed=discord.Embed(description=f"🏓 **Pong!** `{round(self.bot.latency * 1000)} ms`", color=BLUE), mention_author=False)

    @commands.command(name="about", aliases=["info", "uptime"])
    async def about(self, ctx):
        delta = datetime.now(timezone.utc) - self.bot.start_time
        embed = discord.Embed(title="🧊 Time Bot", description="A vibrant command deck for your server.", color=BLUE)
        embed.add_field(name="Uptime", value=str(delta).split(".")[0], inline=True)
        embed.add_field(name="Servers", value=f"{len(self.bot.guilds):,}", inline=True)
        embed.add_field(name="Latency", value=f"{round(self.bot.latency * 1000)} ms", inline=True)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="serverinfo")
    async def serverinfo(self, ctx):
        g = ctx.guild
        embed = discord.Embed(title=f"🌌 {g.name}  /  SERVER PROFILE", color=BLUE, timestamp=g.created_at)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        embed.add_field(name="Members", value=str(g.member_count), inline=True)
        embed.add_field(name="Owner", value=f"<@{g.owner_id}>", inline=True)
        embed.add_field(name="Channels", value=f"{len(g.text_channels)} text • {len(g.voice_channels)} voice", inline=True)
        embed.add_field(name="Boosts", value=f"Level {g.premium_tier} • {g.premium_subscription_count or 0} boosts", inline=True)
        embed.add_field(name="Roles", value=f"{len(g.roles):,}", inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(g.created_at, style="D"), inline=False)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="serverstats", aliases=["guildstats"])
    async def serverstats(self, ctx):
        guild = ctx.guild
        counts = {
            "Text channels": len(guild.text_channels),
            "Voice channels": len(guild.voice_channels),
            "Categories": len(guild.categories),
            "Roles": len(guild.roles),
            "Custom emojis": len(guild.emojis),
            "Stickers": len(guild.stickers),
        }
        embed = discord.Embed(title=f"📊 {guild.name}  /  LIVE SERVER STATS", color=BLUE)
        embed.description = "\n".join(f"**{label}:** `{count:,}`" for label, count in counts.items())
        embed.add_field(name="Members", value=f"👥 {guild.member_count:,}", inline=True)
        embed.add_field(name="Boosts", value=f"🚀 {guild.premium_subscription_count or 0}", inline=True)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.set_footer(text="TIME BOT  •  Updated live")
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="roles")
    async def roles_list(self, ctx):
        roles = [role for role in reversed(ctx.guild.roles) if role != ctx.guild.default_role]
        lines = [f"{role.mention} · `{len(role.members)} members`" for role in roles[:35]]
        embed = discord.Embed(title="🎭 ROLE DIRECTORY", description="\n".join(lines) or "No roles yet.", color=BLUE)
        if len(roles) > 35:
            embed.set_footer(text=f"Showing 35 of {len(roles)} roles")
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="roleinfo")
    async def roleinfo(self, ctx, role: discord.Role):
        embed = discord.Embed(title=f"🎭 ROLE PROFILE  /  {role.name}", color=role.color if role.color.value else BLUE)
        embed.add_field(name="ID", value=f"`{role.id}`", inline=True)
        embed.add_field(name="Members", value=f"`{len(role.members):,}`", inline=True)
        embed.add_field(name="Position", value=f"`{role.position}`", inline=True)
        embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No", inline=True)
        embed.add_field(name="Hoisted", value="Yes" if role.hoist else "No", inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(role.created_at, style="D"), inline=True)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="userinfo", aliases=["whois"])
    async def userinfo(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=f"🩵 {member}", color=BLUE, timestamp=member.created_at)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, style="R") if member.joined_at else "Unknown", inline=True)
        embed.add_field(name="Created", value=discord.utils.format_dt(member.created_at, style="R"), inline=True)
        embed.add_field(name="Roles", value=" ".join(role.mention for role in member.roles[1:])[:1000] or "None", inline=False)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="avatar")
    async def avatar(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        embed = discord.Embed(title=f"🩵 {member.display_name}'s avatar", color=BLUE)
        embed.set_image(url=member.display_avatar.url)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="membercount")
    async def membercount(self, ctx):
        await ctx.reply(f"🩵 **{ctx.guild.member_count:,}** members", mention_author=False)

    @commands.command(name="messagecount", aliases=["messages"])
    async def messagecount(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        async with __import__("aiosqlite").connect(database.DB_PATH) as db:
            async with db.execute("SELECT messages FROM activity WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id)) as cur:
                row = await cur.fetchone()
        count = row[0] if row else 0
        embed = discord.Embed(title="💬 MESSAGE ACTIVITY", description=f"{member.mention} has **{count:,}** messages counted since Time Bot started tracking.", color=BLUE)
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="accage", aliases=["accountage"])
    async def account_age(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        account_days = (datetime.now(timezone.utc) - member.created_at).days
        joined_days = (datetime.now(timezone.utc) - member.joined_at).days if member.joined_at else None
        embed = discord.Embed(title=f"🕰️ ACCOUNT PROFILE  /  {member.display_name}", color=BLUE)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Account created", value=f"{discord.utils.format_dt(member.created_at, style='F')}\n`{account_days:,} days ago`", inline=False)
        if member.joined_at:
            embed.add_field(name="Joined this server", value=f"{discord.utils.format_dt(member.joined_at, style='F')}\n`{joined_days:,} days ago`", inline=False)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="perms", aliases=["permissions"])
    async def permissions(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        granted = [name.replace("_", " ").title() for name, value in member.guild_permissions if value]
        embed = discord.Embed(title=f"🔐 SERVER ACCESS  /  {member.display_name}", color=BLUE)
        embed.description = "\n".join(f"🩵 {name}" for name in granted[:30]) or "No server permissions granted."
        if len(granted) > 30:
            embed.set_footer(text=f"Showing first 30 of {len(granted)} permissions")
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="afk")
    async def afk(self, ctx, *, reason="AFK"):
        afk = await database.get_setting(ctx.guild.id, "afk", {})
        afk[str(ctx.author.id)] = {"reason": reason[:180], "since": time.time()}
        await database.set_setting(ctx.guild.id, "afk", afk)
        await ctx.reply(f"💤 I'll mark you AFK: **{reason[:180]}**", mention_author=False)

    @commands.command(name="remindme")
    async def remindme(self, ctx, duration: str, *, text):
        seconds = parse_duration(duration)
        if not seconds or seconds < 30 or seconds > 365 * 86400:
            return await ctx.reply("Use a duration from 30 seconds to 1 year, such as `10m`, `6h`, or `2d`.", mention_author=False)
        async with __import__("aiosqlite").connect(database.DB_PATH) as db:
            await db.execute("INSERT INTO reminders(user_id,channel_id,guild_id,text,due_at) VALUES(?,?,?,?,?)",
                              (ctx.author.id, ctx.channel.id, ctx.guild.id if ctx.guild else None, text[:1000], time.time() + seconds))
            await db.commit()
        await ctx.reply(f"⏰ Reminder set for {discord.utils.format_dt(datetime.fromtimestamp(time.time() + seconds, timezone.utc), style='R')}.", mention_author=False)

    @tasks.loop(seconds=10)
    async def reminder_loop(self):
        async with __import__("aiosqlite").connect(database.DB_PATH) as db:
            db.row_factory = __import__("aiosqlite").Row
            async with db.execute("SELECT * FROM reminders WHERE due_at<=?", (time.time(),)) as cur:
                due = await cur.fetchall()
            if due:
                await db.executemany("DELETE FROM reminders WHERE id=?", [(row["id"],) for row in due])
                await db.commit()
        for reminder in due:
            user = self.bot.get_user(reminder["user_id"])
            try:
                if user:
                    await user.send(f"⏰ **Reminder:** {reminder['text']}")
                else:
                    channel = self.bot.get_channel(reminder["channel_id"])
                    if channel:
                        await channel.send(f"<@{reminder['user_id']}> ⏰ **Reminder:** {reminder['text']}")
            except discord.HTTPException:
                pass

    @reminder_loop.before_loop
    async def before_reminder_loop(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        afk = await database.get_setting(message.guild.id, "afk", {})
        record = afk.pop(str(message.author.id), None)
        if record:
            await database.set_setting(message.guild.id, "afk", afk)
            await message.reply("👋 Welcome back! I removed your AFK status.", mention_author=False)
        for target in message.mentions:
            info = afk.get(str(target.id))
            if info:
                await message.reply(f"💤 **{target.display_name} is AFK:** {info['reason']}", mention_author=False)


async def setup(bot):
    bot.start_time = datetime.now(timezone.utc)
    await bot.add_cog(Core(bot))
