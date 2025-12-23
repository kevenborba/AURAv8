import discord
from discord import app_commands
from discord.ext import commands
import datetime
from typing import Optional

# ==============================================================================
# VIEW: DASHBOARD DE CONFIGURAÇÃO (Configuração Visual e Canais)
# ==============================================================================
class PunishmentDashboardView(discord.ui.View):
    def __init__(self, bot, author):
        super().__init__(timeout=300)
        self.bot = bot
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.author:
            await interaction.response.send_message("⛔ **Apenas o autor pode usar.**", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Editar Textos (DM)", style=discord.ButtonStyle.secondary, emoji="📝", row=0)
    async def btn_edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PunishmentTextModal(self.bot))

    @discord.ui.button(label="Editar Emojis", style=discord.ButtonStyle.secondary, emoji="😀", row=0)
    async def btn_edit_emojis(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PunishmentEmojiModal(self.bot))

    @discord.ui.button(label="Editar Cor (Hex)", style=discord.ButtonStyle.secondary, emoji="🎨", row=0)
    async def btn_edit_color(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PunishmentColorModal(self.bot))
        
    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="Canal de Tickets...", min_values=1, max_values=1, row=1)
    async def select_ticket_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        channel = select.values[0]
        await self.bot.db.execute("INSERT INTO config (guild_id, ticket_panel_channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET ticket_panel_channel_id = ?", (interaction.guild.id, channel.id, channel.id))
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Canal de Tickets vinculado: {channel.mention}", ephemeral=True)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="Canal de Alinhamento...", min_values=1, max_values=1, row=2)
    async def select_align_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        channel = select.values[0]
        await self.bot.db.execute("INSERT INTO config (guild_id, alignment_channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET alignment_channel_id = ?", (interaction.guild.id, channel.id, channel.id))
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Canal de Alinhamento vinculado: {channel.mention}", ephemeral=True)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="Canal de Punições (Logs do Membro)...", min_values=1, max_values=1, row=3)
    async def select_punish_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        channel = select.values[0]
        await self.bot.db.execute("UPDATE config SET punish_channel_id = ? WHERE guild_id = ?", (channel.id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Canal de Punições vinculado: {channel.mention}", ephemeral=True)


# ==============================================================================
# MODALS: EDIÇÃO DE TEXTO, EMOJIS E COR
# ==============================================================================
class PunishmentTextModal(discord.ui.Modal, title="Configurar Textos de Punição"):
    title_field = discord.ui.TextInput(label="Título da DM", placeholder="Ex: ⚠️ Notificação Administrativa", required=True, max_length=100)
    desc_field = discord.ui.TextInput(label="Descrição da DM", placeholder="Ex: Você recebeu um apontamento...", style=discord.TextStyle.paragraph, required=True, max_length=300)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await self.bot.db.execute("UPDATE config SET punish_title = ?, punish_desc = ? WHERE guild_id = ?", (self.title_field.value, self.desc_field.value, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message("✅ **Textos Atualizados!**", ephemeral=True)

class PunishmentEmojiModal(discord.ui.Modal, title="Configurar Emojis"):
    warn = discord.ui.TextInput(label="Emoji: Advertência (Warn)", placeholder="Ex: 🟧", required=True, max_length=50)
    feedback = discord.ui.TextInput(label="Emoji: Alinhamento (Feedback)", placeholder="Ex: 🟨", required=True, max_length=50)
    ban = discord.ui.TextInput(label="Emoji: Banimento/Exoneração", placeholder="Ex: 🟥", required=True, max_length=50)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await self.bot.db.execute("UPDATE config SET punish_emoji_warn = ?, punish_emoji_feedback = ?, punish_emoji_ban = ? WHERE guild_id = ?", (self.warn.value, self.feedback.value, self.ban.value, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message("✅ **Emojis Atualizados!**", ephemeral=True)

class PunishmentColorModal(discord.ui.Modal, title="Configurar Cor da Embed"):
    hex_code = discord.ui.TextInput(label="Cor HEX (Com ou sem #)", placeholder="Ex: FFD700 ou #FF0000", required=True, max_length=7)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        clean_hex = self.hex_code.value.replace("#", "").strip()
        try:
            int_color = int(clean_hex, 16)
        except ValueError:
            return await interaction.response.send_message("❌ **Cor Inválida!** Use formato HEX (Ex: FFD700).", ephemeral=True)
            
        await self.bot.db.execute("UPDATE config SET punish_color = ? WHERE guild_id = ?", (int_color, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ **Cor Atualizada!** (Preview: #{clean_hex})", ephemeral=True)


# ==============================================================================
# COG: SISTEMA DE PUNIÇÕES
# ==============================================================================
class Punishments(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def get_config(self, guild_id):
        # Fallback robusto para quando as colunas ainda não existirem (embora tenhamos forçado a migração)
        try:
            async with self.bot.db.execute("SELECT ticket_panel_channel_id, punish_title, punish_desc, punish_emoji_warn, punish_emoji_feedback, punish_emoji_ban, alignment_channel_id, punish_color, punish_channel_id FROM config WHERE guild_id = ?", (guild_id,)) as cursor:
                row = await cursor.fetchone()
        except:
            # Fallback (tenta pegar sem o canal novo se der erro)
            async with self.bot.db.execute("SELECT ticket_panel_channel_id, punish_title, punish_desc, punish_emoji_warn, punish_emoji_feedback, punish_emoji_ban, alignment_channel_id, punish_color FROM config WHERE guild_id = ?", (guild_id,)) as cursor:
                row = await cursor.fetchone()
                row = (*row, None) # Append None for punish_channel_id
        
        # Defaults
        if not row: return {
            'ticket_id': None, 'title': '⚠️ Notificação Administrativa', 
            'desc': 'Você recebeu um apontamento administrativo.',
            'e_warn': '🟧', 'e_feed': '🟨', 'e_ban': '🟥', 'align_id': None, 'color': 0xFFD700, 'punish_chan': None
        }
        
        # Safe Unpack
        return {
            'ticket_id': row[0], 
            'title': row[1] or '⚠️ Notificação Administrativa', 
            'desc': row[2] or 'Você recebeu um apontamento administrativo.',
            'e_warn': row[3] or '🟧', 'e_feed': row[4] or '🟨', 'e_ban': row[5] or '🟥',
            'align_id': row[6],
            'color': row[7] if len(row) > 7 and row[7] is not None else 0xFFD700,
            'punish_chan': row[8] if len(row) > 8 else None
        }

    # ==========================================================================
    # COMANDO: REGISTRAR WARN (User ou Cargo)
    # ==========================================================================
    @app_commands.command(name="registrar_warn", description="[Staff] Registra punição para um Membro ou Cargo inteiro.")
    @app_commands.describe(user="Membro Específico", role="Cargo (Aplica a todos)", punicao="Descrição da Punição (Ex: Banimento Temporário)", motivo="Motivo da Punição", passaporte="Passaporte (ID) do Jogador")
    async def registrar_warn(self, interaction: discord.Interaction, punicao: str, motivo: str, passaporte: str, user: Optional[discord.Member] = None, role: Optional[discord.Role] = None):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("⛔ **Sem permissão.** Staff Only.", ephemeral=True)

        if not user and not role:
            return await interaction.response.send_message("⚠️ Você precisa selecionar um **Usuário** ou um **Cargo**.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        conf = await self.get_config(interaction.guild.id)
        
        targets = []
        if user: targets.append(user)
        if role:
            for m in role.members:
                if m not in targets: targets.append(m)

        if not targets:
            return await interaction.followup.send("❌ Ninguém encontrado para punir.", ephemeral=True)

        count = 0
        punish_chan = interaction.guild.get_channel(conf['punish_chan']) if conf['punish_chan'] else None

        # Time
        now = datetime.datetime.now() - datetime.timedelta(hours=3) # Horario Brasilia Simplificado
        data_str = now.strftime("%d/%m/%Y %H:%M")

        for target in targets:
            if target.bot: continue
            
            # 1. DB Log
            # Saving 'punicao' in the 'conclusion' column to persist it for history
            await self.bot.db.execute("""
                INSERT INTO org_punishments (guild_id, user_id, staff_id, type, reason, conclusion)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (interaction.guild.id, target.id, interaction.user.id, "manual", motivo, punicao))
            
            # 2. Notification (Public Channel or DM)
            # Layout Premium / "Senior Dev" Style (Ticket Sync)
            embed = discord.Embed(
                description=f"", 
                color=conf['color']
            )
            
            # Header Formal
            embed.set_author(name="NOVA PUNIÇÃO APLICADA", icon_url=interaction.guild.icon.url if interaction.guild.icon else self.bot.user.display_avatar.url)

            separator = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

            # Campos Verticais com Separadores (Sem quebras extras)
            embed.add_field(name="Jogador Punido", value=f"{target.mention}", inline=False)
            embed.add_field(name="\u200b", value=separator, inline=False)

            embed.add_field(name="Passaporte", value=f"```{passaporte}```", inline=False)
            embed.add_field(name="\u200b", value=separator, inline=False)
            
            embed.add_field(name="Punição", value=f"```{punicao}```", inline=False)
            embed.add_field(name="\u200b", value=separator, inline=False)

            embed.add_field(name="Motivo", value=f"```{motivo}```", inline=False)
            embed.add_field(name="\u200b", value=separator, inline=False)
            
            embed.add_field(name="Aplicado por", value=f"{interaction.user.mention}", inline=False)
            embed.add_field(name="\u200b", value=separator, inline=False)

            embed.add_field(name="Data da Punição", value=f"```{data_str}```", inline=False)

            # Thumbnail no canto direito superior
            if self.bot.user.avatar:
                embed.set_thumbnail(url=self.bot.user.avatar.url)
            elif self.bot.user.default_avatar:
                embed.set_thumbnail(url=self.bot.user.default_avatar.url)
            
            # Ultra-Wide Fix
            embed.set_image(url="https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png")
            
            # Footer Minimalista
            embed.set_footer(text="Aura Bot") 

            try:
                if punish_chan:
                    await punish_chan.send(content=target.mention, embed=embed)
                else:
                    await target.send(embed=embed)
                count += 1
            except: pass 

        await self.bot.db.commit()
        
        dest_msg = f"no canal {punish_chan.mention}" if punish_chan else "nas DMs"
        await interaction.followup.send(f"✅ **Sucesso!** Punição registrada para **{len(targets)}** membros.\n📩 Notificações enviadas {dest_msg}.", ephemeral=True)

    # ==========================================================================
    # COMANDO: ALINHAMENTO (User ou Cargo)
    # ==========================================================================
    @app_commands.command(name="alinhamento", description="[Staff] Convoca Usuário ou Cargo para Alinhamento.")
    @app_commands.describe(user="Membro Específico", role="Cargo Inteiro")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def registrar_alignment(self, interaction: discord.Interaction, user: Optional[discord.Member] = None, role: Optional[discord.Role] = None):
        if not user and not role:
            return await interaction.response.send_message("⚠️ Selecione um **Usuário** ou **Cargo**.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        conf = await self.get_config(interaction.guild.id)
        
        align_chan = interaction.guild.get_channel(conf['align_id']) if conf['align_id'] else None
        
        if not align_chan:
            return await interaction.followup.send("❌ **Erro:** Canal de Alinhamento não configurado. Use `/painel_punicoes`.", ephemeral=True)

        ticket_chan = interaction.guild.get_channel(conf['ticket_id'])
        ticket_mention = ticket_chan.mention if ticket_chan else "o canal de tickets"

        # Monta menção
        mention_str = ""
        if role: mention_str += f"{role.mention} "
        if user: mention_str += f"{user.mention} "

        # Embed Profissional no Canal
        embed = discord.Embed(title="", color=conf['color'])
        embed.description = f"{mention_str}\n\nVocê foi convocado para uma reunião de **Alinhamento**.\n\nAbra um ticket em {ticket_mention} marcando {interaction.user.mention}."
        
        # Bot Avatar
        if self.bot.user.avatar: embed.set_thumbnail(url=self.bot.user.avatar.url)
        else: embed.set_thumbnail(url=self.bot.user.default_avatar.url)

        embed.set_image(url="https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png")
        embed.set_footer(text="Aura Bot")

        try:
            await align_chan.send(content=mention_str, embed=embed) # Mencionamos fora da embed para notificar, e embed bonita.
            await interaction.followup.send(f"✅ Convocação enviada em {align_chan.mention}!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro: {e}", ephemeral=True)

    # ==========================================================================
    # HELPER: FICHA / VIEW CLEAR
    # ==========================================================================
    class ClearHistoryView(discord.ui.View):
        def __init__(self, bot, target_id):
            super().__init__(timeout=60)
            self.bot = bot; self.target_id = target_id
            
        @discord.ui.button(label="Limpar Histórico", style=discord.ButtonStyle.danger, emoji="🗑️")
        async def clear_hist(self, interaction: discord.Interaction, button: discord.ui.Button):
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message("⛔ Apenas Administradores podem limpar o histórico.", ephemeral=True)
                
            await self.bot.db.execute("DELETE FROM org_punishments WHERE user_id = ? AND guild_id = ?", (self.target_id, interaction.guild.id))
            await self.bot.db.commit()
            await interaction.response.edit_message(content=f"✅ Histórico limpo por {interaction.user.mention}!", embed=None, view=None)

    async def _show_history(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("⛔ **Sem permissão.**", ephemeral=True)

        async with self.bot.db.execute("SELECT type, reason, conclusion, staff_id, timestamp FROM org_punishments WHERE user_id = ? AND guild_id = ? ORDER BY id DESC LIMIT 10", (user.id, interaction.guild.id)) as cursor:
            rows = await cursor.fetchall()
        
        conf = await self.get_config(interaction.guild.id)

        if not rows:
            return await interaction.response.send_message(f"📂 **Ficha Limpa!** Nenhuma anotação para {user.mention}.", ephemeral=True)

        # Title without emoji
        embed = discord.Embed(title=f"Ficha de conduta: {user.display_name}", color=conf['color'])
        embed.set_thumbnail(url=user.display_avatar.url)
        
        history_text = ""
        separator = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        
        for row in rows:
            p_type, reason, conclusion, staff_id, date = row
            staff = interaction.guild.get_member(staff_id)
            staff_mention = staff.mention if staff else f"<@{staff_id}>"
            
            # Formatação solicitada
            history_text += f"**Motivo:** {reason}\n"
            history_text += f"**Punição:** {conclusion}\n" # Conclusion holds the punishment arg
            history_text += f"**Aplicado por:** {staff_mention}\n"
            history_text += f"**Data:** {date}\n"
            history_text += f"{separator}\n"

        embed.description = history_text[:4000]
        embed.set_image(url="https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png")
        embed.set_footer(text="Aura Bot • Staff Only")

        view = self.ClearHistoryView(self.bot, user.id)
        await interaction.response.send_message(embed=embed, ephemeral=True, view=view)

    @app_commands.command(name="ficha", description="[Staff] Consulta a ficha criminal de um membro.")
    async def ficha(self, interaction: discord.Interaction, user: discord.Member):
        await self._show_history(interaction, user)

    @app_commands.command(name="historico", description="[Staff] Alias para /ficha.")
    async def historico(self, interaction: discord.Interaction, user: discord.Member):
        await self._show_history(interaction, user)

    # ==========================================================================
    # PAINEL DE CONFIGURAÇÃO (DASHBOARD)
    # ==========================================================================
    @app_commands.command(name="painel_punicoes", description="⚙️ Configurar Sistema de Punições.")
    @app_commands.checks.has_permissions(administrator=True)
    async def painel_punicoes(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        conf = await self.get_config(interaction.guild.id)
        
        t_chan = interaction.guild.get_channel(conf['ticket_id'])
        a_chan = interaction.guild.get_channel(conf['align_id'])
        p_chan = interaction.guild.get_channel(conf['punish_chan']) if conf['punish_chan'] else None
        
        embed = discord.Embed(title="⚙️ Configuração: Punições & Alinhamento", color=conf['color'])
        embed.description = "**Ajuste os parâmetros do sistema de gestão de equipe.**"
        
        embed.add_field(name="🎫 Canal Ticket", value=t_chan.mention if t_chan else "`Não Configurado`", inline=True)
        embed.add_field(name="📢 Canal Alinhamento", value=a_chan.mention if a_chan else "`Não Configurado`", inline=True)
        embed.add_field(name="🔨 Canal Punições", value=p_chan.mention if p_chan else "`Enviar na DM`", inline=True)
        
        embed.add_field(name="📝 Textos DM", value=f"**Título:** {conf['title']}\n**Desc:** {conf['desc'][:50]}...", inline=False)
        embed.add_field(name="😀 Emojis", value=f"{conf['e_warn']} Warn | {conf['e_feed']} Feedback | {conf['e_ban']} Ban", inline=False)
        
        # Color Preview
        hex_preview = hex(conf['color']).replace("0x", "").upper()
        embed.add_field(name="🎨 Cor Embed", value=f"#{hex_preview}", inline=False)
        
        embed.set_image(url="https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png") # Ultra Wide
        embed.set_footer(text="Use os botões para editar.")
        
        await interaction.followup.send(embed=embed, view=PunishmentDashboardView(self.bot, interaction.user))

async def setup(bot):
    await bot.add_cog(Punishments(bot))
