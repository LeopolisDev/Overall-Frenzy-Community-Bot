import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta

TOKEN = "MY_BOT_TOKEN"
ADMIN_ROLE_ID = 1522941950519672833
TARGET_USER_ID = 1076540096024678461

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(intents=intents, command_prefix="!")


async def has_admin_role(interaction: discord.Interaction):
    if interaction.guild is None:
        return False
    member = interaction.guild.get_member(interaction.user.id)
    if member is None:
        try:
            member = await interaction.guild.fetch_member(interaction.user.id)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return False
    return any(role.id == ADMIN_ROLE_ID for role in member.roles)


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


@bot.tree.command(description="Mute the fixed user for 1 to 10 minutes.")
@app_commands.check(has_admin_role)
async def mute(interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 10]):
    member = interaction.guild.get_member(TARGET_USER_ID) if interaction.guild else None
    if member is None and interaction.guild is not None:
        try:
            member = await interaction.guild.fetch_member(TARGET_USER_ID)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            member = None

    if member is None:
        await interaction.response.send_message("Target user was not found in this server.", ephemeral=True)
        return

    duration = timedelta(minutes=minutes)
    await member.timeout(duration, reason=f"Muted for {minutes} minute(s) by {interaction.user}")
    await interaction.response.send_message(f"Muted {member.mention} for {minutes} minute(s).")


bot.run(TOKEN)
