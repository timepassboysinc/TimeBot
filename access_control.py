"""Role-based gates for Time Bot's privileged commands.

The role table is stored in role_access.json so Discord server permissions such
as Administrator and server ownership cannot bypass these bot-command gates.
"""

import json
from pathlib import Path

ROOT = Path(__file__).parent
POLICY_FILE = ROOT / "role_access.json"

# Only commands with bot-side privileges are gated. Public utility commands
# remain public. The "all" permission is required for bans, setup, role edits,
# and every other administrative command.
COMMAND_ACCESS_GROUPS = {
    "kick": "kick",
    "timeout": "timeout",
    "untimeout": "timeout",
    "warn": "warn",
    "warnings": "warn",
    "clearwarnings": "warn",
    "note": "warn",
    "notes": "warn",
    "modlogs": "warn",
    "case": "warn",
    "ban": "all",
    "unban": "all",
    "softban": "all",
    "autoban": "all",
    "setlog": "all",
    "logchannel": "all",
    "logchannels": "all",
    "config": "all",
    "purge": "all",
    "lock": "all",
    "unlock": "all",
    "slowmode": "all",
    "deafen": "all",
    "undeafen": "all",
    "role": "all",
    "addrole": "all",
    "removerole": "all",
    "nick": "all",
    "setactionlog": "all",
    "setwelcome": "all",
    "welcometext": "all",
    "setleave": "all",
    "leavetext": "all",
    "setautorole": "all",
    "autorole": "all",
    "automod": "all",
    "autodelete": "all",
    "autoresponse": "all",
    "custom": "all",
    "automessage": "all",
    "autopurge": "all",
    "feed": "all",
    "voicelink": "all",
    "clearinvites": "all",
    "clearsnipe": "all",
    "ticketpanel": "all",
    "tickets": "all",
    "setform": "all",
    "starboard": "all",
    "giveaway": "all",
    "giveaway create": "all",
    "giveaway drop": "all",
    "giveaway edit": "all",
    "giveaway fix": "all",
    "giveaway end": "all",
    "giveaway reroll": "all",
    "giveaway delete": "all",
    "reactionrole": "all",
    "panel": "all",
    "announce": "all",
}


def _load_policy():
    try:
        with POLICY_FILE.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def member_has_permission(ctx, required):
    """Check the configured role grants for a privileged command/action."""
    return member_has_guild_permission(ctx.guild, ctx.author, required)


def _guild_policy(guild_id):
    return _load_policy().get("guilds", {}).get(str(guild_id))


def member_has_guild_permission(guild, member, required):
    if guild is None:
        return False
    guild_policy = _guild_policy(guild.id)
    if not isinstance(guild_policy, dict):
        return False

    role_permissions = guild_policy.get("roles", {})
    member_role_ids = {str(role.id) for role in getattr(member, "roles", [])}
    granted = set()
    for role_id in member_role_ids:
        permissions = role_permissions.get(role_id, [])
        if isinstance(permissions, list):
            granted.update(str(permission).lower() for permission in permissions)

    if "all" in granted or required in granted:
        return True

    return False


def is_access_role(guild_id, role_id):
    guild_policy = _guild_policy(guild_id)
    roles = guild_policy.get("roles", {}) if isinstance(guild_policy, dict) else {}
    return str(role_id) in roles


def can_manage_access_roles(guild_id, user_id):
    guild_policy = _guild_policy(guild_id)
    if not isinstance(guild_policy, dict):
        return False
    return str(user_id) in {str(value) for value in guild_policy.get("role_admin_user_ids", [])}


def check_command_access(guild, member, command_name):
    """Return (allowed, explanation) for a command in either command surface."""
    if guild is None or not command_name:
        return True, ""

    command_name = command_name.lower()
    required = COMMAND_ACCESS_GROUPS.get(command_name)
    if required is None:
        required = COMMAND_ACCESS_GROUPS.get(command_name.rsplit(" ", 1)[-1])
    if required is None:
        return True, ""

    if member_has_guild_permission(guild, member, required):
        return True, ""

    label = {
        "kick": "kick access",
        "timeout": "timeout access",
        "warn": "warning access",
        "all": "a full-access role",
    }.get(required, "the required access role")
    return False, f"You need {label} for this Time Bot command. Server Administrator and owner status do not bypass this bot role rule."


def check_command(ctx):
    """Return (allowed, explanation) for a prefix command context."""
    command_name = ctx.command.qualified_name if ctx.command is not None else ""
    return check_command_access(ctx.guild, ctx.author, command_name)


def check_interaction(interaction):
    """Return (allowed, explanation) for a slash command interaction."""
    command_name = interaction.command.qualified_name if interaction.command is not None else ""
    return check_command_access(interaction.guild, interaction.user, command_name)
