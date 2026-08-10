import discord
import aiohttp
from discord import app_commands
from discord.ext import commands
from datetime import timedelta
from collections import defaultdict, deque
import time
import re, json, os

TOKEN = "MY_BOT_TOKEN"
LOG_WEBHOOK_URL = "https://discord.com/api/webhooks/1535194115459911700/9GLQXqSDt_kfWgjh4S2w-a2EzFJ3vvMNP0ZiUFAEEkxsULzpVYHun6DJZ8C1WsEhdY_-"

intents = discord.Intents.default()
intents.members = True

log_webhook_session = None
log_webhook = None


class Bot(commands.Bot):
    async def setup_hook(self):
        global log_webhook_session, log_webhook
        log_webhook_session = aiohttp.ClientSession()
        log_webhook = discord.Webhook.from_url(LOG_WEBHOOK_URL, session=log_webhook_session)

    async def close(self):
        global log_webhook_session
        await super().close()
        if log_webhook_session is not None and not log_webhook_session.closed:
            await log_webhook_session.close()


bot = Bot(intents=intents, command_prefix="!")

WARN_FILE="warnings.json"
warnings={}
if os.path.exists(WARN_FILE):
    with open(WARN_FILE,"r") as f:
        warnings=json.load(f)
def save():
    with open(WARN_FILE,"w") as f: json.dump(warnings,f,indent=2)

MODERATOR_ROLE_ID = 1522941925819416688
HEAD_MODERATOR_ROLE_ID = 1522941922371436707
HEAD_ADMIN_ROLE_ID = 1522941920740118669
ADMIN_ROLE_ID = 1522941921717391411
OWNER_ROLE_ID = 1528793993712894003
TEMP_MESSAGE_DELETE_AFTER = 10
MOD_ACTION_WINDOW_SECONDS = 10 * 60
MOD_ACTION_LIMIT = 3
moderation_actions = defaultdict(deque)

async def has_role(interaction: discord.Interaction, role_id: int):
    if interaction.guild is None:
        return False
    member = interaction.guild.get_member(interaction.user.id)
    if member is None:
        try:
            member = await interaction.guild.fetch_member(interaction.user.id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return False
    return any(role.id == role_id for role in member.roles)

async def is_moderator(interaction: discord.Interaction):
    return await has_role(interaction, MODERATOR_ROLE_ID)

async def is_head_moderator(interaction: discord.Interaction):
    return await has_role(interaction, HEAD_MODERATOR_ROLE_ID)

async def is_head_admin(interaction: discord.Interaction):
    return await has_role(interaction, HEAD_ADMIN_ROLE_ID)

async def is_admin(interaction: discord.Interaction):
    return await has_role(interaction, ADMIN_ROLE_ID)

async def is_owner(interaction: discord.Interaction):
    return await has_role(interaction, OWNER_ROLE_ID)

async def log_action(interaction: discord.Interaction, message: str):
    if interaction.guild is None or log_webhook is None:
        return
    embed = discord.Embed(description=message, color=discord.Color.red())
    await log_webhook.send(embed=embed, username="OFC Bot Logs")

async def record_moderation_action(interaction: discord.Interaction, action: str):
    if interaction.guild is None:
        return False

    actor_id = interaction.user.id
    now = time.monotonic()
    action_times = moderation_actions[actor_id]

    while action_times and now - action_times[0] > MOD_ACTION_WINDOW_SECONDS:
        action_times.popleft()

    action_times.append(now)

    if len(action_times) > MOD_ACTION_LIMIT:
        actor = interaction.guild.get_member(actor_id)
        if actor is None:
            try:
                actor = await interaction.guild.fetch_member(actor_id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                moderation_actions.pop(actor_id, None)
                return False

        try:
            await interaction.guild.ban(actor, reason=f"Exceeded moderation limit: {action}")
        except (discord.Forbidden, discord.HTTPException):
            return False

        moderation_actions.pop(actor_id, None)
        await log_action(
            interaction,
            f"AUTO-BAN | {actor} was banned for exceeding {MOD_ACTION_LIMIT} kick/ban actions in {MOD_ACTION_WINDOW_SECONDS // 60} minutes."
        )
        return True

    return False

def parse_duration(s):
    m=re.fullmatch(r"(\d+)([smhd])",s.lower().strip())
    if not m: return None
    n,u=int(m.group(1)),m.group(2)
    td={"s":timedelta(seconds=n),"m":timedelta(minutes=n),"h":timedelta(hours=n),"d":timedelta(days=n)}[u]
    return td if td<=timedelta(days=14) else None

def _extract_id(value: str):
    value = value.strip()
    mention_match = re.fullmatch(r"<@!?(\d+)>", value) or re.fullmatch(r"<#(\d+)>", value)
    if mention_match:
        return int(mention_match.group(1))
    if value.isdigit():
        return int(value)
    return None

def _all_message_channels(guild: discord.Guild):
    channels = list(guild.text_channels)
    channels.extend(getattr(guild, "threads", []))
    return sorted(
        channels,
        key=lambda channel: ((channel.last_message_id or 0), getattr(channel, "position", 0)),
        reverse=True
    )

async def resolve_target_user_id(guild: discord.Guild, user_ref: str):
    user_id = _extract_id(user_ref)
    if user_id is not None:
        member = guild.get_member(user_id)
        if member is not None:
            return user_id, str(member)
        return user_id, f"User ID {user_id}"

    lowered = user_ref.casefold().strip()
    for member in guild.members:
        if (
            member.name.casefold() == lowered
            or member.display_name.casefold() == lowered
            or str(member).casefold() == lowered
        ):
            return member.id, str(member)

    return None, None

async def resolve_channel_scope(guild: discord.Guild, channel_ref: str):
    if channel_ref.strip().casefold() == "all":
        return "all", None

    channel_id = _extract_id(channel_ref)
    channels = _all_message_channels(guild)
    if channel_id is not None:
        for channel in channels:
            if channel.id == channel_id:
                return channel, None

    lowered = channel_ref.strip().casefold()
    for channel in channels:
        if channel.name.casefold() == lowered:
            return channel, None

    return None, None

async def collect_purge_targets(guild: discord.Guild, target_user_id: int, channel_scope, amount: int):
    collected = []
    skipped_channels = 0
    channels = _all_message_channels(guild) if channel_scope == "all" else [channel_scope]

    for channel in channels:
        try:
            async for message in channel.history(limit=None, oldest_first=False):
                if message.author.id == target_user_id:
                    collected.append(message)
                    if len(collected) >= amount:
                        return collected, skipped_channels
        except (discord.Forbidden, discord.HTTPException):
            if channel_scope == "all":
                skipped_channels += 1
                continue
            raise

    return collected, skipped_channels

async def delete_purge_messages(messages):
    deleted = 0
    recent_cutoff = discord.utils.utcnow() - timedelta(days=14)
    by_channel = defaultdict(list)

    for message in messages:
        by_channel[message.channel].append(message)

    for channel, channel_messages in by_channel.items():
        recent_messages = [message for message in channel_messages if message.created_at >= recent_cutoff]
        old_messages = [message for message in channel_messages if message.created_at < recent_cutoff]

        for start in range(0, len(recent_messages), 100):
            batch = recent_messages[start:start + 100]
            if not batch:
                continue
            try:
                await channel.delete_messages(batch)
                deleted += len(batch)
            except (discord.Forbidden, discord.HTTPException):
                for message in batch:
                    try:
                        await message.delete()
                        deleted += 1
                    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                        pass

        for message in old_messages:
            try:
                await message.delete()
                deleted += 1
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass

    return deleted

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        if interaction.response.is_done():
            await interaction.followup.send(
                "You do not have permission to use this command.",
                delete_after=TEMP_MESSAGE_DELETE_AFTER
            )
        else:
            await interaction.response.send_message(
                "You do not have permission to use this command.",
                delete_after=TEMP_MESSAGE_DELETE_AFTER
            )
        return
    raise error

@bot.tree.command(description="Timeout a member for a set duration.")
@app_commands.check(is_moderator)
async def mute(interaction:discord.Interaction, member:discord.Member, duration:str, reason:str="No reason provided"):
    td=parse_duration(duration)
    if not td:
        await interaction.response.send_message(
            "Invalid duration. Use for example 1s,1m,1h,1d (max 14d).",
            delete_after=TEMP_MESSAGE_DELETE_AFTER
        ); return
    await member.timeout(td,reason=reason)
    await interaction.response.send_message(
        f"Muted {member.mention} for {duration}. Reason: {reason}",
        delete_after=TEMP_MESSAGE_DELETE_AFTER
    )
    await log_action(interaction, f"MUTE | {interaction.user} -> {member} | Duration: {duration} | Reason: {reason}")

@bot.tree.command(description="Remove a member's timeout.")
@app_commands.check(is_moderator)
async def unmute(interaction:discord.Interaction, member:discord.Member):
    await member.timeout(None)
    await interaction.response.send_message(
        f"Unmuted {member.mention}",
        delete_after=TEMP_MESSAGE_DELETE_AFTER
    )
    await log_action(interaction, f"UNMUTE | {interaction.user} -> {member}")

@bot.tree.command(description="Add a warning to a member.")
@app_commands.check(is_head_moderator)
async def warn(interaction:discord.Interaction, member:discord.Member, reason:str):
    k=str(member.id)
    warnings.setdefault(k,[]).append(reason)
    save()
    await interaction.response.send_message(
        f"Warned {member.mention}: {reason}",
        delete_after=TEMP_MESSAGE_DELETE_AFTER
    )
    await log_action(interaction, f"WARN | {interaction.user} -> {member} | Reason: {reason}")

@bot.tree.command(description="Remove a specific warning from a member.")
@app_commands.check(is_head_moderator)
async def unwarn(interaction:discord.Interaction, member:discord.Member, warning_number:int):
    k=str(member.id)
    if k not in warnings or not warnings[k]:
        await interaction.response.send_message("No warnings.", delete_after=TEMP_MESSAGE_DELETE_AFTER); return
    if warning_number < 1 or warning_number > len(warnings[k]):
        await interaction.response.send_message("Invalid warning number.", delete_after=TEMP_MESSAGE_DELETE_AFTER); return
    removed=warnings[k].pop(warning_number - 1)
    save()
    await interaction.response.send_message(
        f"Removed warning {warning_number}: {removed}",
        delete_after=TEMP_MESSAGE_DELETE_AFTER
    )
    await log_action(interaction, f"UNWARN | {interaction.user} -> {member} | Warning {warning_number}: {removed}")

@bot.tree.command(name="warnlist", description="Show all warnings for a member.")
@app_commands.check(is_head_moderator)
async def warnlist(interaction:discord.Interaction, member:discord.Member):
    lst=warnings.get(str(member.id),[])
    if not lst:
        await interaction.response.send_message("No warnings.", delete_after=TEMP_MESSAGE_DELETE_AFTER)
        return
    total=len(lst)
    await interaction.response.send_message(
        "\n".join(f"{i+1}/{total}. {w}" for i,w in enumerate(lst)),
        delete_after=TEMP_MESSAGE_DELETE_AFTER
    )
    await log_action(interaction, f"WARNLIST | {interaction.user} viewed warnings for {member}")

@bot.tree.command(description="Kick a member from the server.")
@app_commands.check(is_admin)
async def kick(interaction:discord.Interaction, member:discord.Member, reason:str="No reason"):
    await member.kick(reason=reason)
    await interaction.response.send_message(
        f"Kicked {member.mention}",
        delete_after=TEMP_MESSAGE_DELETE_AFTER
    )
    await log_action(interaction, f"KICK | {interaction.user} -> {member} | Reason: {reason}")
    await record_moderation_action(interaction, f"KICK | Target: {member} | Reason: {reason}")

@bot.tree.command(description="Ban a member from the server.")
@app_commands.check(is_admin)
async def ban(interaction:discord.Interaction, member:discord.Member, reason:str="No reason"):
    await member.ban(reason=reason)
    await interaction.response.send_message(
        f"Banned {member.mention}",
        delete_after=TEMP_MESSAGE_DELETE_AFTER
    )
    await log_action(interaction, f"BAN | {interaction.user} -> {member} | Reason: {reason}")
    await record_moderation_action(interaction, f"BAN | Target: {member} | Reason: {reason}")

@bot.tree.command(description="Unban a user by ID.")
@app_commands.check(is_admin)
async def unban(interaction:discord.Interaction, user_id:str):
    user=await bot.fetch_user(int(user_id))
    await interaction.guild.unban(user)
    await interaction.response.send_message(
        f"Unbanned {user}",
        delete_after=TEMP_MESSAGE_DELETE_AFTER
    )
    await log_action(interaction, f"UNBAN | {interaction.user} -> {user} (ID: {user_id})")

@bot.tree.command(description="Delete a user's messages in one channel or across all channels.")
@app_commands.check(is_owner)
async def purge(interaction: discord.Interaction, user: str, channel: str, amount: app_commands.Range[int, 1, 1000]):
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used in a server.",
            delete_after=TEMP_MESSAGE_DELETE_AFTER
        )
        return

    target_user_id, target_label = await resolve_target_user_id(interaction.guild, user)
    if target_user_id is None:
        await interaction.response.send_message(
            "I could not resolve that user. Use a member mention, username, or raw user ID.",
            delete_after=TEMP_MESSAGE_DELETE_AFTER
        )
        return

    channel_scope, _ = await resolve_channel_scope(interaction.guild, channel)
    if channel_scope is None:
        await interaction.response.send_message(
            "I could not resolve that channel. Use a channel mention, channel name, channel ID, or `all`.",
            delete_after=TEMP_MESSAGE_DELETE_AFTER
        )
        return

    await interaction.response.defer(thinking=True)

    try:
        messages, skipped_channels = await collect_purge_targets(interaction.guild, target_user_id, channel_scope, amount)
    except (discord.Forbidden, discord.HTTPException):
        scope_name = "that channel" if channel_scope != "all" else "one or more channels"
        await interaction.followup.send(
            f"I couldn't read messages in {scope_name}.",
            delete_after=TEMP_MESSAGE_DELETE_AFTER
        )
        return

    if not messages:
        scope_name = "all channels" if channel_scope == "all" else f"#{channel_scope.name}"
        await interaction.followup.send(
            f"I didn't find any messages from {target_label} in {scope_name}.",
            delete_after=TEMP_MESSAGE_DELETE_AFTER
        )
        return

    deleted_count = await delete_purge_messages(messages)
    scope_name = "all channels" if channel_scope == "all" else f"#{channel_scope.name}"
    skipped_note = f" Skipped {skipped_channels} channel(s) I couldn't read." if skipped_channels else ""

    await interaction.followup.send(
        f"Deleted {deleted_count} message(s) from {target_label} in {scope_name}.{skipped_note}",
        delete_after=TEMP_MESSAGE_DELETE_AFTER
    )
    await log_action(
        interaction,
        f"PURGE | {interaction.user} -> {target_label} | Scope: {scope_name} | Requested: {amount} | Deleted: {deleted_count}"
        + (f" | Skipped channels: {skipped_channels}" if skipped_channels else "")
    )

bot.run(TOKEN)
