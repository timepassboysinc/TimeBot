import asyncio
import io
import random
import time
from datetime import datetime, timedelta, timezone

import aiosqlite
import discord
from discord.ext import commands, tasks

import access_control
import database
from cogs.core import BLUE, parse_duration


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="bg_ticket_close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel) or not (channel.topic or "").startswith("TimeBotTicket|"):
            return await interaction.response.send_message("This isn't a Time Bot ticket.", ephemeral=True)
        try:
            owner_id = int(channel.topic.split("|", 1)[1])
        except ValueError:
            owner_id = 0
        if interaction.user.id != owner_id and not access_control.member_has_guild_permission(interaction.guild, interaction.user, "all"):
            return await interaction.response.send_message("Only the ticket owner or staff can close this ticket.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        transcript = []
        async for message in channel.history(limit=500, oldest_first=True):
            stamp = message.created_at.strftime("%Y-%m-%d %H:%M UTC")
            text = message.clean_content or "[attachment/embed]"
            transcript.append(f"[{stamp}] {message.author} ({message.author.id}): {text}")
        file = discord.File(io.BytesIO("\n".join(transcript).encode("utf-8")), filename=f"{channel.name}-transcript.txt")
        log_id = await database.get_setting(channel.guild.id, "ticket_log_channel")
        log = channel.guild.get_channel(log_id) if log_id else None
        if log:
            await log.send(content=f"Transcript for **{channel.name}** (closed by {interaction.user.mention})", file=file)
        await interaction.followup.send("Ticket transcript saved. Closing this ticket…", ephemeral=True)
        await channel.delete(reason=f"Ticket closed by {interaction.user}")


class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Open a ticket", emoji="🎟️", style=discord.ButtonStyle.primary, custom_id="bg_ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        category_id = await database.get_setting(guild.id, "ticket_category")
        category = guild.get_channel(category_id) if category_id else None
        existing = next((c for c in guild.text_channels if (c.topic or "") == f"TimeBotTicket|{interaction.user.id}"), None)
        if existing:
            return await interaction.response.send_message(f"You already have an open ticket: {existing.mention}", ephemeral=True)
        bot_member = guild.me or guild.get_member(interaction.client.user.id)
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
            bot_member: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True),
        }
        staff_role_id = await database.get_setting(guild.id, "staff_role")
        staff_role = guild.get_role(staff_role_id) if staff_role_id else None
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name[:16]}".lower(), category=category,
            overwrites=overwrites, topic=f"TimeBotTicket|{interaction.user.id}")
        embed = discord.Embed(title="🎟️ Support ticket", description=f"Welcome {interaction.user.mention}. Describe what you need help with; staff will reply here.", color=BLUE)
        await channel.send(content=staff_role.mention if staff_role else None, embed=embed, view=TicketCloseView(), allowed_mentions=discord.AllowedMentions(roles=True))
        await interaction.response.send_message(f"Your ticket is open: {channel.mention}", ephemeral=True)


class FormModal(discord.ui.Modal):
    def __init__(self, question):
        super().__init__(title="Time Bot form")
        self.answer = discord.ui.TextInput(label=question[:45], style=discord.TextStyle.paragraph, max_length=1500)
        self.add_item(self.answer)

    async def on_submit(self, interaction: discord.Interaction):
        channel_id = await database.get_setting(interaction.guild.id, "form_channel")
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if channel:
            embed = discord.Embed(title="📨 Form response", color=BLUE, timestamp=datetime.now(timezone.utc))
            embed.add_field(name="Submitted by", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
            embed.add_field(name="Response", value=self.answer.value[:1000], inline=False)
            await channel.send(embed=embed)
        await interaction.response.send_message("✅ Your response was submitted.", ephemeral=True)


class GiveawayView(discord.ui.View):
    def __init__(self, message_id=0):
        super().__init__(timeout=None)
        self.message_id = int(message_id)

    @discord.ui.button(label="Enter giveaway", emoji="🎉", style=discord.ButtonStyle.success, custom_id="bg_giveaway_enter")
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.bot:
            return await interaction.response.send_message("Bots can't enter giveaways.", ephemeral=True)
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT 1 FROM giveaway_entries WHERE message_id=? AND user_id=?", (interaction.message.id, interaction.user.id)) as cur:
                already_entered = await cur.fetchone()
            if already_entered:
                await db.execute("DELETE FROM giveaway_entries WHERE message_id=? AND user_id=?", (interaction.message.id, interaction.user.id))
                entered = False
            else:
                await db.execute("INSERT INTO giveaway_entries(message_id,user_id) VALUES(?,?)", (interaction.message.id, interaction.user.id))
                entered = True
            async with db.execute("SELECT COUNT(*) FROM giveaway_entries WHERE message_id=?", (interaction.message.id,)) as cur:
                entry_count = (await cur.fetchone())[0]
            async with db.execute("SELECT winner_count,drop_mode,ended FROM giveaways WHERE message_id=?", (interaction.message.id,)) as cur:
                giveaway_row = await cur.fetchone()
            await db.commit()
        if interaction.message.embeds:
            embed = discord.Embed.from_dict(interaction.message.embeds[0].to_dict())
            field_index = next((i for i, field in enumerate(embed.fields) if field.name == "🎟️ Entries"), None)
            if field_index is not None:
                embed.set_field_at(field_index, name="🎟️ Entries", value=f"**{entry_count:,}**", inline=True)
            await interaction.message.edit(embed=embed)
        if giveaway_row and not giveaway_row[2] and giveaway_row[1] and entry_count >= giveaway_row[0]:
            await interaction.response.send_message("⚡ You claimed a spot in the drop!", ephemeral=True)
            cog = interaction.client.get_cog("Community")
            if cog:
                await cog.finish_giveaway(interaction.guild, interaction.message.id)
            return
        await interaction.response.send_message("🎉 You're entered!" if entered else "Your entry was removed.", ephemeral=True)


class ChooseEntryView(discord.ui.View):
    def __init__(self, winner_count):
        super().__init__(timeout=60)
        self.winner_count = winner_count
        self.entrants = set()

    @discord.ui.button(label="Enter draw", emoji="🎟️", style=discord.ButtonStyle.primary)
    async def enter(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.bot:
            return await interaction.response.send_message("Bots can't enter this draw.", ephemeral=True)
        if interaction.user.id in self.entrants:
            return await interaction.response.send_message("You're already entered.", ephemeral=True)
        self.entrants.add(interaction.user.id)
        if interaction.message.embeds:
            embed = discord.Embed.from_dict(interaction.message.embeds[0].to_dict())
            embed.set_field_at(0, name="🎟️ Entries", value=f"**{len(self.entrants):,}**", inline=True)
            await interaction.message.edit(embed=embed)
        await interaction.response.send_message("✅ You're in the draw!", ephemeral=True)


class Community(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._xp_cooldowns = {}
        self.giveaway_loop.start()

    def cog_unload(self):
        self.giveaway_loop.cancel()
        for task in getattr(self, "_timer_tasks", {}).values():
            task.cancel()

    @commands.command(name="snipe")
    async def snipe(self, ctx):
        """Show the most recently deleted message in this channel."""
        item = getattr(self, "_snipes", {}).get(ctx.channel.id)
        if not item:
            return await ctx.reply("There's no recently deleted message to show here.", mention_author=False)
        embed = discord.Embed(
            title="🕵️ Recently deleted message",
            description=item["content"][:4000] or "*(No text content)*",
            color=BLUE,
            timestamp=item["deleted_at"],
        )
        embed.set_author(name=item["author"], icon_url=item["avatar"])
        if item["attachments"]:
            embed.add_field(name="Attachments", value="\n".join(item["attachments"])[:1000], inline=False)
        await ctx.reply(embed=embed, mention_author=False, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="clearsnipe", aliases=["csnipe"])
    async def clear_snipe(self, ctx):
        """Clear the deleted-message record for this channel (full-access role required)."""
        snipes = getattr(self, "_snipes", {})
        if snipes.pop(ctx.channel.id, None) is None:
            return await ctx.reply("There's no snipe record to clear in this channel.", mention_author=False)
        await ctx.reply("🧹 Cleared this channel's snipe record.", mention_author=False)

    @commands.command(name="timer")
    async def timer(self, ctx, duration: str, *, text: str):
        """Ping you in this channel after a delay, e.g. ?timer 1m xyz."""
        seconds = parse_duration(duration)
        if not seconds or seconds < 1 or seconds > 30 * 86400:
            return await ctx.reply("Use a timer from 1 second to 30 days, such as `1m`, `30s`, or `2h`.", mention_author=False)
        task_id = (ctx.channel.id, ctx.author.id, time.time_ns())
        if not hasattr(self, "_timer_tasks"):
            self._timer_tasks = {}
        async def deliver():
            try:
                await asyncio.sleep(seconds)
                await ctx.channel.send(
                    f"⏰ {ctx.author.mention} **Timer:** {text[:1000]}",
                    allowed_mentions=discord.AllowedMentions(users=[ctx.author]),
                )
            except (discord.HTTPException, discord.Forbidden):
                pass
            finally:
                self._timer_tasks.pop(task_id, None)
        self._timer_tasks[task_id] = asyncio.create_task(deliver())
        await ctx.reply(f"⏰ I'll ping you here in {duration} with: **{text[:200]}**", mention_author=False)

    @commands.command(name="choose")
    async def choose(self, ctx, winners: int = 1):
        """Open a one-minute draw for members to enter, e.g. ?choose 1."""
        if not 1 <= winners <= 25:
            return await ctx.reply("Choose between 1 and 25 winners.", mention_author=False)
        end_at = datetime.now(timezone.utc) + timedelta(minutes=1)
        view = ChooseEntryView(winners)
        embed = discord.Embed(
            title="🎲 COMMUNITY DRAW",
            description=f"Enter with the button below. **{winners}** winner{'s' if winners != 1 else ''} will be chosen {discord.utils.format_dt(end_at, style='R')}.",
            color=BLUE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="🎟️ Entries", value="**0**", inline=True)
        embed.set_footer(text=f"Started by {ctx.author}")
        message = await ctx.send(embed=embed, view=view)
        async def finish_draw():
            await view.wait()
            selected = random.sample(list(view.entrants), min(winners, len(view.entrants)))
            for child in view.children:
                child.disabled = True
            if selected:
                mentions = ", ".join(f"<@{user_id}>" for user_id in selected)
                result = f"🎉 Draw complete! Winner{'s' if len(selected) != 1 else ''}: {mentions}"
                allowed = discord.AllowedMentions(users=[discord.Object(id=user_id) for user_id in selected])
            else:
                result = "The draw ended with no entries."
                allowed = discord.AllowedMentions.none()
            final_embed = discord.Embed(
                title="🏆 DRAW COMPLETE",
                description=f"**Winners requested:** {winners}\n**Entries:** {len(view.entrants)}",
                color=BLUE,
                timestamp=datetime.now(timezone.utc),
            )
            try:
                await message.edit(embed=final_embed, view=view)
                await ctx.send(result, allowed_mentions=allowed)
            except discord.HTTPException:
                pass
        asyncio.create_task(finish_draw())

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot or message.author.id == self.bot.user.id:
            return
        if not hasattr(self, "_snipes"):
            self._snipes = {}
        self._snipes[message.channel.id] = {
            "content": message.content or "",
            "author": str(message.author),
            "avatar": message.author.display_avatar.url,
            "attachments": [attachment.url for attachment in message.attachments],
            "deleted_at": datetime.now(timezone.utc),
        }

    @commands.command(name="ticketpanel")
    async def ticketpanel(self, ctx):
        embed = discord.Embed(title="🎟️ Need help?", description="Open a private support ticket with our team.", color=BLUE)
        await ctx.send(embed=embed, view=TicketOpenView())

    @commands.command(name="tickets")
    async def tickets(self, ctx, setting: str, value: str):
        if setting == "category":
            category = ctx.guild.get_channel(int(value.strip("<#>")))
            if not isinstance(category, discord.CategoryChannel):
                return await ctx.reply("Give me a category mention or category ID.", mention_author=False)
            await database.set_setting(ctx.guild.id, "ticket_category", category.id)
            await ctx.reply(f"✅ Tickets will open under {category.name}.", mention_author=False)
        elif setting == "log":
            channel = ctx.guild.get_channel(int(value.strip("<#>")))
            if not isinstance(channel, discord.TextChannel):
                return await ctx.reply("Give me a text channel mention or channel ID.", mention_author=False)
            await database.set_setting(ctx.guild.id, "ticket_log_channel", channel.id)
            await ctx.reply(f"✅ Ticket transcripts will be sent to {channel.mention}.", mention_author=False)
        elif setting == "staff":
            role = ctx.guild.get_role(int(value.strip("<@&>")))
            if not role:
                return await ctx.reply("Give me a role mention or role ID.", mention_author=False)
            await database.set_setting(ctx.guild.id, "staff_role", role.id)
            await ctx.reply(f"✅ Ticket staff role set to {role.mention}.", mention_author=False)
        else:
            await ctx.reply("Use `?tickets category #category`, `?tickets log #channel`, or `?tickets staff @role`.", mention_author=False)

    @commands.command(name="close")
    async def close_ticket(self, ctx):
        channel = ctx.channel
        if not isinstance(channel, discord.TextChannel) or not (channel.topic or "").startswith("TimeBotTicket|"):
            return await ctx.reply("Use this inside a Time Bot ticket.", mention_author=False)
        owner = int(channel.topic.split("|", 1)[1])
        if ctx.author.id != owner and not access_control.member_has_permission(ctx, "all"):
            return await ctx.reply("Only the ticket owner or staff can close it.", mention_author=False)
        await ctx.reply("Closing ticket and saving a transcript…", mention_author=False)
        await self.close_channel(channel, ctx.author)

    async def close_channel(self, channel, closer):
        lines = []
        async for message in channel.history(limit=500, oldest_first=True):
            lines.append(f"[{message.created_at:%Y-%m-%d %H:%M UTC}] {message.author} ({message.author.id}): {message.clean_content or '[attachment/embed]'}")
        file = discord.File(io.BytesIO("\n".join(lines).encode()), filename=f"{channel.name}-transcript.txt")
        log_id = await database.get_setting(channel.guild.id, "ticket_log_channel")
        log = channel.guild.get_channel(log_id) if log_id else None
        if log:
            await log.send(content=f"Transcript for **{channel.name}** (closed by {closer.mention})", file=file)
        await channel.delete(reason=f"Ticket closed by {closer}")

    @commands.command(name="form")
    async def form(self, ctx, *, question="What would you like us to know?"):
        await ctx.reply("Open the form here:", view=FormButtonView(question), mention_author=False)

    @commands.command(name="setform")
    async def setform(self, ctx, channel: discord.TextChannel = None):
        await database.set_setting(ctx.guild.id, "form_channel", (channel or ctx.channel).id)
        await ctx.reply(f"📨 Form responses will go to {(channel or ctx.channel).mention}.", mention_author=False)

    @commands.command(name="tag")
    async def tag(self, ctx, action_or_name: str, *, rest=None):
        if action_or_name.lower() == "add":
            if not access_control.member_has_permission(ctx, "all"):
                return await ctx.reply("You need a full-access Time Bot role to add tags.", mention_author=False)
            if not rest or "|" not in rest:
                return await ctx.reply("Use `?tag add name | response`.", mention_author=False)
            name, content = (item.strip() for item in rest.split("|", 1))
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute("INSERT OR REPLACE INTO tags(guild_id,name,content,author_id) VALUES(?,?,?,?)", (ctx.guild.id, name.lower(), content[:1800], ctx.author.id))
                await db.commit()
            return await ctx.reply(f"✅ Tag `{name}` saved.", mention_author=False)
        if action_or_name.lower() == "delete":
            if not access_control.member_has_permission(ctx, "all"):
                return await ctx.reply("You need a full-access Time Bot role to delete tags.", mention_author=False)
            if not rest:
                return await ctx.reply("Use `?tag delete name`.", mention_author=False)
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute("DELETE FROM tags WHERE guild_id=? AND name=?", (ctx.guild.id, rest.lower()))
                await db.commit()
            return await ctx.reply(f"🗑️ Deleted tag `{rest}` if it existed.", mention_author=False)
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT content FROM tags WHERE guild_id=? AND name=?", (ctx.guild.id, action_or_name.lower())) as cur:
                row = await cur.fetchone()
        await ctx.reply(row[0] if row else f"No tag named `{action_or_name}`.", mention_author=False, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="tags")
    async def tags(self, ctx):
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT name FROM tags WHERE guild_id=? ORDER BY name", (ctx.guild.id,)) as cur:
                rows = await cur.fetchall()
        await ctx.reply("🏷️ **Tags:** " + (", ".join(f"`{row[0]}`" for row in rows) if rows else "none yet"), mention_author=False)

    @commands.command(name="leaderboard", aliases=["top"])
    async def leaderboard(self, ctx):
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT user_id,xp,messages FROM activity WHERE guild_id=? ORDER BY xp DESC LIMIT 10", (ctx.guild.id,)) as cur:
                rows = await cur.fetchall()
        text = "\n".join(f"**{index}.** <@{uid}> — level {int(xp ** 0.5 // 10)} • {xp} XP" for index, (uid, xp, _) in enumerate(rows, 1)) or "No activity recorded yet."
        await ctx.reply(embed=discord.Embed(title="🏆 Activity leaderboard", description=text, color=BLUE), mention_author=False)

    @commands.command(name="level")
    async def level(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT xp,messages FROM activity WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id)) as cur:
                row = await cur.fetchone()
        xp, messages = row or (0, 0)
        level = int(xp ** 0.5 // 10)
        await ctx.reply(f"✨ {member.mention} • Level **{level}** • **{xp} XP** • {messages} messages", mention_author=False)

    @commands.command(name="starboard")
    async def starboard(self, ctx, channel: discord.TextChannel = None, threshold: int = 3):
        if channel is None:
            await database.set_setting(ctx.guild.id, "starboard_channel", None)
            return await ctx.reply("Starboard disabled.", mention_author=False)
        await database.set_setting(ctx.guild.id, "starboard_channel", channel.id)
        await database.set_setting(ctx.guild.id, "starboard_threshold", max(1, min(threshold, 50)))
        await ctx.reply(f"⭐ Starboard set to {channel.mention} (threshold {max(1, min(threshold, 50))}).", mention_author=False)

    @commands.hybrid_group(name="giveaway", aliases=["g"], invoke_without_command=True)
    async def giveaway(self, ctx):
        """Create and manage giveaways. Use /giveaway or ?giveaway with a subcommand."""
        await ctx.reply(
            "🎁 **Giveaway commands**\n"
            "`/giveaway create <duration> <winners> <prize>` — schedule a draw\n"
            "`/giveaway drop <winners> <prize>` — first-come giveaway\n"
            "`/giveaway edit <message_id> [time] [winners] [prize]` • `/giveaway fix <message_id>`\n"
            "`/giveaway end <message_id>` • `/giveaway reroll <message_id>`\n"
            "`/giveaway delete <message_id>` • `/giveaway list`",
            mention_author=False,
        )

    @giveaway.command(name="create")
    async def giveaway_create(self, ctx, duration: str, winners: int = 1, *, prize: str):
        """Start a giveaway. Example: /giveaway create 1h 2 Nitro."""
        seconds = parse_duration(duration)
        if not seconds or seconds < 60 or seconds > 30 * 86400:
            return await ctx.reply("Use a duration from 1 minute to 30 days, such as `2h` or `3d`.", mention_author=False)
        if not 1 <= winners <= 100:
            return await ctx.reply("Choose between 1 and 100 winners.", mention_author=False)
        ends = time.time() + seconds
        embed = discord.Embed(
            title="🎉  GIVEAWAY  🎉",
            description=f"## {prize}\n\n> **Hosted by** {ctx.author.mention}\n> **Winners** `{winners}`\n> **Ends** {discord.utils.format_dt(datetime.fromtimestamp(ends, timezone.utc), style='R')}\n\nTap **Enter giveaway** below to join.",
            color=BLUE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="🎟️ Entries", value="**0**", inline=True)
        embed.set_footer(text="TIME BOT  •  Good luck, everyone!")
        message = await ctx.send(embed=embed, view=GiveawayView())
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO giveaways(message_id,guild_id,channel_id,prize,host_id,ends_at,winner_count,drop_mode) VALUES(?,?,?,?,?,?,?,0)",
                (message.id, ctx.guild.id, ctx.channel.id, prize, ctx.author.id, ends, winners),
            )
            await db.commit()

    @giveaway.command(name="drop")
    async def giveaway_drop(self, ctx, winners: int = 1, *, prize: str):
        """Start a fast drop; it ends as soon as all winning spots are claimed."""
        if not 1 <= winners <= 100:
            return await ctx.reply("Choose between 1 and 100 winners.", mention_author=False)
        ends = time.time() + 365 * 86400
        embed = discord.Embed(
            title="⚡  GIVEAWAY DROP  ⚡",
            description=f"## {prize}\n\n> **Spots** `{winners}`\n> First to claim a spot wins.\n\nTap **Claim a spot** below!",
            color=BLUE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="🎟️ Entries", value="**0**", inline=True)
        embed.set_footer(text="TIME BOT  •  First come, first served")
        view = GiveawayView()
        view.children[0].label = "Claim a spot"
        view.children[0].emoji = "⚡"
        message = await ctx.send(embed=embed, view=view)
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO giveaways(message_id,guild_id,channel_id,prize,host_id,ends_at,winner_count,drop_mode) VALUES(?,?,?,?,?,?,?,1)",
                (message.id, ctx.guild.id, ctx.channel.id, prize, ctx.author.id, ends, winners),
            )
            await db.commit()

    @giveaway.command(name="edit")
    async def giveaway_edit(self, ctx, message_id: int, duration: str = None, winners: int = None, *, prize: str = None):
        """Edit an active giveaway's remaining time, winner count, or prize."""
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute(
                "SELECT channel_id,prize,ends_at,winner_count,ended,host_id,drop_mode FROM giveaways WHERE message_id=? AND guild_id=?",
                (message_id, ctx.guild.id),
            ) as cur:
                row = await cur.fetchone()
            if not row or row[4]:
                return await ctx.reply("I couldn't find an active giveaway with that message ID.", mention_author=False)
            ends_at = row[2]
            if duration:
                seconds = parse_duration(duration)
                if not seconds or seconds < 60 or seconds > 365 * 86400:
                    return await ctx.reply("Use a remaining time from 1 minute to 365 days, such as `2h` or `3d`.", mention_author=False)
                ends_at = time.time() + seconds
            winner_count = winners if winners is not None else row[3]
            if not 1 <= winner_count <= 100:
                return await ctx.reply("Choose between 1 and 100 winners.", mention_author=False)
            prize = (prize or row[1]).strip()
            if not prize:
                return await ctx.reply("Prize can't be empty.", mention_author=False)
            await db.execute(
                "UPDATE giveaways SET prize=?,ends_at=?,winner_count=? WHERE message_id=?",
                (prize, ends_at, winner_count, message_id),
            )
            await db.commit()
        channel = ctx.guild.get_channel(row[0])
        if not channel:
            return await ctx.reply("Giveaway settings were updated, but its channel is unavailable.", mention_author=False)
        try:
            message = await channel.fetch_message(message_id)
            embed = discord.Embed(
                title="⚡  GIVEAWAY DROP  ⚡" if row[6] else "🎉  GIVEAWAY  🎉",
                description=(f"## {prize}\n\n> **Spots** `{winner_count}`\n> First to claim a spot wins.\n\nTap **Claim a spot** below!" if row[6] else f"## {prize}\n\n> **Hosted by** <@{row[5]}>\n> **Winners** `{winner_count}`\n> **Ends** {discord.utils.format_dt(datetime.fromtimestamp(ends_at, timezone.utc), style='R')}\n\nTap **Enter giveaway** below to join."),
                color=BLUE,
                timestamp=datetime.now(timezone.utc),
            )
            if row[6]:
                embed.description = f"## {prize}\n\n> **Spots** `{winner_count}`\n> First to claim a spot wins.\n> **Ends** {discord.utils.format_dt(datetime.fromtimestamp(ends_at, timezone.utc), style='R')}\n\nTap **Claim a spot** below!"
            async with aiosqlite.connect(database.DB_PATH) as db:
                async with db.execute("SELECT COUNT(*) FROM giveaway_entries WHERE message_id=?", (message_id,)) as cur:
                    entries = (await cur.fetchone())[0]
            embed.add_field(name="🎟️ Entries", value=f"**{entries:,}**", inline=True)
            embed.set_footer(text="TIME BOT  •  Good luck, everyone!")
            if row[6]:
                view = GiveawayView(message_id)
                view.children[0].label = "Claim a spot"
                view.children[0].emoji = "⚡"
                await message.edit(embed=embed, view=view)
            else:
                await message.edit(embed=embed)
        except discord.HTTPException:
            return await ctx.reply("Settings were saved, but I couldn't update the giveaway post. Try `/giveaway fix`.", mention_author=False)
        await ctx.reply("✅ Giveaway updated.", mention_author=False)

    @giveaway.command(name="fix")
    async def giveaway_fix(self, ctx, message_id: int):
        """Restore the entry button on an active giveaway post."""
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT channel_id,ended,drop_mode FROM giveaways WHERE message_id=? AND guild_id=?", (message_id, ctx.guild.id)) as cur:
                row = await cur.fetchone()
        if not row or row[1]:
            return await ctx.reply("I couldn't find an active giveaway with that message ID.", mention_author=False)
        channel = ctx.guild.get_channel(row[0])
        if not channel:
            return await ctx.reply("That giveaway's channel is unavailable.", mention_author=False)
        try:
            message = await channel.fetch_message(message_id)
            view = GiveawayView(message_id)
            if row[2]:
                view.children[0].label = "Claim a spot"
                view.children[0].emoji = "⚡"
            await message.edit(view=view)
        except discord.HTTPException:
            return await ctx.reply("I couldn't edit that giveaway message. Check my View Channel and Manage Messages permissions.", mention_author=False)
        await ctx.reply("✅ Giveaway entry button restored.", mention_author=False)

    @giveaway.command(name="end")
    async def giveaway_end(self, ctx, message_id: int):
        """End a giveaway immediately and draw its winners."""
        await self.finish_giveaway(ctx.guild, message_id)
        await ctx.reply("🎉 Giveaway ended.", mention_author=False)

    @giveaway.command(name="reroll")
    async def giveaway_reroll(self, ctx, message_id: int):
        """Pick one additional winner from an ended giveaway."""
        winner = await self.reroll_giveaway(ctx.guild, message_id)
        await ctx.reply(f"🎉 New winner: <@{winner}>!" if winner else "No eligible new winner was found.", mention_author=False)

    @giveaway.command(name="delete")
    async def giveaway_delete(self, ctx, message_id: int):
        """Delete a giveaway without drawing winners."""
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT channel_id FROM giveaways WHERE message_id=? AND guild_id=?", (message_id, ctx.guild.id)) as cur:
                row = await cur.fetchone()
            if not row:
                return await ctx.reply("I couldn't find that giveaway in this server.", mention_author=False)
            await db.execute("DELETE FROM giveaways WHERE message_id=?", (message_id,))
            await db.execute("DELETE FROM giveaway_entries WHERE message_id=?", (message_id,))
            await db.execute("DELETE FROM giveaway_winners WHERE message_id=?", (message_id,))
            await db.commit()
        channel = ctx.guild.get_channel(row[0])
        if channel:
            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
            except discord.HTTPException:
                pass
        await ctx.reply("🗑️ Giveaway deleted without a draw.", mention_author=False)

    @giveaway.command(name="list")
    async def giveaway_list(self, ctx):
        """List the active giveaways in this server."""
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT message_id,channel_id,prize,ends_at,winner_count,drop_mode FROM giveaways WHERE guild_id=? AND ended=0 ORDER BY ends_at LIMIT 15", (ctx.guild.id,)) as cur:
                rows = await cur.fetchall()
        if not rows:
            return await ctx.reply("There are no active giveaways right now.", mention_author=False)
        lines = []
        for message_id, channel_id, prize, ends_at, count, drop_mode in rows:
            mode = "⚡ Drop" if drop_mode else "🎉 Giveaway"
            link = f"https://discord.com/channels/{ctx.guild.id}/{channel_id}/{message_id}"
            lines.append(f"{mode} • [{prize}]({link}) • `{count}` winner(s) • <t:{int(ends_at)}:R>")
        await ctx.reply(embed=discord.Embed(title="🎁 ACTIVE GIVEAWAYS", description="\n".join(lines), color=BLUE), mention_author=False)

    async def finish_giveaway(self, guild, message_id):
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT channel_id,prize,ended,winner_count FROM giveaways WHERE message_id=? AND guild_id=?", (message_id, guild.id)) as cur:
                row = await cur.fetchone()
            if not row or row[2]:
                return
            await db.execute("UPDATE giveaways SET ended=1 WHERE message_id=?", (message_id,))
            async with db.execute("SELECT user_id FROM giveaway_entries WHERE message_id=?", (message_id,)) as cur:
                entries = [item[0] for item in await cur.fetchall()]
            winners = random.sample(entries, min(row[3], len(entries))) if entries else []
            await db.executemany("INSERT OR IGNORE INTO giveaway_winners(message_id,user_id) VALUES(?,?)", [(message_id, user_id) for user_id in winners])
            await db.commit()
        channel = guild.get_channel(row[0])
        if not channel:
            return
        try:
            message = await channel.fetch_message(message_id)
            winner_text = ", ".join(f"<@{user_id}>" for user_id in winners) if winners else "No entries."
            embed = discord.Embed(title="🏆 GIVEAWAY COMPLETE", description=f"## {row[1]}\n\n**Winner(s):** {winner_text}\n\n**Giveaway:** `{message_id}`", color=BLUE, timestamp=datetime.now(timezone.utc))
            embed.set_footer(text="TIME BOT  •  Congratulations to the winners!")
            await message.edit(embed=embed, view=None)
            if winners:
                await channel.send(f"🎉 Congratulations {winner_text}! You won **{row[1]}**.", allowed_mentions=discord.AllowedMentions(users=True))
        except discord.HTTPException:
            pass

    async def reroll_giveaway(self, guild, message_id):
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT channel_id,prize,ended FROM giveaways WHERE message_id=? AND guild_id=?", (message_id, guild.id)) as cur:
                row = await cur.fetchone()
            if not row or not row[2]:
                return None
            async with db.execute("SELECT user_id FROM giveaway_entries WHERE message_id=?", (message_id,)) as cur:
                entries = [record[0] for record in await cur.fetchall()]
            async with db.execute("SELECT user_id FROM giveaway_winners WHERE message_id=?", (message_id,)) as cur:
                previous = {record[0] for record in await cur.fetchall()}
            eligible = [user_id for user_id in entries if user_id not in previous]
            if not eligible:
                return None
            winner = random.choice(eligible)
            await db.execute("INSERT OR IGNORE INTO giveaway_winners(message_id,user_id) VALUES(?,?)", (message_id, winner))
            await db.commit()
        channel = guild.get_channel(row[0])
        if channel:
            await channel.send(f"🔁 Reroll winner for **{row[1]}**: <@{winner}>!", allowed_mentions=discord.AllowedMentions(users=True))
        return winner

    @tasks.loop(seconds=10)
    async def giveaway_loop(self):
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT message_id,guild_id FROM giveaways WHERE ended=0 AND ends_at<=?", (time.time(),)) as cur:
                rows = await cur.fetchall()
        for message_id, guild_id in rows:
            guild = self.bot.get_guild(guild_id)
            if guild: await self.finish_giveaway(guild, message_id)

    @giveaway_loop.before_loop
    async def before_giveaway_loop(self):
        await self.bot.wait_until_ready()

    @commands.command(name="reactionrole")
    async def reactionrole(self, ctx, message_id: int, emoji: str, role: discord.Role):
        if access_control.is_access_role(ctx.guild.id, role.id):
            return await ctx.reply("Access-control roles can't be assigned through reaction roles.", mention_author=False)
        if role >= ctx.guild.me.top_role:
            return await ctx.reply("Move Time Bot's role above that role first.", mention_author=False)
        channel = ctx.channel
        try:
            message = await channel.fetch_message(message_id)
            await message.add_reaction(emoji)
        except discord.HTTPException as exc:
            return await ctx.reply(f"Couldn't add that reaction: {exc}", mention_author=False)
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute("INSERT OR REPLACE INTO reaction_roles(message_id,emoji,role_id) VALUES(?,?,?)", (message_id, emoji, role.id))
            await db.commit()
        await ctx.reply(f"✅ Reaction role linked: {emoji} → {role.mention}.", mention_author=False)

    @commands.command(name="highlight")
    async def highlight(self, ctx, action: str = "list", *, keyword=None):
        items = await database.get_setting(ctx.guild.id, f"highlights:{ctx.author.id}", [])
        if action == "add" and keyword:
            if keyword.lower() not in [x.lower() for x in items] and len(items) < 20: items.append(keyword[:80])
            await database.set_setting(ctx.guild.id, f"highlights:{ctx.author.id}", items)
            return await ctx.reply(f"🔔 Added highlight `{keyword}`.", mention_author=False)
        if action == "remove" and keyword:
            items = [x for x in items if x.lower() != keyword.lower()]
            await database.set_setting(ctx.guild.id, f"highlights:{ctx.author.id}", items)
            return await ctx.reply(f"Removed `{keyword}` from your highlights.", mention_author=False)
        await ctx.reply("**Your highlights:** " + (", ".join(f"`{x}`" for x in items) if items else "none"), mention_author=False)

    @commands.command(name="panel", aliases=["embed"])
    async def panel_message(self, ctx, channel: discord.TextChannel, *, content):
        """Post a custom text panel as an embed. Use: ?panel #channel Title | Message"""
        parts = [p.strip() for p in content.split("|", 1)]
        if len(parts) == 2:
            title, description = parts
        else:
            title, description = "", parts[0]
        if not description:
            return await ctx.reply("Add panel text. Use `?panel #channel Title | Your message` or `?panel #channel Your message`.", mention_author=False)
        embed = discord.Embed(title=title[:256] or None, description=description[:4000], color=BLUE)
        embed.set_footer(text="TIME BOT  •  Server panel")
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        await ctx.reply(f"✅ Panel posted in {channel.mention}.", mention_author=False)

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot: return
        now = time.time()
        key = (message.guild.id, message.author.id)
        if now - self._xp_cooldowns.get(key, 0) >= 60 and len(message.content.strip()) >= 4:
            self._xp_cooldowns[key] = now
            async with aiosqlite.connect(database.DB_PATH) as db:
                await db.execute("INSERT INTO activity(guild_id,user_id,xp,messages) VALUES(?,?,?,1) ON CONFLICT(guild_id,user_id) DO UPDATE SET xp=xp+excluded.xp,messages=messages+1", (message.guild.id, message.author.id, random.randint(10, 20)))
                await db.commit()
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT key,value FROM settings WHERE guild_id=? AND key LIKE 'highlights:%'", (message.guild.id,)) as cur:
                subscriptions = await cur.fetchall()
        for setting_key, raw_keywords in subscriptions:
            try: keywords = __import__("json").loads(raw_keywords)
            except (ValueError, TypeError): continue
            hits = [word for word in keywords if word.lower() in message.content.lower()]
            if hits:
                user_id = int(setting_key.split(":", 1)[1])
                user = self.bot.get_user(user_id)
                if user and user.id != message.author.id:
                    try: await user.send(f"🔔 `{message.guild.name} • #{message.channel.name}` matched `{hits[0]}`: {message.jump_url}")
                    except discord.HTTPException: pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.guild_id is None or (self.bot.user and payload.user_id == self.bot.user.id): return
        emoji = str(payload.emoji)
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT role_id FROM reaction_roles WHERE message_id=? AND emoji=?", (payload.message_id, emoji)) as cur:
                row = await cur.fetchone()
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        role = guild.get_role(row[0]) if guild and row else None
        if member and role and not access_control.is_access_role(guild.id, role.id) and role < guild.me.top_role:
            try: await member.add_roles(role, reason="Time Bot reaction role")
            except discord.HTTPException: pass
        if emoji != "⭐" or not guild: return
        channel_id = await database.get_setting(guild.id, "starboard_channel")
        threshold = await database.get_setting(guild.id, "starboard_threshold", 3)
        channel = guild.get_channel(channel_id) if channel_id else None
        source = guild.get_channel(payload.channel_id)
        if not channel or not source: return
        try:
            message = await source.fetch_message(payload.message_id)
            reaction = discord.utils.get(message.reactions, emoji="⭐")
            if not reaction or reaction.count < threshold: return
            embed = discord.Embed(description=message.content[:4000] or "[attachment/embed]", color=BLUE, timestamp=message.created_at)
            embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
            embed.add_field(name="Source", value=f"[Jump to message]({message.jump_url}) • ⭐ {reaction.count}")
            if message.attachments: embed.set_image(url=message.attachments[0].url)
            async with aiosqlite.connect(database.DB_PATH) as db:
                async with db.execute("SELECT board_message_id FROM starboard_posts WHERE source_message_id=?", (message.id,)) as cur:
                    prior = await cur.fetchone()
                if prior:
                    try:
                        post = await channel.fetch_message(prior[0])
                        await post.edit(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                    except discord.NotFound:
                        prior = None
                if not prior:
                    post = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                    await db.execute("INSERT OR REPLACE INTO starboard_posts(source_message_id,board_message_id) VALUES(?,?)", (message.id, post.id))
                    await db.commit()
        except discord.HTTPException: pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        if payload.guild_id is None: return
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute("SELECT role_id FROM reaction_roles WHERE message_id=? AND emoji=?", (payload.message_id, str(payload.emoji))) as cur:
                row = await cur.fetchone()
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        role = guild.get_role(row[0]) if guild and row else None
        if member and role and not access_control.is_access_role(guild.id, role.id) and role < guild.me.top_role:
            try: await member.remove_roles(role, reason="Time Bot reaction role")
            except discord.HTTPException: pass


class FormButtonView(discord.ui.View):
    def __init__(self, question):
        super().__init__(timeout=180)
        self.question = question

    @discord.ui.button(label="Open form", emoji="📝", style=discord.ButtonStyle.primary)
    async def open_form(self, interaction, button):
        await interaction.response.send_modal(FormModal(self.question))


async def setup(bot):
    await bot.add_cog(Community(bot))
    bot.add_view(TicketOpenView())
    bot.add_view(TicketCloseView())
    async with aiosqlite.connect(database.DB_PATH) as db:
        async with db.execute("SELECT message_id FROM giveaways WHERE ended=0") as cur:
            rows = await cur.fetchall()
    for (message_id,) in rows:
        bot.add_view(GiveawayView(message_id))
