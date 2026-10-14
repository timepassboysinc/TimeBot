import json
import os
import time
import xml.etree.ElementTree as ET

import aiohttp
import discord
from discord.ext import commands, tasks

import database

BLUE = 0x176BFF


class Feeds(commands.Cog):
    """Lightweight public feed polling for YouTube, Reddit and Twitch."""
    def __init__(self, bot):
        self.bot = bot
        self._twitch_token = None
        self._twitch_token_exp = 0
        self.poll_feeds.start()

    def cog_unload(self):
        self.poll_feeds.cancel()

    @commands.command(name="feed")
    async def feed(self, ctx, action: str = None, platform: str = None, source: str = None, channel: discord.TextChannel = None):
        """?feed add youtube <channel id> #channel; same form for reddit/twitch."""
        feeds = await database.get_setting(ctx.guild.id, "social_feeds", [])
        if action == "list":
            listing = "\n".join(f"`{f['id']}` • **{f['platform']}** `{f['source']}` → <#{f['channel_id']}>" for f in feeds) or "No feeds configured."
            return await ctx.reply(f"📡 **Feeds**\n{listing}", mention_author=False)
        if action == "remove" and platform:
            before = len(feeds)
            feeds = [f for f in feeds if f["id"] != platform]
            await database.set_setting(ctx.guild.id, "social_feeds", feeds)
            return await ctx.reply("✅ Feed removed." if len(feeds) < before else "No feed with that ID.", mention_author=False)
        if action != "add" or platform not in {"youtube", "reddit", "twitch"} or not source or not channel:
            return await ctx.reply(
                "Use `?feed add youtube <channel ID> #channel`, `?feed add reddit <subreddit> #channel`, "
                "`?feed add twitch <username> #channel`, `?feed list`, or `?feed remove <feed ID>`. "
                "Twitch requires API credentials in `.env`; TikTok does not provide a stable public feed endpoint.",
                mention_author=False)
        if len(feeds) >= 25:
            return await ctx.reply("This server has reached 25 configured feeds.", mention_author=False)
        item = {"id": str(int(time.time() * 1000)), "platform": platform, "source": source.lstrip("r/"), "channel_id": channel.id, "last_id": ""}
        feeds.append(item)
        await database.set_setting(ctx.guild.id, "social_feeds", feeds)
        await ctx.reply(f"✅ Added **{platform}** feed `{source}` → {channel.mention}.", mention_author=False)

    async def twitch_access_token(self, session):
        client_id, secret = os.getenv("TWITCH_CLIENT_ID"), os.getenv("TWITCH_CLIENT_SECRET")
        if not client_id or not secret:
            return None, None
        if self._twitch_token and time.time() < self._twitch_token_exp:
            return client_id, self._twitch_token
        async with session.post("https://id.twitch.tv/oauth2/token", data={"client_id": client_id, "client_secret": secret, "grant_type": "client_credentials"}, timeout=12) as response:
            if response.status != 200: return client_id, None
            data = await response.json()
        self._twitch_token = data.get("access_token")
        self._twitch_token_exp = time.time() + int(data.get("expires_in", 3600)) - 60
        return client_id, self._twitch_token

    async def read_youtube(self, session, source):
        channel_id = source.split("/")[-1] if source.startswith("http") else source
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        async with session.get(url, timeout=12) as response:
            if response.status != 200: return None
            xml = await response.text()
        root = ET.fromstring(xml)
        entry = root.find("{http://www.w3.org/2005/Atom}entry")
        if entry is None: return None
        title = entry.findtext("{http://www.w3.org/2005/Atom}title", "New upload")
        link = entry.find("{http://www.w3.org/2005/Atom}link")
        video_url = link.attrib.get("href", "") if link is not None else ""
        video_id = entry.findtext("{http://www.youtube.com/xml/schemas/2015}videoId", "")
        return {"id": video_id, "title": title, "url": video_url}

    async def read_reddit(self, session, source):
        url = f"https://www.reddit.com/r/{source}/new.json?limit=1"
        async with session.get(url, headers={"User-Agent": "TimeBotDiscordBot/1.0"}, timeout=12) as response:
            if response.status != 200: return None
            data = await response.json(content_type=None)
        posts = data.get("data", {}).get("children", [])
        if not posts: return None
        post = posts[0]["data"]
        return {"id": post.get("id"), "title": post.get("title", "New post"), "url": "https://reddit.com" + post.get("permalink", "")}

    async def read_twitch(self, session, source):
        client_id, token = await self.twitch_access_token(session)
        if not token: return None
        headers = {"Client-ID": client_id, "Authorization": f"Bearer {token}"}
        async with session.get("https://api.twitch.tv/helix/streams", params={"user_login": source}, headers=headers, timeout=12) as response:
            if response.status != 200: return None
            data = await response.json()
        streams = data.get("data", [])
        if not streams: return None
        stream = streams[0]
        return {"id": stream.get("id"), "title": stream.get("title", "Live now"), "url": f"https://twitch.tv/{source}"}

    @tasks.loop(seconds=120)
    async def poll_feeds(self):
        async with aiohttp.ClientSession() as session:
            async with __import__("aiosqlite").connect(database.DB_PATH) as db:
                async with db.execute("SELECT guild_id,value FROM settings WHERE key='social_feeds'") as cur:
                    rows = await cur.fetchall()
            for guild_id, raw in rows:
                try: feeds = json.loads(raw)
                except (ValueError, TypeError): continue
                changed = False
                for feed in feeds:
                    try:
                        if feed["platform"] == "youtube": latest = await self.read_youtube(session, feed["source"])
                        elif feed["platform"] == "reddit": latest = await self.read_reddit(session, feed["source"])
                        else: latest = await self.read_twitch(session, feed["source"])
                    except (aiohttp.ClientError, ET.ParseError, ValueError, KeyError):
                        continue
                    if not latest or not latest.get("id") or latest["id"] == feed.get("last_id"):
                        continue
                    # First poll establishes the baseline, so adding a feed won't dump an old post.
                    first_seen = not feed.get("last_id")
                    feed["last_id"] = latest["id"]
                    changed = True
                    if first_seen: continue
                    channel = self.bot.get_channel(int(feed["channel_id"]))
                    if channel:
                        embed = discord.Embed(title=latest["title"][:250], url=latest["url"], color=BLUE)
                        embed.description = f"New {feed['platform']} post from **{feed['source']}**"
                        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                if changed:
                    await database.set_setting(int(guild_id), "social_feeds", feeds)

    @poll_feeds.before_loop
    async def before_poll_feeds(self):
        await self.bot.wait_until_ready()

    @commands.command(name="voicelink")
    async def voicelink(self, ctx, voice: discord.VoiceChannel = None, text: discord.TextChannel = None):
        links = await database.get_setting(ctx.guild.id, "voice_text_links", {})
        if voice is None:
            listing = "\n".join(f"<#{voice_id}> → <#{text_id}>" for voice_id, text_id in links.items()) or "No voice/text links configured."
            return await ctx.reply(f"**Voice text links**\n{listing}\nUse `?voicelink #voice #text` to add one.", mention_author=False)
        if text is None:
            return await ctx.reply("Provide a voice channel and its text channel: `?voicelink #voice #text`.", mention_author=False)
        links[str(voice.id)] = text.id
        await database.set_setting(ctx.guild.id, "voice_text_links", links)
        await ctx.reply(f"✅ Linked {voice.mention} to {text.mention}. Members in voice will get access to that text channel.", mention_author=False)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        links = await database.get_setting(member.guild.id, "voice_text_links", {})
        changed_ids = {str(c.id) for c in (before.channel, after.channel) if c and str(c.id) in links}
        for voice_id in changed_ids:
            text = member.guild.get_channel(int(links[voice_id]))
            voice = member.guild.get_channel(int(voice_id))
            if not text or not voice: continue
            users = [m for m in voice.members if not m.bot]
            if member in users:
                try: await text.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True, reason="Voice text link")
                except discord.HTTPException: pass
            elif before.channel and str(before.channel.id) == voice_id:
                try: await text.set_permissions(member, overwrite=None, reason="Left linked voice channel")
                except discord.HTTPException: pass


async def setup(bot):
    await bot.add_cog(Feeds(bot))
