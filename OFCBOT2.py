import discord
from discord import app_commands
from discord.ext import commands

TOKEN = "MY_BOT_TOKEN"
TARGET_USER_ID = 1419051314700226753

intents = discord.Intents.default()


class Bot(commands.Bot):
    async def setup_hook(self):
        await self.tree.sync()


bot = Bot(command_prefix="!", intents=intents)


@bot.tree.command(
    name="ping",
    description="Mention the configured user multiple times."
)
@app_commands.describe(amount="How many times to ping the user (1-100)")
async def ping(interaction: discord.Interaction, amount: int):

    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used in a server.",
            ephemeral=True,
        )
        return

    if amount < 1 or amount > 100:
        await interaction.response.send_message(
            "Amount must be between 1 and 100.",
            ephemeral=True,
        )
        return

    # Send the first ping as the initial interaction response
    await interaction.response.send_message(
        f"<@{TARGET_USER_ID}>",
        allowed_mentions=discord.AllowedMentions(users=True),
    )

    # Send the remaining pings as separate messages
    for _ in range(amount - 1):
        await interaction.followup.send(
            f"<@{TARGET_USER_ID}>",
            allowed_mentions=discord.AllowedMentions(users=True),
        )


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


bot.run(TOKEN)