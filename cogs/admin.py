import discord
import asyncio
import sys
import os
import importlib 
import time
from discord.ext import commands
from discord import app_commands, ui

try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import config
except ImportError:
    class config:
        EMBED_COLOR = 0x000000

# ====================================================
# CLASSES DE UI (Definidas no topo para evitar erros)
# ====================================================

class RoleSelector(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="Selecione os cargos alvo...", min_values=1, max_values=25)

    async def callback(self, interaction: discord.Interaction):
        view = self.view 
        if interaction.user != view.author: return

        await interaction.response.defer()
        if not interaction.guild.chunked: await interaction.guild.chunk()

        view.target_members = set()
        for role in self.values:
            for member in role.members:
                if not member.bot: view.target_members.add(member)
        
        view.start_btn.disabled = False
        view.start_btn.label = f"🚀 Iniciar ({len(view.target_members)})"
        view.start_btn.style = discord.ButtonStyle.green
        
        painel = interaction.message.embeds[1]
        painel.description = f"✅ **Alvo:** {len(view.target_members)} membros.\nPronto para disparar."
        painel.color = discord.Color.blue()
        
        await interaction.edit_original_response(embeds=[interaction.message.embeds[0], painel], view=view)

class CampaignView(ui.View):
    def __init__(self, bot, author, embed_to_send, delay, link_btn, label_btn, emoji_btn):
        super().__init__(timeout=None)
        self.bot = bot
        self.author = author
        self.embed_to_send = embed_to_send
        self.delay = delay
        self.link_btn = link_btn
        self.label_btn = label_btn
        self.emoji_btn = emoji_btn
        self.target_members = set()
        self.stop_signal = False
        self.add_item(RoleSelector())

    @ui.button(label="Selecione cargos...", style=discord.ButtonStyle.secondary, disabled=True, row=1)
    async def start_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user != self.author: return
        self.stop_signal = False
        button.disabled = True
        self.stop_btn.disabled = False
        self.children[0].disabled = True
        await interaction.response.edit_message(view=self)
        asyncio.create_task(self.run_process(interaction))

    @ui.button(label="⛔ PARAR", style=discord.ButtonStyle.danger, disabled=True, row=1)
    async def stop_btn(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user != self.author: return
        self.stop_signal = True
        button.label = "🛑 Parando..."
        button.disabled = True
        await interaction.response.edit_message(view=self)

    def make_bar(self, current, total):
        percent = current / total * 100 if total > 0 else 0
        filled = int(15 * percent // 100)
        return '▰' * filled + '▱' * (15 - filled) + f" {int(percent)}%"

    async def run_process(self, interaction):
        sent = 0
        failed = 0
        total = len(self.target_members)
        
        # Cria o botão que vai para o usuário
        user_view = None
        if self.link_btn and self.label_btn:
            user_view = ui.View()
            # Adiciona o botão com link e emoji (se tiver)
            # Nota: Botões de Link são SEMPRE cinza (Limitação do Discord)
            btn = ui.Button(
                label=self.label_btn, 
                url=self.link_btn, 
                style=discord.ButtonStyle.link,
                emoji=self.emoji_btn # <--- AQUI ENTRA O ÍCONE
            )
            user_view.add_item(btn)

        painel = interaction.message.embeds[1]
        members_list = list(self.target_members)

        for index, member in enumerate(members_list, 1):
            if self.stop_signal: break
            try:
                await member.send(embed=self.embed_to_send, view=user_view)
                sent += 1
            except: failed += 1
            
            if index % 5 == 0 or index == total:
                painel.title = "🚀 Enviando..."
                painel.color = discord.Color.gold()
                painel.description = f"`{self.make_bar(index, total)}`\n\n📨 {sent} | 🚫 {failed}"
                try: await interaction.edit_original_response(embeds=[interaction.message.embeds[0], painel], view=self)
                except: pass
            
            await asyncio.sleep(self.delay)

        painel.title = "✅ Finalizado" if not self.stop_signal else "⚠️ Parado"
        painel.color = discord.Color.green() if not self.stop_signal else discord.Color.red()
        painel.description = f"**Relatório:**\n👥 {total}\n✅ {sent}\n❌ {failed}"
        self.stop_btn.disabled = True
        await interaction.edit_original_response(embeds=[interaction.message.embeds[0], painel], view=self)

# ====================================================
# COG PRINCIPAL
# ====================================================

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- FERRAMENTAS ---
    @app_commands.command(name="reload", description="🔄 Recarrega um módulo")
    @app_commands.checks.has_permissions(administrator=True)
    async def reload_cog(self, interaction: discord.Interaction, modulo: str):
        try:
            await self.bot.reload_extension(f"cogs.{modulo}")
            importlib.reload(config)
            await interaction.response.send_message(f"✅ Módulo **`{modulo}`** recarregado!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Erro: {e}", ephemeral=True)

    @app_commands.command(name="sync", description="☁️ Sincroniza comandos Slash")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_tree(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.tree.sync()
            await interaction.followup.send("✅ Sincronizado!")
        except Exception as e:
            await interaction.followup.send(f"❌ Erro: {e}")

    @app_commands.command(name="listar_emojis", description="Lista emojis para config")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_emojis(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            guild_emojis = list(self.bot.emojis)
            try: app_emojis = await self.bot.fetch_application_emojis()
            except: app_emojis = []
            
            all = guild_emojis + app_emojis
            if not all:
                await interaction.followup.send("❌ Nada encontrado.")
                return

            code = "```python\n"
            for e in all:
                code += f"# {e.name}\nVARIABLE = \"{str(e)}\"\n\n"
            code += "```"
            await interaction.followup.send(f"📋 **Emojis:**\n{code}")
        except Exception as e:
             await interaction.followup.send(f"Erro: {e}")

    # --- CAMPANHA DM ---
    @app_commands.command(name="campanha_dm", description="MassDM Avançado")
    @app_commands.describe(
        titulo="Título", 
        mensagem="Texto", 
        delay="Delay (s)", 
        imagem="URL Imagem",
        texto_botao="Texto do botão (Ex: Conectar)",
        link_botao="Link do botão (Ex: https://...)",
        emoji_botao="Emoji do botão (Ex: 🔗 ou ID personalizado)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def campaign_dm(self, interaction: discord.Interaction, 
                          titulo: str, 
                          mensagem: str, 
                          delay: app_commands.Range[int, 1, 60] = 2, 
                          imagem: str = None, 
                          texto_botao: str = None, 
                          link_botao: str = None,
                          emoji_botao: str = None):
        
        embed = discord.Embed(title=titulo, description=mensagem, color=config.EMBED_COLOR)
        
        # CORREÇÃO: Usa display_avatar (Pega a foto mesmo se for padrão)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        if imagem: embed.set_image(url=imagem)
        embed.set_footer(text=f"Via {interaction.guild.name}", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)

        painel = discord.Embed(
            title="🎛️ Painel de Campanha",
            description=f"1. Revise o preview.\n2. Selecione cargos.\n3. Inicie.\n\n⏱️ **Delay:** `{delay}s`",
            color=discord.Color.light_grey()
        )

        view = CampaignView(self.bot, interaction.user, embed, delay, link_botao, texto_botao, emoji_botao)
        await interaction.response.send_message(content="**👁️ PREVIEW:**", embeds=[embed, painel], view=view, ephemeral=True)

    # --- LIMPEZA DE CHAT ---
    @app_commands.command(name="limpar", description="🧹 Limpa mensagens do chat")
    @app_commands.describe(quantidade="Número de mensagens para apagar")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def clear_chat(self, interaction: discord.Interaction, quantidade: int):
        await interaction.response.defer(ephemeral=True)
        try:
            deleted = await interaction.channel.purge(limit=quantidade)
            await interaction.followup.send(f"✅ {len(deleted)} mensagens limpas!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro ao limpar: {e}", ephemeral=True)

    # --- CONFIGURAÇÃO (SETUP) ---
    @app_commands.command(name="setup_streaming", description="⚙️ Configura o módulo de Streaming")
    @app_commands.describe(canal="Canal onde as lives serão divulgadas", cargo="Cargo a ser dado (Opcional)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_streaming(self, interaction: discord.Interaction, canal: discord.TextChannel, cargo: discord.Role = None):
        role_id = cargo.id if cargo else None
        
        # Upsert na tabela config
        # SQLite UPSERT syntax: INSERT INTO ... ON CONFLICT(guild_id) DO UPDATE SET ...
        # Mas nossa tabela config pode não ter UNIQUE(guild_id) garantido em versões antigas? 
        # Assumindo que tem PRIMARY KEY(guild_id) ou UNIQUE
        
        # Vamos checar se já existe registro
        exists = await self.bot.db.execute("SELECT 1 FROM config WHERE guild_id = ?", (interaction.guild.id,))
        row = await exists.fetchone()
        
        if row:
            await self.bot.db.execute("UPDATE config SET streaming_channel_id = ?, streaming_role_id = ? WHERE guild_id = ?", (canal.id, role_id, interaction.guild.id))
        else:
             await self.bot.db.execute("INSERT INTO config (guild_id, streaming_channel_id, streaming_role_id) VALUES (?, ?, ?)", (interaction.guild.id, canal.id, role_id))
             
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ **Streaming Configurado!**\n📺 Canal: {canal.mention}\n🎭 Cargo: {cargo.mention if cargo else 'Nenhum'}", ephemeral=True)

    @app_commands.command(name="setup_tickets", description="⚙️ Configura o canal de Tickets (para Punições)")
    @app_commands.describe(canal="Canal onde fica o painel de tickets")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_tickets(self, interaction: discord.Interaction, canal: discord.TextChannel):
        exists = await self.bot.db.execute("SELECT 1 FROM config WHERE guild_id = ?", (interaction.guild.id,))
        row = await exists.fetchone()
        
        if row:
            await self.bot.db.execute("UPDATE config SET ticket_panel_channel_id = ? WHERE guild_id = ?", (canal.id, interaction.guild.id))
        else:
             await self.bot.db.execute("INSERT INTO config (guild_id, ticket_panel_channel_id) VALUES (?, ?)", (interaction.guild.id, canal.id))
             
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ **Tickets Configurado!**\n🎫 Canal Vinculado: {canal.mention}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Admin(bot))