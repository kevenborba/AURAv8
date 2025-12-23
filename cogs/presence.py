import discord
import sys
import os
import random
import asyncio
from discord.ext import commands, tasks
from discord import app_commands, ui

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


AUTHORIZED_ID = 216807300810276866

class Presence(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.presence_loop.start()

    def cog_unload(self):
        self.presence_loop.cancel()

    # ====================================================
    # 🖥️ COMANDO DO PAINEL
    # ====================================================
    @app_commands.command(name="painel_presence", description="Gerencia os status rotativos do bot")
    @app_commands.checks.has_permissions(administrator=True)
    async def panel_presence(self, interaction: discord.Interaction):
        if interaction.user.id != AUTHORIZED_ID:
            return await interaction.response.send_message("❌ Você não tem permissão para usar este painel.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        await self.send_panel(interaction)

    async def send_panel(self, interaction: discord.Interaction, is_edit=False):
        # 1. Pega dados do banco
        async with self.bot.db.execute("SELECT presence_interval, presence_state FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            config_data = await cursor.fetchone()
            
        # Valores padrão se não tiver config
        interval = config_data[0] if config_data else 60
        state = config_data[1] if config_data else "online"

        # 2. Pega as frases cadastradas
        async with self.bot.db.execute("SELECT id, activity_type, activity_text FROM presence") as cursor:
            activities = await cursor.fetchall()

        # 3. Monta o Embed
        embed = discord.Embed(title="🎭 Gerenciador de Persona", color=config.EMBED_COLOR)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        status_emoji = {
            "online": "🟢 Online",
            "idle": "🌙 Ausente",
            "dnd": "🔴 Não Perturbe",
            "invisible": "👻 Invisível"
        }
        
        embed.description = (
            f"**Configuração Atual:**\n"
            f"⏱️ **Intervalo:** `{interval}s`\n"
            f"🚦 **Modo:** `{status_emoji.get(state, 'Online')}`\n\n"
            f"📂 **Fila de Rotação ({len(activities)}):**"
        )

        if activities:
            txt_lista = ""
            for act in activities:
                # act = (id, type, text)
                icon = "🎮" if act[1] == "jogando" else "📺" if act[1] == "assistindo" else "🎧"
                txt_lista += f"`#{act[0]}` {icon} **[{act[1].upper()}]** {act[2]}\n"
            embed.add_field(name="Lista:", value=txt_lista[:1024])
        else:
            embed.add_field(name="Lista:", value="*Nenhum status configurado. O bot ficará padrão.*")

        embed.add_field(
            name="Variáveis Disponíveis", 
            value="`{membros}` `{ping}` `{servidores}`", 
            inline=False
        )

        view = PresenceView(self.bot, self)
        
        if is_edit:
            await interaction.edit_original_response(embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed, view=view)

    # ====================================================
    # 🔄 LOOP DE ROTAÇÃO
    # ====================================================
    @tasks.loop(seconds=60)
    async def presence_loop(self):
        await self.bot.wait_until_ready()
        
        # [V8] Check de Trava Global (ex: Bot Stream Ativo)
        if getattr(self.bot, 'presence_locked', False):
            return
        
        # Pega config
        # Nota: Pegamos do primeiro guild que achar só pra ter base, ou usamos padrão
        try:
            async with self.bot.db.execute("SELECT presence_interval, presence_state FROM config LIMIT 1") as cursor:
                cfg = await cursor.fetchone()
                
            interval = cfg[0] if cfg else 60
            state_str = cfg[1] if cfg else "online"

            # Ajusta intervalo dinamicamente
            if self.presence_loop.seconds != interval:
                self.presence_loop.change_interval(seconds=interval)

            # Pega atividades
            async with self.bot.db.execute("SELECT activity_type, activity_text, activity_url FROM presence") as cursor:
                activities = await cursor.fetchall()

            if not activities: return

            # Sorteia uma
            choice = random.choice(activities)
            act_type, act_text, act_url = choice

            # Formata Placeholders
            final_text = act_text.replace("{membros}", str(len(self.bot.users))) \
                                 .replace("{servidores}", str(len(self.bot.guilds))) \
                                 .replace("{ping}", str(round(self.bot.latency * 1000)))

            # Define Tipo
            if act_type == "jogando": type_obj = discord.ActivityType.playing
            elif act_type == "assistindo": type_obj = discord.ActivityType.watching
            elif act_type == "ouvindo": type_obj = discord.ActivityType.listening
            elif act_type == "competindo": type_obj = discord.ActivityType.competing
            elif act_type == "stream": type_obj = discord.ActivityType.streaming
            else: type_obj = discord.ActivityType.playing

            # Define Status
            if state_str == "idle": status_obj = discord.Status.idle
            elif state_str == "dnd": status_obj = discord.Status.dnd
            elif state_str == "invisible": status_obj = discord.Status.invisible
            else: status_obj = discord.Status.online

            # Aplica
            if act_type == "stream":
                await self.bot.change_presence(activity=discord.Streaming(name=final_text, url=act_url), status=status_obj)
            else:
                await self.bot.change_presence(activity=discord.Activity(type=type_obj, name=final_text), status=status_obj)

        except Exception as e:
            print(f"Erro no loop de presence: {e}")

# ====================================================
# 🎛️ MODALS E VIEWS
# ====================================================

class AddStatusModal(ui.Modal, title="Adicionar Novo Status"):
    type_input = ui.TextInput(label="Tipo", placeholder="jogando, assistindo, ouvindo, stream", min_length=4)
    text_input = ui.TextInput(label="Texto (Aceita {membros})", placeholder="Ex: Protegendo {membros} cidadãos", style=discord.TextStyle.paragraph)
    url_input = ui.TextInput(label="URL (Só para Stream)", placeholder="https://twitch.tv/...", required=False)

    def __init__(self, bot, parent_cog, interaction_origin):
        super().__init__()
        self.bot = bot
        self.cog = parent_cog
        self.origin = interaction_origin

    async def on_submit(self, interaction: discord.Interaction):
        t = self.type_input.value.lower()
        if t not in ["jogando", "assistindo", "ouvindo", "competindo", "stream"]:
            return await interaction.response.send_message("❌ Tipo inválido! Use: jogando, assistindo, ouvindo...", ephemeral=True)

        await self.bot.db.execute("INSERT INTO presence (activity_type, activity_text, activity_url) VALUES (?, ?, ?)",
                                  (t, self.text_input.value, self.url_input.value))
        await self.bot.db.commit()
        
        await interaction.response.send_message("✅ Adicionado!", ephemeral=True)
        # Atualiza o painel original
        await self.cog.send_panel(self.origin, is_edit=True)

class IntervalModal(ui.Modal, title="Alterar Intervalo"):
    seconds = ui.TextInput(label="Segundos (Min: 10)", placeholder="60")

    def __init__(self, bot, parent_cog, interaction_origin):
        super().__init__()
        self.bot = bot
        self.cog = parent_cog
        self.origin = interaction_origin

    async def on_submit(self, interaction: discord.Interaction):
        try:
            sec = int(self.seconds.value)
            if sec < 10: sec = 10
            
            await self.bot.db.execute("UPDATE config SET presence_interval = ? WHERE guild_id = ?", (sec, interaction.guild.id))
            await self.bot.db.commit()
            
            await interaction.response.send_message(f"✅ Intervalo alterado para {sec}s.", ephemeral=True)
            await self.cog.send_panel(self.origin, is_edit=True)
        except:
            await interaction.response.send_message("❌ Digite apenas números.", ephemeral=True)

class RemoveSelect(ui.Select):
    def __init__(self, bot, parent_cog, interaction_origin, options):
        self.bot = bot
        self.cog = parent_cog
        self.origin = interaction_origin
        super().__init__(placeholder="Selecione para remover...", options=options)

    async def callback(self, interaction: discord.Interaction):
        status_id = int(self.values[0])
        await self.bot.db.execute("DELETE FROM presence WHERE id = ?", (status_id,))
        await self.bot.db.commit()
        
        await interaction.response.send_message("🗑️ Removido com sucesso!", ephemeral=True)
        await self.cog.send_panel(self.origin, is_edit=True)

class PresenceView(ui.View):
    def __init__(self, bot, cog):
        super().__init__(timeout=None)
        self.bot = bot
        self.cog = cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != AUTHORIZED_ID:
            await interaction.response.send_message("❌ Você não tem permissão para interagir com este painel.", ephemeral=True)
            return False
        return True

    @ui.button(label="Adicionar", style=discord.ButtonStyle.success, emoji="➕")
    async def add_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(AddStatusModal(self.bot, self.cog, interaction))

    @ui.button(label="Remover", style=discord.ButtonStyle.danger, emoji="➖")
    async def rem_btn(self, interaction: discord.Interaction, button: ui.Button):
        # Busca lista para montar o select
        async with self.bot.db.execute("SELECT id, activity_text FROM presence") as cursor:
            rows = await cursor.fetchall()
            
        if not rows:
            return await interaction.response.send_message("❌ Lista vazia.", ephemeral=True)

        options = []
        for r in rows:
            # Limita tamanho do texto
            lbl = f"#{r[0]} - {r[1]}"[:99]
            options.append(discord.SelectOption(label=lbl, value=str(r[0])))

        view = ui.View()
        view.add_item(RemoveSelect(self.bot, self.cog, interaction, options))
        await interaction.response.send_message("Selecione qual deletar:", view=view, ephemeral=True)

    @ui.button(label="Intervalo", style=discord.ButtonStyle.secondary, emoji="⏱️")
    async def time_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(IntervalModal(self.bot, self.cog, interaction))

    @ui.button(label="Modo", style=discord.ButtonStyle.primary, emoji="🚦")
    async def mode_btn(self, interaction: discord.Interaction, button: ui.Button):
        # Ciclo: Online -> Idle -> DND -> Invisible
        async with self.bot.db.execute("SELECT presence_state FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            curr = await cursor.fetchone()
        
        curr = curr[0] if curr else "online"
        states = ["online", "idle", "dnd", "invisible"]
        
        try: next_idx = (states.index(curr) + 1) % len(states)
        except: next_idx = 0
        
        new_state = states[next_idx]
        
        await self.bot.db.execute("UPDATE config SET presence_state = ? WHERE guild_id = ?", (new_state, interaction.guild.id))
        await self.bot.db.commit()
        
        await interaction.response.defer() # Apenas carrega, não manda msg
        await self.cog.send_panel(interaction, is_edit=True)

async def setup(bot):
    await bot.add_cog(Presence(bot))