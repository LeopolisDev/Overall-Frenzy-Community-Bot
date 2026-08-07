import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta
from collections import defaultdict, deque
import time
import re, json, os

TOKEN = "MY_BOT_TOKEN"
JUMPY_MEDIA_URL = "https://images-ext-1.discordapp.net/external/4x2JsFTeRKzvt9EWH9YuAKlDLrJm1RoCAZPlzb0FCPQ/%3Fsize%3D4096/https/cdn.discordapp.com/avatars/1076540096024678461/40325a3d71d1818cb65921a157eafa6e.png?format=webp&quality=lossless"

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(intents=intents, command_prefix="!")

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
LOG_CHANNEL_ID = 1534575514432573470
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

async def log_action(interaction: discord.Interaction, message: str):
    if interaction.guild is None:
        return
    channel = interaction.guild.get_channel(LOG_CHANNEL_ID) or bot.get_channel(LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await interaction.guild.fetch_channel(LOG_CHANNEL_ID)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return
    await channel.send(message)

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

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if re.search(r"\bfurry\b", message.content, re.IGNORECASE):
        await message.channel.send(JUMPY_MEDIA_URL)

    await bot.process_commands(message)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        if interaction.response.is_done():
            await interaction.followup.send("You do not have permission to use this command.", ephemeral=True)
        else:
            await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    raise error

@bot.tree.command(description="Timeout a member for a set duration.")
@app_commands.check(is_moderator)
async def mute(interaction:discord.Interaction, member:discord.Member, duration:str, reason:str="No reason provided"):
    td=parse_duration(duration)
    if not td:
        await interaction.response.send_message("Invalid duration. Use for example 1s,1m,1h,1d (max 14d).",ephemeral=True); return
    await member.timeout(td,reason=reason)
    await interaction.response.send_message(f"Muted {member.mention} for {duration}. Reason: {reason}")
    await log_action(interaction, f"MUTE | {interaction.user} -> {member} | Duration: {duration} | Reason: {reason}")

@bot.tree.command(description="Remove a member's timeout.")
@app_commands.check(is_moderator)
async def unmute(interaction:discord.Interaction, member:discord.Member):
    await member.timeout(None)
    await interaction.response.send_message(f"Unmuted {member.mention}")
    await log_action(interaction, f"UNMUTE | {interaction.user} -> {member}")

@bot.tree.command(description="Add a warning to a member.")
@app_commands.check(is_head_moderator)
async def warn(interaction:discord.Interaction, member:discord.Member, reason:str):
    k=str(member.id)
    warnings.setdefault(k,[]).append(reason)
    save()
    await interaction.response.send_message(f"Warned {member.mention}: {reason}")
    await log_action(interaction, f"WARN | {interaction.user} -> {member} | Reason: {reason}")

@bot.tree.command(description="Remove a specific warning from a member.")
@app_commands.check(is_head_moderator)
async def unwarn(interaction:discord.Interaction, member:discord.Member, warning_number:int):
    k=str(member.id)
    if k not in warnings or not warnings[k]:
        await interaction.response.send_message("No warnings."); return
    if warning_number < 1 or warning_number > len(warnings[k]):
        await interaction.response.send_message("Invalid warning number."); return
    removed=warnings[k].pop(warning_number - 1)
    save()
    await interaction.response.send_message(f"Removed warning {warning_number}: {removed}")
    await log_action(interaction, f"UNWARN | {interaction.user} -> {member} | Warning {warning_number}: {removed}")

@bot.tree.command(name="warnlist", description="Show all warnings for a member.")
@app_commands.check(is_head_moderator)
async def warnlist(interaction:discord.Interaction, member:discord.Member):
    lst=warnings.get(str(member.id),[])
    if not lst:
        await interaction.response.send_message("No warnings.")
        return
    total=len(lst)
    await interaction.response.send_message("\n".join(f"{i+1}/{total}. {w}" for i,w in enumerate(lst)))
    await log_action(interaction, f"WARNLIST | {interaction.user} viewed warnings for {member}")

@bot.tree.command(description="Kick a member from the server.")
@app_commands.check(is_admin)
async def kick(interaction:discord.Interaction, member:discord.Member, reason:str="No reason"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"Kicked {member.mention}")
    await log_action(interaction, f"KICK | {interaction.user} -> {member} | Reason: {reason}")
    await record_moderation_action(interaction, f"KICK | Target: {member} | Reason: {reason}")

@bot.tree.command(description="Ban a member from the server.")
@app_commands.check(is_admin)
async def ban(interaction:discord.Interaction, member:discord.Member, reason:str="No reason"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"Banned {member.mention}")
    await log_action(interaction, f"BAN | {interaction.user} -> {member} | Reason: {reason}")
    await record_moderation_action(interaction, f"BAN | Target: {member} | Reason: {reason}")

@bot.tree.command(description="Unban a user by ID.")
@app_commands.check(is_admin)
async def unban(interaction:discord.Interaction, user_id:str):
    user=await bot.fetch_user(int(user_id))
    await interaction.guild.unban(user)
    await interaction.response.send_message(f"Unbanned {user}")
    await log_action(interaction, f"UNBAN | {interaction.user} -> {user} (ID: {user_id})")

bot.run(TOKEN)
