import os

import aiohttp
import discord
from discord.ext import commands

from cogs.core import BLUE


class AI(commands.Cog):
    """Answer general questions through the OpenAI API."""

    def __init__(self, bot):
        self.bot = bot
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("OPENAI_MODEL", "gpt-6-luna").strip() or "gpt-6-luna"

    @commands.command(name="ai", aliases=["ask"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def ask_ai(self, ctx, *, question: str):
        """Ask an AI assistant a question. Usage: ?ai <question>"""
        if not self.api_key:
            return await ctx.reply(
                "AI chat isn’t set up yet. Add `OPENAI_API_KEY` to the bot’s `.env` file, save it, and restart Time Bot.",
                mention_author=False,
            )

        question = question.strip()
        if not question:
            return await ctx.reply("Ask me something, for example: `?ai explain black holes simply`.", mention_author=False)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "instructions": "You are Time Bot's helpful assistant. Answer clearly and accurately. If you are unsure, say so. Keep the answer suitable for a Discord chat.",
            "input": question[:6000],
            "max_output_tokens": 700,
        }

        try:
            timeout = aiohttp.ClientTimeout(total=45)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    "https://api.openai.com/v1/responses", headers=headers, json=payload
                ) as response:
                    if response.status == 401:
                        return await ctx.reply("The AI API key was rejected. Check `OPENAI_API_KEY` in `.env`.", mention_author=False)
                    if response.status == 429:
                        return await ctx.reply("The AI service is rate limited or the API account has no available quota. Try again later or check its billing limits.", mention_author=False)
                    if response.status >= 400:
                        body = await response.json(content_type=None)
                        detail = body.get("error", {}).get("message", "The AI request failed.")
                        return await ctx.reply(f"AI request failed: {str(detail)[:300]}", mention_author=False)
                    data = await response.json()
        except (aiohttp.ClientError, TimeoutError) as exc:
            return await ctx.reply(f"I couldn’t reach the AI service ({type(exc).__name__}). Try again in a moment.", mention_author=False)

        answer = "\n".join(
            block.get("text", "")
            for item in data.get("output", [])
            for block in item.get("content", [])
            if block.get("type") == "output_text" and block.get("text")
        ).strip()
        if not answer:
            return await ctx.reply("The AI service returned no text. Try asking in a different way.", mention_author=False)

        embed = discord.Embed(title="✨ Time Bot AI", description=answer[:4000], color=BLUE)
        embed.set_footer(text=f"Model: {self.model}  •  Use ?ai <question> to ask another")
        await ctx.reply(embed=embed, mention_author=False, allowed_mentions=discord.AllowedMentions.none())

    @ask_ai.error
    async def ask_ai_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            return await ctx.reply("Ask me something, for example: `?ai explain black holes simply`.", mention_author=False)
        if isinstance(error, commands.CommandOnCooldown):
            return await ctx.reply(f"Give me a moment — try again in {error.retry_after:.1f}s.", mention_author=False)
        raise error


async def setup(bot):
    await bot.add_cog(AI(bot))
