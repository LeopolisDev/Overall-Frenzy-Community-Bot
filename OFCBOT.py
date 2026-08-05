import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta
import re, json, os

TOKEN = "MY_BOT_TOKEN"

intents = discord.Intents.default()
intents.members = True
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

@bot.tree.command(description="Remove a member's timeout.")
@app_commands.check(is_moderator)
async def unmute(interaction:discord.Interaction, member:discord.Member):
    await member.timeout(None)
    await interaction.response.send_message(f"Unmuted {member.mention}")

@bot.tree.command(description="Add a warning to a member.")
@app_commands.check(is_head_moderator)
async def warn(interaction:discord.Interaction, member:discord.Member, reason:str):
    k=str(member.id)
    warnings.setdefault(k,[]).append(reason)
    save()
    await interaction.response.send_message(f"Warned {member.mention}: {reason}")

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

@bot.tree.command(name="warnlist", description="Show all warnings for a member.")
@app_commands.check(is_head_moderator)
async def warnlist(interaction:discord.Interaction, member:discord.Member):
    lst=warnings.get(str(member.id),[])
    if not lst:
        await interaction.response.send_message("No warnings.")
        return
    total=len(lst)
    await interaction.response.send_message("\n".join(f"{i+1}/{total}. {w}" for i,w in enumerate(lst)))

@bot.tree.command(description="Kick a member from the server.")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction:discord.Interaction, member:discord.Member, reason:str="No reason"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"Kicked {member.mention}")

@bot.tree.command(description="Ban a member from the server.")
@app_commands.check(is_head_admin)
async def ban(interaction:discord.Interaction, member:discord.Member, reason:str="No reason"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"Banned {member.mention}")

@bot.tree.command(description="Unban a user by ID.")
@app_commands.check(is_head_admin)
async def unban(interaction:discord.Interaction, user_id:str):
    user=await bot.fetch_user(int(user_id))
    await interaction.guild.unban(user)
    await interaction.response.send_message(f"Unbanned {user}")

bot.run(TOKEN)
