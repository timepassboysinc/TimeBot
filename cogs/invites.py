import aiosqlite
import discord
from discord.ext import commands

import database

BLUE = 0x176BFF


class InviteTracking(commands.Cog):
    """Track invite joins. The bot needs Manage Server to read invite use counts."""

    def __init__(self, bot):
        self.bot = bot
        self.invite_cache = {}

    async def refresh_guild(self, guild):
        try:
            invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return
        self.invite_cache[guild.id] = {
            invite.code: (invite.uses or 0, invite.inviter.id if invite.inviter else None)
            for invite in invites
        }

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self.refresh_guild(guild)

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.refresh_guild(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        cache = self.invite_cache.setdefault(invite.guild.id, {})
        cache[invite.code] = (invite.uses or 0, invite.inviter.id if invite.inviter else None)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        self.invite_cache.setdefault(invite.guild.id, {}).pop(invite.code, None)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        previous = self.invite_cache.get(member.guild.id, {})
        try:
            current_invites = await member.guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return
        used_invite = None
        updated = {}
        for invite in current_invites:
            uses = invite.uses or 0
            inviter_id = invite.inviter.id if invite.inviter else None
            updated[invite.code] = (uses, inviter_id)
            old_uses, old_inviter = previous.get(invite.code, (0, inviter_id))
            if inviter_id and uses > old_uses:
                used_invite = inviter_id
        self.invite_cache[member.guild.id] = updated
        if not used_invite:
            return
        async with aiosqlite.connect(database.DB_PATH) as db:
            await db.execute(
                "INSERT INTO invite_counts(guild_id,user_id,uses) VALUES(?,?,1) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET uses=uses+1",
                (member.guild.id, used_invite),
            )
            await db.commit()

    @commands.command(name="invites")
    async def invites(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute(
                "SELECT uses FROM invite_counts WHERE guild_id=? AND user_id=?",
                (ctx.guild.id, member.id),
            ) as cur:
                row = await cur.fetchone()
        count = row[0] if row else 0
        embed = discord.Embed(title="📨 INVITE PROFILE", description=f"{member.mention} has **{count:,}** tracked invites.", color=BLUE)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Invite counts begin after Time Bot is added and granted Manage Server.")
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="inviteleaderboard", aliases=["invitetop"])
    async def inviteleaderboard(self, ctx):
        async with aiosqlite.connect(database.DB_PATH) as db:
            async with db.execute(
                "SELECT user_id,uses FROM invite_counts WHERE guild_id=? ORDER BY uses DESC LIMIT 10",
                (ctx.guild.id,),
            ) as cur:
                rows = await cur.fetchall()
        description = "\n".join(f"**{index}.** <@{user_id}> — `{uses:,}` invites" for index, (user_id, uses) in enumerate(rows, 1)) or "No invites have been tracked yet."
        embed = discord.Embed(title="🏆 INVITE LEADERBOARD", description=description, color=BLUE)
        embed.set_footer(text="TIME BOT  •  Invite tracker")
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="clearinvites")
    async def clearinvites(self, ctx, member: discord.Member = None):
        async with aiosqlite.connect(database.DB_PATH) as db:
            if member:
                await db.execute("DELETE FROM invite_counts WHERE guild_id=? AND user_id=?", (ctx.guild.id, member.id))
            else:
                await db.execute("DELETE FROM invite_counts WHERE guild_id=?", (ctx.guild.id,))
            await db.commit()
        await ctx.reply("🧹 Invite counts cleared" + (f" for {member.mention}." if member else " for this server."), mention_author=False)


async def setup(bot):
    await bot.add_cog(InviteTracking(bot))
