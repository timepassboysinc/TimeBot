# Time Bot module coverage

Time Bot is a new, independent bot with Dyno-style features. It is not a copy of Dyno, does not use Dyno's code, and does not claim exact command parity. This table describes the commands present in this starter implementation.

| Module | Coverage | Notes |
|---|---|---|
| AFK | Basic | `?afk`; removes status when the user speaks and replies to mentions. |
| Action Log | Partial | Join/leave, message delete/edit, and moderation logs. |
| Announcements | Basic | `?announce` posts a message to a chosen channel. |
| Auto Delete | Basic | Link auto-delete toggle. |
| Auto Message | Basic | Repeating scheduled message. |
| Auto Purge | Basic | Scheduled age-based cleanup. |
| Autoban | Basic | Blocks new joins from accounts younger than a configured age. |
| Automod | Basic | Word, link, and caps rules. |
| Autoresponder | Basic | Text-trigger replies. |
| Autoroles | Basic | Assign one configured role on join. |
| Custom Commands | Basic | Text response commands configured by managers. |
| Forms | Basic | One-question modal routed to a configured channel. |
| Giveaways | Core tools | `/giveaway` and `?giveaway`: create timed draws, first-come drops, edit, restore entry button, list, end, reroll, and delete. |
| Highlights | Basic | User keyword alerts by DM. |
| Invite tracking | Basic | Tracked invite joins and leaderboard; requires Manage Server permission. |
| Levels | Basic | Message XP, message count, level display, and leaderboard. Tracking starts when the bot is added. |
| Message Embedder | Basic | Title/description embed publisher. |
| Custom Panels | Basic | `?panel #channel Title | Message` posts a custom text panel; `?embed` remains an alias. |
| Moderation | Partial | Ban, kick, timeout, warn, notes, cases, purge, lock, slowmode, role/nickname, voice moderation. |
| Reaction Roles | Basic | One role per reaction mapping. |
| Reddit | Basic | Public subreddit new-post feed polling. |
| Reminders | Basic | Persistent reminders delivered by DM or channel fallback. |
| Slowmode | Basic | Channel slowmode setting. |
| Starboard | Basic | ⭐ threshold post/update. |
| Tags | Basic | Manager-created reusable text responses. |
| Tickets | Basic | Private ticket creation, staff role, and transcript on close. |
| TikTok | Not included | No stable, supported feed implementation is included. |
| Twitch | Credential-dependent | Live stream notices require `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`. |
| YouTube | Basic | Public channel RSS feed polling; no API key needed. |
| Voice Text Linking | Basic | Grant linked text channel access while a member is in voice. |

This is a substantial starter feature set, not a finished, drop-in replacement for every Dyno module or every Dyno command. Feed polling and moderation permissions should be configured and checked in a private test server before broad use.

Server configuration and moderation commands use the per-server role policy in `role_access.json`. Time Bot itself needs the corresponding Discord permissions to perform actions.
