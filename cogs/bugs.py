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

# IMAGEM TRANSPARENTE WIDE
INVISIBLE_WIDE_URL = "https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png"

def parse_emoji(custom_emoji):
    if not custom_emoji: return None
    try: return discord.PartialEmoji.from_str(custom_emoji)
    except: return custom_emoji

class Bugs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ====================================================
    # 🖥️ PAINEL DE CONFIGURAÇÃO
    # ====================================================
    @app_commands.command(name="painel_bugs", description="Configura o sistema de report de bugs")
    @app_commands.checks.has_permissions(administrator=True)
    async def bug_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.send_admin_panel(interaction)

    async def send_admin_panel(self, interaction: discord.Interaction, is_edit=False):
        async with self.bot.db.execute("SELECT * FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()
            data = dict(zip([d[0] for d in cursor.description], row)) if row else {}

        pub_id = data.get('bug_public_channel_id')
        stf_id = data.get('bug_staff_channel_id')
        
        pub_chan = self.bot.get_channel(pub_id) if pub_id else None
        stf_chan = self.bot.get_channel(stf_id) if stf_id else None

        e_pub = data.get('bug_emoji_public') or "🐛"
        e_ana = data.get('bug_emoji_analyze') or "🔍"
        e_fix = data.get('bug_emoji_fixed') or "✅"
        e_inv = data.get('bug_emoji_invalid') or "❌"

        embed = discord.Embed(title="🐛 Central de Bugs", color=config.EMBED_COLOR)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        status_pub = f"✅ {pub_chan.mention}" if pub_chan else "🔴 Não definido"
        status_stf = f"✅ {stf_chan.mention}" if stf_chan else "🔴 Não definido"

        embed.description = (
            f"**Fluxo de Reports:**\n📢 Público: {status_pub}\n🛡️ Staff: {status_stf}\n\n"
            f"**Emojis Atuais:**\n"
            f"Publicar: {e_pub} | Análise: {e_ana}\n"
            f"Corrigido: {e_fix} | Inválido: {e_inv}"
        )
        
        # WIDE MODE
        embed.set_image(url=INVISIBLE_WIDE_URL)
        
        view = BugAdminView(self.bot, self)
        
        if is_edit: await interaction.edit_original_response(embed=embed, view=view)
        else: await interaction.followup.send(embed=embed, view=view)

    # ====================================================
    # 📝 LÓGICA DE REPORT (SUBMIT)
    # ====================================================
    async def submit_bug(self, interaction, title, desc, steps, media):
        async with self.bot.db.execute("SELECT bug_staff_channel_id, bug_count, bug_emoji_analyze, bug_emoji_fixed, bug_emoji_invalid FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            res = await cursor.fetchone()
            if not res or not res[0]:
                return await interaction.response.send_message("❌ Erro: Canal da Staff não configurado.", ephemeral=True)
            
            staff_channel_id = res[0]
            count = (res[1] or 0) + 1
            emojis = {'analyze': res[2] or "🔍", 'fixed': res[3] or "✅", 'invalid': res[4] or "❌"}

        await self.bot.db.execute("UPDATE config SET bug_count = ? WHERE guild_id = ?", (count, interaction.guild.id))
        await self.bot.db.commit()

        staff_chan = self.bot.get_channel(staff_channel_id)
        if not staff_chan:
            return await interaction.response.send_message("❌ Erro: Canal da Staff sumiu.", ephemeral=True)

        embed = discord.Embed(title=f"🐛 Bug Report #{count:03d}", color=0xe74c3c)
        
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_author(name=f"Reportado por {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
        
        # Campos formatados em blocos de código
        embed.add_field(name="📍 Resumo", value=f"```txt\n{title}\n```", inline=False)
        embed.add_field(name="📝 Descrição", value=f"```txt\n{desc}\n```", inline=False)
        if steps: embed.add_field(name="👣 Passo a Passo", value=f"```txt\n{steps}\n```", inline=False)
        if media: embed.add_field(name="📸 Provas/Mídia", value=f"```txt\n{media}\n```", inline=False)
        
        embed.set_footer(text=f"ID Usuário: {interaction.user.id}")
        embed.timestamp = datetime.datetime.now()

        # WIDE MODE
        embed.set_image(url=INVISIBLE_WIDE_URL)

        view = BugManagementView(interaction.user.id, emojis)
        await staff_chan.send(content="🚨 **Novo Bug Reportado!**", embed=embed, view=view)
        await interaction.response.send_message(f"✅ **Report enviado!** Ticket: `#{count:03d}`.", ephemeral=True)

# ====================================================
# VIEWS & MODALS
# ====================================================

class BugReportModal(ui.Modal, title="Reportar Bug"):
    bug_title = ui.TextInput(label="Resumo", placeholder="Ex: Ticket não abre", max_length=100)
    bug_desc = ui.TextInput(label="Descrição Detalhada", style=discord.TextStyle.paragraph)
    bug_steps = ui.TextInput(label="Passo a Passo (Opcional)", style=discord.TextStyle.paragraph, required=False)
    bug_media = ui.TextInput(label="Link demonstrativo (Opcional)", placeholder="https://...", required=False)

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.submit_bug(interaction, self.bug_title.value, self.bug_desc.value, self.bug_steps.value, self.bug_media.value)

class BugVisualModal(ui.Modal, title="🎨 Emojis dos Botões"):
    def __init__(self, bot, cog, origin, emojis):
        super().__init__()
        self.bot = bot
        self.cog = cog
        self.origin = origin
        
        self.e_pub = ui.TextInput(label="Botão Público", default=emojis.get('bug_emoji_public', '🐛'))
        self.e_ana = ui.TextInput(label="Botão Análise", default=emojis.get('bug_emoji_analyze', '🔍'))
        self.e_fix = ui.TextInput(label="Botão Corrigido", default=emojis.get('bug_emoji_fixed', '✅'))
        self.e_inv = ui.TextInput(label="Botão Inválido", default=emojis.get('bug_emoji_invalid', '❌'))
        
        self.add_item(self.e_pub)
        self.add_item(self.e_ana)
        self.add_item(self.e_fix)
        self.add_item(self.e_inv)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.execute("""
            UPDATE config SET bug_emoji_public=?, bug_emoji_analyze=?, bug_emoji_fixed=?, bug_emoji_invalid=?
            WHERE guild_id=?
        """, (self.e_pub.value, self.e_ana.value, self.e_fix.value, self.e_inv.value, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.followup.send("✅ Emojis salvos!")
        await self.cog.send_admin_panel(self.origin, is_edit=True)

class PublicBugView(ui.View):
    def __init__(self, cog, emoji_public="🐛"):
        super().__init__(timeout=None)
        self.cog = cog
        # ESTILO SECUNDÁRIO (CINZA)
        self.add_item(ui.Button(label="Reportar Bug", style=discord.ButtonStyle.secondary, emoji=parse_emoji(emoji_public), custom_id="open_bug_modal"))

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.data['custom_id'] == "open_bug_modal":
            await interaction.response.send_modal(BugReportModal(self.cog))
        return False

class BugManagementView(ui.View):
    def __init__(self, author_id, emojis):
        super().__init__(timeout=None)
        self.author_id = author_id
        
        # TODOS OS BOTÕES SECUNDÁRIOS (CINZA)
        self.add_item(ui.Button(label="Em Análise", style=discord.ButtonStyle.secondary, emoji=parse_emoji(emojis['analyze']), custom_id="bug_analyze"))
        self.add_item(ui.Button(label="Corrigido", style=discord.ButtonStyle.secondary, emoji=parse_emoji(emojis['fixed']), custom_id="bug_fixed"))
        self.add_item(ui.Button(label="Inválido", style=discord.ButtonStyle.secondary, emoji=parse_emoji(emojis['invalid']), custom_id="bug_invalid"))

    async def interaction_check(self, interaction: discord.Interaction):
        cid = interaction.data['custom_id']
        if cid == "bug_analyze": await self.notify_user(interaction, "🔍 Em Análise", 0xe67e22, "Estamos investigando seu caso.")
        elif cid == "bug_fixed": await self.notify_user(interaction, "✅ Corrigido", 0x2ecc71, "Obrigado! O bug foi resolvido.", True)
        elif cid == "bug_invalid": await self.notify_user(interaction, "❌ Inválido", 0x2b2d31, "Report invalidado.", True)
        return False

    async def notify_user(self, interaction, status, color, message_text, disable_buttons=False):
        embed = interaction.message.embeds[0]
        embed.color = color
        
        timestamp = discord.utils.format_dt(datetime.datetime.now(), style="t")
        log_line = f"• {status} por {interaction.user.mention} às {timestamp}"
        
        history_field_index = -1
        for i, field in enumerate(embed.fields):
            if field.name == "📜 Histórico de Status":
                history_field_index = i
                break
        
        if history_field_index != -1:
            curr_val = embed.fields[history_field_index].value
            # Remove backticks if present to append clearly, then re-wrap or handle plain
            # Mas como o histórico cresce, melhor deixar sem bloco de código pra não quebrar
            # ou usar um bloco grande. Vou manter texto simples no histórico para legibilidade.
            lines = curr_val.split('\n')[-2:] 
            lines.append(log_line)
            embed.set_field_at(history_field_index, name="📜 Histórico de Status", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="📜 Histórico de Status", value=log_line, inline=False)

        if disable_buttons:
            for child in self.children: child.disabled = True
        
        await interaction.message.edit(embed=embed, view=self)
        
        try:
            user = await interaction.client.fetch_user(self.author_id)
            dm_embed = discord.Embed(title="🔔 Atualização do Bug Report", color=color)
            dm_embed.set_thumbnail(url=interaction.client.user.display_avatar.url)
            
            dm_embed.add_field(name="Status Atual", value=status, inline=True)
            dm_embed.add_field(name="Staff Responsável", value=interaction.user.mention, inline=True)
            
            dm_embed.add_field(name="Mensagem", value=f"```txt\n{message_text}\n```", inline=False)
            dm_embed.set_footer(text=f"Servidor: {interaction.guild.name}", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
            dm_embed.timestamp = datetime.datetime.now()
            
            # WIDE MODE NA DM TAMBÉM
            dm_embed.set_image(url=INVISIBLE_WIDE_URL)
            
            await user.send(embed=dm_embed)
            await interaction.response.send_message(f"✅ Status: **{status}** (DM Enviada).", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"✅ Status: **{status}** (⚠️ DM Falhou: {e}).", ephemeral=True)

class BugAdminView(ui.View):
    def __init__(self, bot, cog):
        super().__init__(timeout=None)
        self.bot = bot
        self.cog = cog

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Canal Público", channel_types=[discord.ChannelType.text], row=0)
    async def sel_pub(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await interaction.response.defer()
        await self.bot.db.execute("UPDATE config SET bug_public_channel_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await self.cog.send_admin_panel(interaction, is_edit=True)

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Canal Staff", channel_types=[discord.ChannelType.text], row=1)
    async def sel_stf(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await interaction.response.defer()
        await self.bot.db.execute("UPDATE config SET bug_staff_channel_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await self.cog.send_admin_panel(interaction, is_edit=True)

    @ui.button(label="Editar Emojis", style=discord.ButtonStyle.secondary, emoji="🎨", row=2)
    async def edit_emojis(self, interaction: discord.Interaction, button: ui.Button):
        async with self.bot.db.execute("SELECT bug_emoji_public, bug_emoji_analyze, bug_emoji_fixed, bug_emoji_invalid FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()
            keys = ['bug_emoji_public', 'bug_emoji_analyze', 'bug_emoji_fixed', 'bug_emoji_invalid']
            data = dict(zip(keys, row)) if row else {}
            
        await interaction.response.send_modal(BugVisualModal(self.bot, self.cog, interaction, data))

    # ESTILO SECUNDÁRIO (CINZA)
    @ui.button(label="Postar Botão", style=discord.ButtonStyle.secondary, emoji="🚀", row=2)
    async def post_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db.execute("SELECT bug_public_channel_id, bug_emoji_public FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            res = await cursor.fetchone()
        
        if not res or not res[0]: return await interaction.followup.send("❌ Configure Canal Público.")
        
        channel = self.bot.get_channel(res[0])
        emj = res[1] or "🐛"
        
        embed = discord.Embed(title="Central de Bugs", color=0xe74c3c)
        embed.description = "**Encontrou algum bug? Ajude-nos a melhorar!**\n\nComo reportar:\nClique no botão abaixo.\nDescreva o problema com detalhes.\nSe possível, anexe link de vídeos ou prints."
        
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        # WIDE MODE
        embed.set_image(url=INVISIBLE_WIDE_URL)
        
        view = PublicBugView(self.cog, emj)
        await channel.send(embed=embed, view=view)
        await interaction.followup.send("✅ Postado!")

async def setup(bot):
    await bot.add_cog(Bugs(bot))