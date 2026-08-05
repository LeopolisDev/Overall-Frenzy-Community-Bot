import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta
import re, json, os

TOKEN = "MTQ4MjAxNTI4MjUyNzQ3MzY3NA.GjfxC-.2goU03jkXoUm_bhhqTvgQEhloOrxVZr7OeC5m4"

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

@bot.tree.command()
@app_commands.checks.has_permissions(moderate_members=True)
async def mute(interaction:discord.Interaction, member:discord.Member, duration:str, reason:str="No reason provided"):
    td=parse_duration(duration)
    if not td:
        await interaction.response.send_message("Invalid duration. Use 30s,5m,2h,7d (max 14d).",ephemeral=True); return
    await member.timeout(td,reason=reason)
    await interaction.response.send_message(f"Muted {member.mention} for {duration}. Reason: {reason}")

@bot.tree.command()
@app_commands.checks.has_permissions(moderate_members=True)
async def unmute(interaction:discord.Interaction, member:discord.Member):
    await member.timeout(None)
    await interaction.response.send_message(f"Unmuted {member.mention}")

@bot.tree.command()
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction:discord.Interaction, member:discord.Member, reason:str):
    k=str(member.id)
    warnings.setdefault(k,[]).append(reason)
    save()
    await interaction.response.send_message(f"Warned {member.mention}: {reason}")

@bot.tree.command()
@app_commands.checks.has_permissions(moderate_members=True)
async def unwarn(interaction:discord.Interaction, member:discord.Member):
    k=str(member.id)
    if k not in warnings or not warnings[k]:
        await interaction.response.send_message("No warnings."); return
    removed=warnings[k].pop()
    save()
    await interaction.response.send_message(f"Removed warning: {removed}")

@bot.tree.command(name="warnlist")
@app_commands.checks.has_permissions(moderate_members=True)
async def warnlist(interaction:discord.Interaction, member:discord.Member):
    lst=warnings.get(str(member.id),[])
    await interaction.response.send_message("\n".join(f"{i+1}. {w}" for i,w in enumerate(lst)) if lst else "No warnings.")

@bot.tree.command()
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction:discord.Interaction, member:discord.Member, reason:str="No reason"):
    await member.kick(reason=reason)
    await interaction.response.send_message(f"Kicked {member.mention}")

@bot.tree.command()
@app_commands.checks.has_permissions(ban_members=True)
async def ban(interaction:discord.Interaction, member:discord.Member, reason:str="No reason"):
    await member.ban(reason=reason)
    await interaction.response.send_message(f"Banned {member.mention}")

@bot.tree.command()
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction:discord.Interaction, user_id:str):
    user=await bot.fetch_user(int(user_id))
    await interaction.guild.unban(user)
    await interaction.response.send_message(f"Unbanned {user}")

bot.run(TOKEN)