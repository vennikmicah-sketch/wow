import os
import json
import time
import discord
from discord import app_commands, ui
from discord.ext import commands
from pathlib import Path

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN environment variable is missing")

DATA_FILE = Path("data.json")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ── persistence ──────────────────────────────────────────────────────────────

def load_data() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "services": {},
        "settings": {},
        "cooldowns": {},
    }


def save_data(data: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


data = load_data()


# ── helpers ──────────────────────────────────────────────────────────────────

def get_stock(service: str) -> int:
    return len(data["services"].get(service.lower(), []))


def all_services() -> list[str]:
    return sorted(data["services"].keys())


def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator


# ── setup panel ──────────────────────────────────────────────────────────────

class SetupView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Set Gen Channel", style=discord.ButtonStyle.primary, custom_id="setup_channel")
    async def set_channel(self, interaction: discord.Interaction, button: ui.Button):
        if not is_admin(interaction):
            return await interaction.response.send_message("Admin only.", ephemeral=True)
        await interaction.response.send_modal(ChannelModal())

    @ui.button(label="Set Cooldown (sec)", style=discord.ButtonStyle.secondary, custom_id="setup_cooldown")
    async def set_cooldown(self, interaction: discord.Interaction, button: ui.Button):
        if not is_admin(interaction):
            return await interaction.response.send_message("Admin only.", ephemeral=True)
        await interaction.response.send_modal(CooldownModal())

    @ui.button(label="Add Service", style=discord.ButtonStyle.success, custom_id="setup_add_service")
    async def add_service(self, interaction: discord.Interaction, button: ui.Button):
        if not is_admin(interaction):
            return await interaction.response.send_message("Admin only.", ephemeral=True)
        await interaction.response.send_modal(AddServiceModal())

    @ui.button(label="Remove Service", style=discord.ButtonStyle.danger, custom_id="setup_remove_service")
    async def remove_service(self, interaction: discord.Interaction, button: ui.Button):
        if not is_admin(interaction):
            return await interaction.response.send_message("Admin only.", ephemeral=True)

        services = all_services()
        if not services:
            return await interaction.response.send_message("No services to remove.", ephemeral=True)

        options = [discord.SelectOption(label=s) for s in services[:25]]
        view = ui.View(timeout=60)
        select = ui.Select(placeholder="Choose service to remove", options=options)

        async def callback(inter: discord.Interaction):
            name = select.values[0]
            data["services"].pop(name, None)
            save_data(data)
            await inter.response.send_message(f"Removed service `{name}`.", ephemeral=True)

        select.callback = callback
        view.add_item(select)
        await interaction.response.send_message("Select service to remove:", view=view, ephemeral=True)


class ChannelModal(ui.Modal, title="Set Gen Channel"):
    channel_id = ui.TextInput(label="Channel ID", placeholder="Right-click channel → Copy ID", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            cid = int(self.channel_id.value.strip())
        except ValueError:
            return await interaction.response.send_message("Invalid channel ID.", ephemeral=True)

        gid = str(interaction.guild_id)
        if gid not in data["settings"]:
            data["settings"][gid] = {}
        data["settings"][gid]["channel_id"] = cid
        save_data(data)
        await interaction.response.send_message(f"Gen channel set to <#{cid}>", ephemeral=True)


class CooldownModal(ui.Modal, title="Set Cooldown"):
    seconds = ui.TextInput(label="Cooldown in seconds", placeholder="e.g. 60", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            sec = int(self.seconds.value.strip())
            if sec < 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("Must be a positive number.", ephemeral=True)

        gid = str(interaction.guild_id)
        if gid not in data["settings"]:
            data["settings"][gid] = {}
        data["settings"][gid]["cooldown"] = sec
        save_data(data)
        await interaction.response.send_message(f"Cooldown set to **{sec}s**", ephemeral=True)


class AddServiceModal(ui.Modal, title="Add Service"):
    name = ui.TextInput(label="Service name", placeholder="e.g. netflix, spotify", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        key = self.name.value.strip().lower()
        if key in data["services"]:
            return await interaction.response.send_message("Service already exists.", ephemeral=True)
        data["services"][key] = []
        save_data(data)
        await interaction.response.send_message(f"Service `{key}` created (empty stock).", ephemeral=True)


# ── gen panel ────────────────────────────────────────────────────────────────

class GenSelect(ui.Select):
    def __init__(self):
        services = all_services()
        options = []
        for s in services[:25]:
            stock = get_stock(s)
            options.append(discord.SelectOption(
                label=s.title(),
                description=f"Stock: {stock}",
                value=s
            ))
        if not options:
            options = [discord.SelectOption(label="No services", value="none")]
        super().__init__(placeholder="Choose a service to generate...", options=options, custom_id="gen_select")

    async def callback(self, interaction: discord.Interaction):
        service = self.values[0]
        if service == "none":
            return await interaction.response.send_message("No services configured.", ephemeral=True)

        gid = str(interaction.guild_id)
        settings = data["settings"].get(gid, {})
        channel_id = settings.get("channel_id")
        if channel_id and interaction.channel_id != channel_id:
            return await interaction.response.send_message(
                f"You can only gen in <#{channel_id}>", ephemeral=True
            )

        uid = str(interaction.user.id)
        cooldown = settings.get("cooldown", 30)
        now = time.time()
        last = data["cooldowns"].get(uid, 0)
        remaining = int(cooldown - (now - last))
        if remaining > 0:
            return await interaction.response.send_message(
                f"Cooldown active. Try again in **{remaining}s**.", ephemeral=True
            )

        stock = data["services"].get(service, [])
        if not stock:
            return await interaction.response.send_message(
                f"`{service}` is out of stock.", ephemeral=True
            )

        account = stock.pop(0)
        data["services"][service] = stock
        data["cooldowns"][uid] = now
        save_data(data)

        embed = discord.Embed(
            title=f"{service.title()} Account",
            description=f"```{account}```",
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Remaining stock: {len(stock)}")
        try:
            await interaction.user.send(embed=embed)
            await interaction.response.send_message(
                f"Sent **{service.title()}** account to your DMs. Stock left: **{len(stock)}**",
                ephemeral=True
            )
        except discord.Forbidden:
            stock.insert(0, account)
            data["services"][service] = stock
            save_data(data)
            await interaction.response.send_message(
                "Could not DM you. Open your DMs and try again.", ephemeral=True
            )


class GenView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(GenSelect())


# ── restock (text modal) ─────────────────────────────────────────────────────

class RestockModal(ui.Modal, title="Restock Service (Text)"):
    service = ui.TextInput(label="Service name", placeholder="netflix", required=True)
    accounts = ui.TextInput(
        label="Accounts (one per line)",
        style=discord.TextStyle.paragraph,
        placeholder="email:pass\nemail:pass",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            return await interaction.response.send_message("Admin only.", ephemeral=True)

        key = self.service.value.strip().lower()
        lines = [line.strip() for line in self.accounts.value.splitlines() if line.strip()]
        if not lines:
            return await interaction.response.send_message("No accounts provided.", ephemeral=True)

        if key not in data["services"]:
            data["services"][key] = []
        data["services"][key].extend(lines)
        save_data(data)
        await interaction.response.send_message(
            f"Restocked **{len(lines)}** into `{key}`. New stock: **{get_stock(key)}**",
            ephemeral=True
        )


# ── restock by file ──────────────────────────────────────────────────────────

class RestockFileModal(ui.Modal, title="Restock by File"):
    service = ui.TextInput(label="Service name", placeholder="netflix", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            return await interaction.response.send_message("Admin only.", ephemeral=True)

        key = self.service.value.strip().lower()
        await interaction.response.send_message(
            f"Now upload a `.txt` file for **`{key}`** in this channel.\n"
            "One account per line. I will only read the next file you send.",
            ephemeral=True
        )
        # store pending restock target for this user
        bot.pending_restock[interaction.user.id] = key


# ── commands ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="gensetup", description="Open the gen bot setup panel (admin only)")
async def gensetup(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("Admin only.", ephemeral=True)

    embed = discord.Embed(
        title="Gen Bot Setup",
        description=(
            "Configure the generator here.\n\n"
            "• **Set Gen Channel** – only allow gens in one channel\n"
            "• **Set Cooldown** – seconds between gens per user\n"
            "• **Add / Remove Service** – manage services\n\n"
            "Use `/restock` for text paste.\n"
            "Use `/restockfile` to add stock from a .txt file.\n"
            "Use `/genpanel` to post the public gen panel."
        ),
        color=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed, view=SetupView(), ephemeral=True)


@bot.tree.command(name="genpanel", description="Post the public generate panel (admin only)")
async def genpanel(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("Admin only.", ephemeral=True)

    services = all_services()
    if not services:
        return await interaction.response.send_message(
            "No services yet. Use `/gensetup` → Add Service first.", ephemeral=True
        )

    lines = [f"**{s.title()}** — `{get_stock(s)}` left" for s in services]
    embed = discord.Embed(
        title="Account Generator",
        description="Select a service below to generate an account.\n\n" + "\n".join(lines),
        color=discord.Color.green()
    )
    embed.set_footer(text="Accounts are sent to your DMs")
    await interaction.response.send_message(embed=embed, view=GenView())


@bot.tree.command(name="restock", description="Add accounts via text (admin only)")
async def restock(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("Admin only.", ephemeral=True)
    await interaction.response.send_modal(RestockModal())


@bot.tree.command(name="restockfile", description="Add stock from a .txt file (admin only)")
async def restockfile(interaction: discord.Interaction):
    if not is_admin(interaction):
        return await interaction.response.send_message("Admin only.", ephemeral=True)
    await interaction.response.send_modal(RestockFileModal())


@bot.tree.command(name="stock", description="Show current stock of all services")
async def stock(interaction: discord.Interaction):
    services = all_services()
    if not services:
        return await interaction.response.send_message("No services configured.", ephemeral=True)

    lines = [f"**{s.title()}** → `{get_stock(s)}`" for s in services]
    embed = discord.Embed(
        title="Current Stock",
        description="\n".join(lines),
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="ping", description="Check latency")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"Pong · {round(bot.latency * 1000)}ms", ephemeral=True
    )


# ── file upload listener ─────────────────────────────────────────────────────

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    # check if this user has a pending file restock
    pending = getattr(bot, "pending_restock", {})
    if message.author.id not in pending:
        return

    if not message.attachments:
        return

    attachment = message.attachments[0]
    if not attachment.filename.lower().endswith(".txt"):
        await message.reply("Only `.txt` files are accepted for restock.", delete_after=10)
        return

    key = pending.pop(message.author.id)
    try:
        content = await attachment.read()
        text = content.decode("utf-8", errors="ignore")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
    except Exception as e:
        await message.reply(f"Failed to read file: {e}", delete_after=10)
        return

    if not lines:
        await message.reply("File was empty.", delete_after=10)
        return

    if key not in data["services"]:
        data["services"][key] = []
    data["services"][key].extend(lines)
    save_data(data)

    await message.reply(
        f"Restocked **{len(lines)}** accounts into `{key}`.\n"
        f"New stock: **{get_stock(key)}**"
    )


# ── ready ────────────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    bot.pending_restock = {}
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s)")
    except Exception as e:
        print(f"Sync failed: {e}")

    bot.add_view(SetupView())
    bot.add_view(GenView())


if __name__ == "__main__":
    bot.run(TOKEN)
