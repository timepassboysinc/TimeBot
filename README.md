# Time Bot

A separate Discord bot project for Dyno-style server tools. It does not modify or share runtime state with TimeAutoMM.

## Setup

The bot is restricted to the comma-separated server IDs in `ALLOWED_GUILD_IDS` and automatically leaves any other server, including servers it was already in at startup. The older single-server setting `ALLOWED_GUILD_ID` remains supported as a fallback.

1. Create a new application and bot in the Discord Developer Portal.
2. Enable **Message Content Intent** and **Server Members Intent** for the bot.
3. Copy `.env.example` to `.env` and put the new bot token in `DISCORD_TOKEN`. Never post that token in chat.
4. On macOS, double-click **Start Time Bot.command**. You do not need to type `python main.py`. The first run creates and opens `.env` in TextEdit so you can paste the token after `DISCORD_TOKEN=`, save, and double-click the launcher again. It installs packages only on the first launch (or after dependencies change); later starts go straight to the bot.
5. Invite it with the OAuth scopes **bot** and **applications.commands**, plus permissions needed by the modules you enable. Invite tracking specifically needs **Manage Server**. Keep Time Bot's role below owner/admin roles.

The command prefix is `?`. Run `?help` for the interactive command guide. To post a custom panel, use `?panel #channel Title | Your message` (or `?panel #channel Your message` for a text-only panel). A full-access Time Bot role is required; Time Bot needs permission to send messages in the target channel. `?embed` is an alias.

### Logs

Use `?logchannel <type> #channel` to route logs to separate channels. Supported types are `ban`, `warn`, `timeout`, `join`, `leave`, `invite`, `server`, and `moderation`. Example: `?logchannel ban #ban-logs`. Run `?logchannels` to see current destinations; use `?logchannel ban off` to clear one. A full-access Time Bot role is required to change these settings. Ban, warn, timeout, and moderation events created by Time Bot are logged; join/leave and invite events are tracked; server logs include channel, role, server-setting, and deleted/edited message events. Manual Discord bans, kicks, and timeouts include the actor/reason when Time Bot has **View Audit Log**. Invite-use detection needs **Manage Server**. Give the bot **View Channel**, **Send Messages**, and **Embed Links** in each log channel.

Giveaway controls are available as both slash and prefix commands under `/giveaway` or `?giveaway`: create a timed giveaway, start a first-come drop with clickable buttons, edit, restore its button, end, reroll, delete, and list. Examples: `?giveaway create 1h 2 Nitro` and `?giveaway drop 2 Nitro`. Participants enter or claim a spot using the button on the giveaway post. Slash commands can take a short time to appear after inviting the bot or syncing. Server settings are stored in SQLite at `data/blueguard.sqlite3`.

Server setup, role assignment, and moderation commands are gated by the per-server Time Bot roles in `role_access.json`. Give the corresponding Discord permissions to Time Bot itself so it can carry out the approved actions.

### Role-based command access

Privileged Time Bot commands also use `role_access.json`. Configure each approved server under `guilds`, then list each role ID and the bot command groups that role can use. See `role_access.json.example` for the shape. Supported groups are `kick`, `timeout`, `warn`, and `all`. A role with `all` can use every privileged bot command, including ban, server setup, and role-management commands. For a server that should be controlled only by owners/co-owners, give only their role IDs `all`. Add your Discord user ID to `role_admin_user_ids` so only you can assign/remove access-control roles through Time Bot. Access roles can't be assigned with reaction roles or autorole. A server with an incomplete or missing policy denies privileged commands until it is configured. Public utility commands remain available.

The access policy decides which person may run a bot command; Time Bot still needs the matching Discord permissions itself (Kick Members, Ban Members, Moderate Members, Manage Roles, View Audit Log, Manage Server for invite tracking, and any channel permissions used by the enabled commands). People using Time Bot commands do not also need those Discord permission bits.

These checks are enforced by Time Bot even when a person has Discord Administrator or owns the server. They govern Time Bot commands only: Discord server owners retain Discord's native powers, including assigning roles and using Discord's own kick/ban controls. Keep the full-access roles private and avoid giving their roles to people who should not have bot admin access.

## Modules

Time Bot is an independent implementation inspired by common moderation-bot features. It does not use Dyno's private code or branding. The interactive `?help` menu lists the commands currently loaded. See `MODULES.md` for coverage and feed credentials. Some modules are partial and it is not a complete Dyno replacement.

### Optional social-feed credentials

Add `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` to `.env` only if you want Twitch live notifications. YouTube RSS and public Reddit feeds do not need credentials. Keep `.env` private.

### AI chat command

Add an OpenAI API key as `OPENAI_API_KEY` in `.env` to enable `?ai <question>` (also `?ask <question>`). The command uses the OpenAI API and may incur API usage charges. `OPENAI_MODEL` defaults to `gpt-6-luna`; change it to another model available to your API project if desired. Keep the API key private. Example: `?ai explain black holes simply`.

To change the name Discord displays for the bot itself, rename the bot application in the Discord Developer Portal (or set a server nickname). The source code controls Time Bot’s help panel, embeds, and presence text.


## Added commands

- `?snipe` shows the latest deleted message in the current channel. `?clearsnipe` clears it (full-access Time Bot role required).
- `?timer 1m xyz` pings you in the current channel after one minute with the reminder text. Timers last only while the bot process is running.
- `?choose 1` opens a one-minute draw with an entry button and selects one winner when time is up.
