import discord
import sys
import os
import datetime
from discord.ext import commands
from discord import app_commands, ui

try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import config
except ImportError:
    class config:
        EMBED_COLOR = 0x000000
        EMOJI_JOIN = "✈️"
        EMOJI_LEAVE = "📤"
        EMOJI_ID = "🆔"
        EMOJI_TIME = "⏱️"
        EMOJI_ROLES = "🛡️"
        EMOJI_WL = "📋"

class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(WelcomePanel(self.bot, self))
        print("[+] [Welcome] Painel persistente carregado.")

    # ====================================================
    # 🖥️ DASHBOARD (PAINEL ADMIN)
    # ====================================================
    @app_commands.command(name="painel_welcome", description="Gerenciador Visual de Boas-Vindas")
    @app_commands.checks.has_permissions(administrator=True)
    async def welcome_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.send_panel(interaction)

    async def send_panel(self, interaction: discord.Interaction, is_edit=False):
        async with self.bot.db.execute("SELECT * FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                cols = [d[0] for d in cursor.description]
                data = dict(zip(cols, row))
            else:
                data = {}

        w_id = data.get('welcome_channel_id')
        l_id = data.get('logs_channel_id')
        color = data.get('welcome_color') or config.EMBED_COLOR
        banner = data.get('welcome_banner')
        
        w_chan = self.bot.get_channel(w_id) if w_id else None
        l_chan = self.bot.get_channel(l_id) if l_id else None

        embed = discord.Embed(title="✈️ Configuração de Boas-Vindas", color=color)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        if banner: embed.set_image(url=banner)
        
        status_w = f"✅ {w_chan.mention}" if w_chan else "🔴 Off (Apenas DM)"
        status_w = f"✅ {w_chan.mention}" if w_chan else "🔴 Off (Apenas DM)"
        status_l = f"✅ {l_chan.mention}" if l_chan else "🔴 Off"
        dm_active = data.get('welcome_dm_active', 1)
        status_dm = "✅ Ativado" if dm_active else "🔴 Desativado"

        # Resumo visual
        btns_str = ""
        
        for i in range(1, 4):
            url = data.get(f'btn{i}_url')
            lbl = data.get(f'btn{i}_label') or f"Btn {i}"
            btns_str += f"{'✅' if url else '⚪'} **{lbl}**\n"

        embed.description = (
            f"**Canais:**\n📥 Entrada: {status_w}\n📤 Logs: {status_l}\n\n"
            f"**Configurações:**\n📨 Enviar DM: {status_dm}\n🎨 Cor: `#{hex(color)[2:].upper()}`\n🖼️ Banner: {'`Sim`' if banner else '`Não`'}\n\n"
            f"**Botões:**\n{btns_str}\n\n"
            f"ℹ️ *O membro receberá uma cópia deste embed na DM automaticamente (se ativado).* "
        )

        view = WelcomePanel(self.bot, self)
        if is_edit: await interaction.edit_original_response(embed=embed, view=view)
        else: await interaction.followup.send(embed=embed, view=view)

    # ====================================================
    # 🧠 LÓGICA DE PROCESSAMENTO
    # ====================================================
    async def process_join(self, member):
        async with self.bot.db.execute("SELECT * FROM config WHERE guild_id = ?", (member.guild.id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                cols = [d[0] for d in cursor.description]
                data = dict(zip(cols, row))
            else:
                data = {}

        color = data.get('welcome_color') or config.EMBED_COLOR
        banner = data.get('welcome_banner')

        embed = discord.Embed(color=color)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_author(name=f"Bem-vindo(a) à {member.guild.name}!", icon_url=member.display_avatar.url)
        
        embed.description = (
            f"Olá {member.mention}, seja muito bem-vindo(a)!\n\n"
            f"Fique à vontade para explorar os canais e interagir com a comunidade."
        )
        
        if banner: embed.set_image(url=banner)
        elif member.guild.icon: embed.set_image(url=member.guild.icon.url)
        
        embed.set_footer(text=f"ID: {member.id} • Membro #{member.guild.member_count}")
        embed.timestamp = datetime.datetime.now()

        view = UserWelcomeView(data)

        # Canal Público
        channel_id = data.get('welcome_channel_id')
        if channel_id:
            channel = self.bot.get_channel(channel_id)
            if channel:
                try: await channel.send(content=f"{member.mention}", embed=embed, view=view)
                except Exception as e: print(f"❌ Erro Welcome Canal: {e}")

        # DM
        if data.get('welcome_dm_active', 1):
            try:
                dm_view = UserWelcomeView(data)
                await member.send(embed=embed, view=dm_view)
            except: pass

    async def process_leave(self, member):
        async with self.bot.db.execute("SELECT logs_channel_id FROM config WHERE guild_id = ?", (member.guild.id,)) as cursor:
            res = await cursor.fetchone()
        
        if not res or not res[0]: return
        channel = self.bot.get_channel(res[0])
        if not channel: return

        roles = [r.name for r in member.roles if r.name != "@everyone"]
        roles_str = ", ".join(roles) if roles else "Visitante"
        time_str = f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "?"

        embed = discord.Embed(title="Auditoria de Saída", color=0xe74c3c, timestamp=datetime.datetime.now())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name=f"{config.EMOJI_LEAVE} Usuário", value=f"{member.name}\n{member.mention}", inline=True)
        embed.add_field(name=f"{config.EMOJI_ID} ID", value=f"`{member.id}`", inline=True)
        embed.add_field(name=f"{config.EMOJI_TIME} Histórico", value=f"Entrou: {time_str}", inline=False)
        embed.add_field(name=f"{config.EMOJI_ROLES} Cargos", value=f"```diff\n- {roles_str}\n```", inline=False)

        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_join(self, member): await self.process_join(member)
    @commands.Cog.listener()
    async def on_member_remove(self, member): await self.process_leave(member)

# ====================================================
# 🎛️ MODALS (VISUAL & BOTOES)
# ====================================================

class StyleModal(ui.Modal, title="🎨 Editar Visual"):
    def __init__(self, bot, cog, origin, cur_color, cur_banner):
        super().__init__()
        self.bot = bot
        self.cog = cog
        self.origin = origin
        
        self.color_hex = ui.TextInput(label="Cor HEX", placeholder="#000000", min_length=7, max_length=7, default=f"#{hex(cur_color)[2:].upper()}" if cur_color else "#000000")
        self.banner_url = ui.TextInput(label="URL Banner", placeholder="https://...", required=False, default=cur_banner if cur_banner else "")
        self.add_item(self.color_hex)
        self.add_item(self.banner_url)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        hex_code = self.color_hex.value.replace("#", "")
        try: int_color = int(hex_code, 16)
        except: return await interaction.followup.send("❌ Cor inválida!")

        await self.bot.db.execute("UPDATE config SET welcome_color = ?, welcome_banner = ? WHERE guild_id = ?", (int_color, self.banner_url.value, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.followup.send("✅ Visual salvo!")
        await self.cog.send_panel(self.origin, is_edit=True)

class ButtonConfigModal(ui.Modal):
    def __init__(self, bot, cog, origin, idx, cur_lbl, cur_url, cur_emj):
        title = "Configurar WL" if idx == 'wl' else f"Configurar Botão {idx}"
        super().__init__(title=title)
        self.bot = bot
        self.cog = cog
        self.origin = origin
        self.idx = idx
        
        self.lbl = ui.TextInput(label="Texto", placeholder="Texto...", default=cur_lbl or "")
        self.url = ui.TextInput(label="Link (Vazio = Botão Interno)", placeholder="https://...", required=False, default=cur_url or "")
        self.emj = ui.TextInput(label="Emoji (Cole <a:nome:id> para animado)", placeholder="📋", required=False, default=cur_emj or "")
        self.add_item(self.lbl)
        self.add_item(self.url)
        self.add_item(self.emj)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        prefix = "wl_btn" if self.idx == "wl" else f"btn{self.idx}"
        await self.bot.db.execute(f"UPDATE config SET {prefix}_label = ?, {prefix}_url = ?, {prefix}_emoji = ? WHERE guild_id = ?", (self.lbl.value, self.url.value, self.emj.value, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.followup.send("✅ Botão salvo!")
        await self.cog.send_panel(self.origin, is_edit=True)

class ButtonActionView(ui.View):
    def __init__(self, bot, cog, origin, idx, current_data):
        super().__init__(timeout=None)
        self.bot = bot
        self.cog = cog
        self.origin = origin
        self.idx = idx
        self.data = current_data

    @ui.button(label="✏️ Editar", style=discord.ButtonStyle.primary)
    async def edit_btn(self, interaction: discord.Interaction, button: ui.Button):
        prefix = "wl_btn" if self.idx == "wl" else f"btn{self.idx}"
        lbl = self.data.get(f'{prefix}_label')
        url = self.data.get(f'{prefix}_url')
        emj = self.data.get(f'{prefix}_emoji')
        await interaction.response.send_modal(ButtonConfigModal(self.bot, self.cog, self.origin, self.idx, lbl, url, emj))

    @ui.button(label="🗑️ Apagar / Resetar", style=discord.ButtonStyle.danger)
    async def delete_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        prefix = "wl_btn" if self.idx == "wl" else f"btn{self.idx}"
        await self.bot.db.execute(f"UPDATE config SET {prefix}_label = '', {prefix}_url = '', {prefix}_emoji = '' WHERE guild_id = ?", (interaction.guild.id,))
        await self.bot.db.commit()
        msg = "✅ Botão resetado!" if self.idx == "wl" else "🗑️ Botão apagado!"
        await interaction.followup.send(msg)
        await self.cog.send_panel(self.origin, is_edit=True)

class ButtonSelectView(ui.View):
    def __init__(self, bot, cog, origin, data):
        super().__init__(timeout=None)
        self.bot = bot
        self.cog = cog
        self.origin = origin
        self.data = data

    @ui.select(placeholder="Qual botão configurar?", options=[
        discord.SelectOption(label="Botão Link 1", value="1", emoji="1️⃣"),
        discord.SelectOption(label="Botão Link 2", value="2", emoji="2️⃣"),
        discord.SelectOption(label="Botão Link 3", value="3", emoji="3️⃣")
    ])
    async def select_btn(self, interaction: discord.Interaction, select: ui.Select):
        idx = select.values[0]
        embed = discord.Embed(description=f"O que deseja fazer com o **Botão {idx if idx != 'wl' else 'Whitelist'}**?", color=discord.Color.light_grey())
        await interaction.response.send_message(embed=embed, view=ButtonActionView(self.bot, self.cog, self.origin, idx, self.data), ephemeral=True)

class WelcomePanel(ui.View):
    def __init__(self, bot, cog):
        super().__init__(timeout=None)
        self.bot = bot
        self.cog = cog

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Canal de Entrada", channel_types=[discord.ChannelType.text], row=0, custom_id="welcome_sel_welcome")
    async def sel_welcome(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await interaction.response.defer()
        await self.bot.db.execute("INSERT OR REPLACE INTO config (guild_id, welcome_channel_id) VALUES (?, ?)", (interaction.guild.id, select.values[0].id))
        await self.bot.db.commit()
        await self.cog.send_panel(interaction, is_edit=True)

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Canal de Logs", channel_types=[discord.ChannelType.text], row=1, custom_id="welcome_sel_logs")
    async def sel_logs(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await interaction.response.defer()
        exists = await self.bot.db.execute_fetchall("SELECT 1 FROM config WHERE guild_id = ?", (interaction.guild.id,))
        if exists: await self.bot.db.execute("UPDATE config SET logs_channel_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        else: await self.bot.db.execute("INSERT INTO config (guild_id, logs_channel_id) VALUES (?, ?)", (interaction.guild.id, select.values[0].id))
        await self.bot.db.commit()
        await self.cog.send_panel(interaction, is_edit=True)

    @ui.button(label="Editar Visual", style=discord.ButtonStyle.secondary, emoji="🎨", row=2, custom_id="welcome_btn_style")
    async def style_btn(self, interaction: discord.Interaction, button: ui.Button):
        async with self.bot.db.execute("SELECT welcome_color, welcome_banner FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()
        col, ban = (row[0], row[1]) if row else (0, "")
        await interaction.response.send_modal(StyleModal(self.bot, self.cog, interaction, col, ban))

    @ui.button(label="Configurar Botões", style=discord.ButtonStyle.secondary, emoji="🔗", row=2, custom_id="welcome_btn_links")
    async def links_btn(self, interaction: discord.Interaction, button: ui.Button):
        async with self.bot.db.execute("SELECT * FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()
            data = dict(zip([d[0] for d in cursor.description], row)) if row else {}
        await interaction.response.send_message("Selecione:", view=ButtonSelectView(self.bot, self.cog, interaction, data), ephemeral=True)

    @ui.button(label="Toggle DM", style=discord.ButtonStyle.secondary, emoji="📨", row=2, custom_id="welcome_btn_dm")
    async def toggle_dm(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        async with self.bot.db.execute("SELECT welcome_dm_active FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()
        
        current = row[0] if row else 1
        new_val = 0 if current else 1
        
        await self.bot.db.execute("UPDATE config SET welcome_dm_active = ? WHERE guild_id = ?", (new_val, interaction.guild.id))
        await self.bot.db.commit()
        await self.cog.send_panel(interaction, is_edit=True)

    @ui.button(label="Testar Entrada", style=discord.ButtonStyle.success, emoji="📥", row=3, custom_id="welcome_btn_test_join")
    async def test_join(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("Simulando... (Verifique a DM e o Canal)")
        await self.cog.process_join(interaction.user)

    @ui.button(label="Testar Saída", style=discord.ButtonStyle.danger, emoji="📤", row=3, custom_id="welcome_btn_test_leave")
    async def test_leave(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("Simulando...")
        await self.cog.process_leave(interaction.user)

# ====================================================
# 🔘 HELPER DE EMOJIS & BOTÕES FINAIS
# ====================================================

def parse_emoji(custom_emoji):
    """Converte string <a:nome:id> em objeto PartialEmoji para botões funcionarem"""
    if not custom_emoji: return None
    try:
        return discord.PartialEmoji.from_str(custom_emoji)
    except:
        return custom_emoji # Retorna string unicode normal se falhar

class UserWelcomeView(ui.View):
    def __init__(self, db_data):
        super().__init__(timeout=None)
        
        # Adiciona Botões Extras (Parseando Emoji)
        for i in range(1, 4):
            url = db_data.get(f'btn{i}_url')
            if url and url.strip():
                lbl = db_data.get(f'btn{i}_label') or f"Link {i}"
                emj = db_data.get(f'btn{i}_emoji')
                parsed_emj = parse_emoji(emj)
                
                # Botão de Link (Cinza)
                self.add_item(ui.Button(label=lbl, url=url, style=discord.ButtonStyle.link, emoji=parsed_emj))

async def setup(bot):
    await bot.add_cog(Welcome(bot))