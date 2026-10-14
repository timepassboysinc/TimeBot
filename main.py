import asyncio
import os
from aiohttp import web

async def start_web():
    app = web.Application()

    async def health(request):
        connected = bot.is_ready()
        username = str(bot.user) if bot.user else "not logged in"
        return web.json_response({
            "service": "running",
            "discord_connected": connected,
            "bot_user": username,
        })

    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 10000)))
    await site.start()

import json
import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

import access_control
from database import init_db

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
with open(ROOT / "config.json", encoding="utf-8") as f:
    CONFIG = json.load(f)


def prefix_for_bot(bot, message):
    return commands.when_mentioned_or(CONFIG.get("prefix", "?"))(bot, message)


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True
intents.reactions = True


class RoleAccessTree(discord.app_commands.CommandTree):
    async def interaction_check(self, interaction):
        allowed, message = access_control.check_interaction(interaction)
        if not allowed:
            await interaction.response.send_message(message, ephemeral=True)
        return allowed


bot = commands.Bot(command_prefix=prefix_for_bot, intents=intents, help_command=None, tree_cls=RoleAccessTree)
bot.config = CONFIG


def allowed_guild_ids():
    raw = os.getenv("ALLOWED_GUILD_IDS", "").strip()
    if not raw:
        raw = os.getenv("ALLOWED_GUILD_ID", "").strip()
    if not raw:
        raise RuntimeError("Set ALLOWED_GUILD_IDS in .env to the comma-separated server IDs Time Bot may join.")
    try:
        guild_ids = {int(value.strip()) for value in raw.split(",") if value.strip()}
    except (TypeError, ValueError):
        raise RuntimeError("ALLOWED_GUILD_IDS must contain comma-separated numeric server IDs.")
    if not guild_ids or any(guild_id <= 0 for guild_id in guild_ids):
        raise RuntimeError("ALLOWED_GUILD_IDS must contain positive Discord server IDs.")
    return guild_ids


async def leave_unapproved_guilds():
    allowed_ids = allowed_guild_ids()
    for guild in list(bot.guilds):
        if guild.id not in allowed_ids:
            print(f"Leaving unauthorized server: {guild.name} ({guild.id})")
            await guild.leave()


@bot.event
async def on_guild_join(guild):
    if guild.id not in allowed_guild_ids():
        print(f"Leaving unauthorized server: {guild.name} ({guild.id})")
        await guild.leave()


@bot.check
async def enforce_bot_role_access(ctx):
    allowed, message = access_control.check_command(ctx)
    if not allowed:
        await ctx.reply(message, mention_author=False)
    return allowed


@bot.event
async def on_message(message):
    # Log command names only; never include message text.
    if not message.author.bot:
        ctx = await bot.get_context(message)
        if ctx.valid and ctx.command:
            location = message.guild.id if message.guild else "DM"
            print(f"Received prefix command ?{ctx.command.qualified_name} in {location}")
    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, (commands.CommandNotFound, commands.CheckFailure)):
        return
    original = getattr(error, "original", error)
    command_name = ctx.command.qualified_name if ctx.command else "unknown"
    print(f"Command ?{command_name} failed: {type(original).__name__}: {original}")
    try:
        await ctx.reply("That command hit an error. The bot owner can check the Render logs for details.", mention_author=False)
    except discord.HTTPException:
        pass


@bot.event
async def on_ready():
    await leave_unapproved_guilds()
    print(f"Ready as {bot.user} • prefix {CONFIG.get('prefix', '?')}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="your server | ?help"))
    if not getattr(bot, "_commands_synced", False):
        try:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} slash command(s)")
            bot._commands_synced = True
        except discord.HTTPException as exc:
            print(f"Slash command sync failed: {exc}")


async def load_cogs():
    for file in sorted((ROOT / "cogs").glob("*.py")):
        if file.name.startswith("_"):
            continue
        await bot.load_extension(f"cogs.{file.stem}")
        print(f"Loaded cog: {file.stem}")


async def main():
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "put_your_new_bot_token_here":
        raise RuntimeError("Set DISCORD_TOKEN in .env before starting Time Bot.")
    allowed_guild_ids()
    await init_db()
    await start_web()
    async with bot:
        await load_cogs()
        print("All cogs loaded; starting Discord gateway login.")
        # Cloudflare 1015 blocks can persist; avoid frequent login attempts.
        retry_delay = 1800
        while True:
            try:
                await bot.start(token)
                break
            except discord.HTTPException as exc:
                if exc.status != 429:
                    raise
                print(
                    "Discord login was rate-limited (HTTP 429). Keeping the Render "
                    f"service alive; retrying in {retry_delay} seconds."
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 21600)


if __name__ == "__main__":
    asyncio.run(main())
