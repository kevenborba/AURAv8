import discord
import datetime
import asyncio
import sys
import os
import html
import uuid
from discord.ext import commands
from discord import app_commands, ui
import aiohttp

try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import config
except ImportError:
    class config:
        EMBED_COLOR = 0x992d22

# ====================================================
# 🎨 GERADOR DE TRANSCRIPT HTML
# ====================================================
def _gerar_html_transcript(ticket_channel, messages, opener, assumed_by, closer):
    html_content = f"""<!DOCTYPE html><html lang="pt-br"><head><meta charset="UTF-8"><title>Transcript {ticket_channel.name}</title>
    <style>body{{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;background:#36393f;color:#dcddde;padding:20px}}.container{{max-width:800px;margin:0 auto;background:#2f3136;padding:20px;border-radius:8px}}
    .header{{border-bottom:1px solid #40444b;padding-bottom:10px;margin-bottom:20px}}.msg{{display:flex;margin-bottom:15px}}.avatar{{width:40px;height:40px;border-radius:50%;margin-right:15px}}
    .content{{display:flex;flex-direction:column}}.author{{font-weight:bold;color:#fff}}.timestamp{{font-size:12px;color:#72767d;margin-left:8px}}
    a{{color:#00b0f4;text-decoration:none}}img{{max-width:400px;border-radius:5px;margin-top:5px}}</style></head><body>
    <div class="container"><div class="header"><h1>#{ticket_channel.name}</h1><p>Gerado em: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}</p></div>"""
    
    for msg in messages:
        if msg.is_system(): continue
        content = html.escape(msg.content).replace("\n", "<br>")
        if msg.attachments:
            for att in msg.attachments: 
                content += f'<br><a href="{att.url}" target="_blank">📎 Anexo: {att.filename}</a>'
                if att.content_type and "image" in att.content_type:
                    content += f'<br><img src="{att.url}">'
        avatar = msg.author.display_avatar.url if msg.author else "https://cdn.discordapp.com/embed/avatars/0.png"
        name = html.escape(msg.author.display_name) if msg.author else "User"
        timestamp = msg.created_at.strftime("%H:%M")
        html_content += f'<div class="msg"><img src="{avatar}" class="avatar"><div class="content"><div class="author">{name}<span class="timestamp">{timestamp}</span></div><div>{content}</div></div></div>'
    
    return html_content + "</div></body></html>"

def parse_emoji(custom_emoji):
    if not custom_emoji: return None
    custom_emoji = custom_emoji.strip()
    if custom_emoji.startswith("<"):
        try: return discord.PartialEmoji.from_str(custom_emoji)
        except: pass
    return custom_emoji

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if not os.path.exists('transcripts'):
            os.makedirs('transcripts')

    # ====================================================
    # 🖥️ PAINEL ADMIN
    # ====================================================
    async def cog_load(self):
        # 1. Registra a View de Controle (Botões dentro do Ticket)
        # Precisamos pegar os emojis do banco? 
        # Para persistência funcionar, basta registrar a classe com os custom_ids corretos.
        # Os emojis são visuais, já estão na mensagem. O callback é o que importa.
        self.bot.add_view(TicketControlView(self.bot))
        
        # 2. Registra a View de Abertura (Painel Principal)
        # Como ela é dinâmica (depende das categorias), precisamos reconstruir uma para cada guild
        print("🔄 [TICKETS] Restaurando views persistentes...")
        try:
            # Pega todas as guilds que tem painel configurado
            async with self.bot.db.execute("SELECT guild_id FROM config WHERE ticket_panel_channel_id IS NOT NULL") as cursor:
                guilds = await cursor.fetchall()
            
            for (g_id,) in guilds:
                # Pega categorias dessa guild
                async with self.bot.db.execute("SELECT id, label, description, emoji FROM ticket_categories WHERE guild_id = ?", (g_id,)) as cursor:
                    cats = await cursor.fetchall()
                
                if cats:
                    # Recria a view
                    view = UserTicketView(self.bot, self, cats)
                    self.bot.add_view(view)
                    
            print(f"✅ [TICKETS] Views restauradas para {len(guilds)} servidores.")
        except Exception as e:
            print(f"❌ [TICKETS] Erro ao restaurar views: {e}")

    @app_commands.command(name="painel_tickets", description="Gerenciador Avançado de Tickets")
    @app_commands.checks.has_permissions(administrator=True)
    async def ticket_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.send_admin_panel(interaction)

    async def send_admin_panel(self, interaction: discord.Interaction, is_edit=False):
        async with self.bot.db.execute("SELECT * FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()
            cfg = dict(zip([d[0] for d in cursor.description], row)) if row else {}

        async with self.bot.db.execute("SELECT COUNT(*) FROM ticket_categories WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            cat_count = (await cursor.fetchone())[0]

        cat_channel = self.bot.get_channel(cfg.get('ticket_category_id'))
        role = interaction.guild.get_role(cfg.get('ticket_support_role_id'))
        panel_chan = self.bot.get_channel(cfg.get('ticket_panel_channel_id'))
        # Novos campos de log
        logs_chan = self.bot.get_channel(cfg.get('ticket_logs_id'))
        rating_chan = self.bot.get_channel(cfg.get('rating_channel_id'))
        
        viewer_url = cfg.get('ticket_viewer_url') or "⚠️ Configure a URL Base!"
        
        embed = discord.Embed(title="🎫 Gerenciador de Tickets", color=config.EMBED_COLOR)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        status = lambda x: f"✅ {x.mention}" if x else "🔴 Não definido"
        
        embed.description = (
            f"**Status Geral:**\n"
            f"📂 Categoria Padrão: {status(cat_channel)}\n"
            f"🛡️ Cargo Suporte: {status(role)}\n"
            f"📢 Canal do Painel: {status(panel_chan)}\n\n"
            f"**Logs & Auditoria:**\n"
            f"📜 Logs de Tickets: {status(logs_chan)}\n"
            f"⭐ Logs de Avaliação: {status(rating_chan)}\n"
            f"🔗 URL Transcripts: `{viewer_url}`\n\n"
            f"📑 **Categorias Criadas:** {cat_count}\n"
        )
        
        view = AdminTicketView(self.bot, self)
        if is_edit: await interaction.edit_original_response(embed=embed, view=view)
        else: await interaction.followup.send(embed=embed, view=view)

    # ====================================================
    # 🛫 CRIAR TICKET
    # ====================================================
    async def create_ticket(self, interaction, category_id, reason):
        async with self.bot.db.execute("""
            SELECT ticket_category_id, ticket_support_role_id, ticket_count, 
                   tk_emoji_claim, tk_emoji_admin, tk_emoji_close, ticket_color, tk_emoji_voice 
            FROM config WHERE guild_id = ?
        """, (interaction.guild.id,)) as cursor:
            res = await cursor.fetchone()
            
        if not res or not res[1]:
            return await interaction.followup.send("❌ Sistema em manutenção ou não configurado.", ephemeral=True)
        
        global_cat_id, role_id, count, e_claim, e_admin, e_close, t_color, e_voice = res
        count = (count or 0) + 1
        
        async with self.bot.db.execute("SELECT label, emoji, location_id FROM ticket_categories WHERE id = ?", (category_id,)) as cursor:
            cat_data = await cursor.fetchone()
            cat_name = cat_data[0] if cat_data else "Ticket"
            cat_emoji = cat_data[1] if cat_data else "🎫"
            specific_cat_id = cat_data[2] if cat_data else None

        await self.bot.db.execute("UPDATE config SET ticket_count = ? WHERE guild_id = ?", (count, interaction.guild.id))
        await self.bot.db.commit()

        target_category_id = specific_cat_id if specific_cat_id else global_cat_id
        category = self.bot.get_channel(target_category_id)
        if not category: return await interaction.followup.send("❌ Categoria Discord inválida.", ephemeral=True)

        role = interaction.guild.get_role(role_id)
        final_color = t_color if t_color else config.EMBED_COLOR
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            role: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        
        ch_name = f"{cat_emoji}・{cat_name}・{count:04d}"
        
        try:
            ticket_channel = await interaction.guild.create_text_channel(name=ch_name, category=category, overwrites=overwrites)
        except Exception as e:
            return await interaction.followup.send(f"❌ Erro ao criar canal: {e}", ephemeral=True)

        await self.bot.db.execute("INSERT INTO active_tickets (channel_id, guild_id, user_id, opened_at) VALUES (?, ?, ?, ?)", (ticket_channel.id, interaction.guild.id, interaction.user.id, datetime.datetime.now().isoformat()))
        await self.bot.db.commit()

        embed = discord.Embed(color=final_color)
        embed.set_author(name=f"Atendimento Iniciado | {cat_name}", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
        embed.description = f"Olá {interaction.user.mention}, seja bem-vindo(a).\nNossa equipe foi notificada e irá atendê-lo em breve.\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        embed.add_field(name="👤 Solicitante", value=interaction.user.mention, inline=True)
        embed.add_field(name="📂 Categoria", value=f"`{cat_name}`\n\n", inline=True)
        embed.add_field(name="📝 Motivo do Contato", value=f"```txt\n{reason}\n```", inline=False)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text=f"Ticket ID: #{count:04d} • {interaction.guild.name}", icon_url=self.bot.user.display_avatar.url)
        embed.timestamp = datetime.datetime.now()
        
        view = TicketControlView(self.bot, e_claim, e_admin, e_close, e_voice)
        await ticket_channel.send(embed=embed, view=view)
        await interaction.followup.send(f"✅ Ticket criado: {ticket_channel.mention}", ephemeral=True)

# ====================================================
# 🎛️ MODAIS
# ====================================================

class TicketReasonModal(ui.Modal, title="Abrir Atendimento"):
    reason = ui.TextInput(label="Qual o motivo do contato?", style=discord.TextStyle.paragraph, placeholder="Descreva aqui...")
    def __init__(self, bot, cog, cat_id):
        super().__init__()
        self.bot = bot; self.cog = cog; self.cat_id = cat_id
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.cog.create_ticket(interaction, self.cat_id, self.reason.value)

class MemberControlModal(ui.Modal):
    def __init__(self, mode):
        super().__init__(title="Adicionar Membro" if mode == "add" else "Remover Membro")
        self.mode = mode; self.uid = ui.TextInput(label="ID do Usuário", placeholder="Ex: 123456789...")
        self.add_item(self.uid)
    async def on_submit(self, interaction: discord.Interaction):
        try:
            user = await interaction.guild.fetch_member(int(self.uid.value))
            if self.mode == "add":
                await interaction.channel.set_permissions(user, read_messages=True, send_messages=True)
                msg = f"✅ {user.mention} adicionado ao ticket."
            else:
                await interaction.channel.set_permissions(user, overwrite=None)
                msg = f"⛔ {user.mention} removido do ticket."
            await interaction.response.send_message(msg)
        except: await interaction.response.send_message("❌ Usuário inválido.", ephemeral=True)

class RenameTicketModal(ui.Modal, title="Renomear Ticket"):
    new_name = ui.TextInput(label="Novo Nome", placeholder="Ex: duvida-resolvida")
    new_emoji = ui.TextInput(label="Novo Emoji (Opcional)", placeholder="Ex: 🔒", required=False, max_length=5)
    async def on_submit(self, interaction: discord.Interaction):
        final_name = self.new_name.value
        if self.new_emoji.value.strip(): final_name = f"{self.new_emoji.value.strip()}・{final_name}"
        elif '・' in interaction.channel.name: final_name = f"{interaction.channel.name.split('・')[0]}・{final_name}"
        await interaction.channel.edit(name=final_name)
        await interaction.response.send_message(f"✅ Ticket renomeado para `{final_name}`.", ephemeral=True)

class VisualConfigModal(ui.Modal, title="🎨 Visual do Painel"):
    def __init__(self, bot, cog, origin, cur_title, cur_desc, cur_color, cur_banner, cur_viewer):
        super().__init__()
        self.bot = bot; self.cog = cog; self.origin = origin
        self.t_title = ui.TextInput(label="Título Principal", default=cur_title or "ATENDIMENTO", required=True)
        self.t_desc = ui.TextInput(label="Regras/Corpo", style=discord.TextStyle.paragraph, default=cur_desc or "Abra um ticket...", required=True)
        self.t_color = ui.TextInput(label="Cor HEX", default=f"#{cur_color:06X}" if cur_color else "#000000", min_length=7, max_length=7)
        self.t_banner = ui.TextInput(label="URL Banner", required=False, default=cur_banner or "")
        self.t_viewer = ui.TextInput(label="URL Base Transcripts", required=False, default=cur_viewer or "", placeholder="Ex: https://lust.shardweb.app/transcripts/")
        self.add_item(self.t_title); self.add_item(self.t_desc); self.add_item(self.t_color); self.add_item(self.t_banner); self.add_item(self.t_viewer)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try: col = int(self.t_color.value.replace("#", ""), 16)
        except: return await interaction.followup.send("❌ Cor inválida!")
        await self.bot.db.execute("UPDATE config SET ticket_title=?, ticket_desc=?, ticket_color=?, ticket_banner=?, ticket_viewer_url=? WHERE guild_id=?", (self.t_title.value, self.t_desc.value, col, self.t_banner.value, self.t_viewer.value, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.followup.send("✅ Configuração Salva!")
        await self.cog.send_admin_panel(self.origin, is_edit=True)

class InternalButtonsModal(ui.Modal, title="⚙️ Botões Internos"):
    def __init__(self, bot, cog, origin, e_claim, e_admin, e_close, e_cancel, e_voice):
        super().__init__()
        self.bot = bot; self.cog = cog; self.origin = origin
        self.i_claim = ui.TextInput(label="Emoji Assumir Ticket", default=e_claim or "🙋‍♂️", required=True)
        self.i_admin = ui.TextInput(label="Emoji Adicionar Pessoa", default=e_admin or "👤", required=True)
        self.i_close = ui.TextInput(label="Emoji Fechar Ticket", default=e_close or "🔒", required=True)
        self.i_cancel = ui.TextInput(label="Emoji Cancelar Fechamento", default=e_cancel or "🛑", required=True)
        self.i_voice = ui.TextInput(label="Emoji Criar Call", default=e_voice or "🔊", required=True)
        self.add_item(self.i_claim); self.add_item(self.i_admin); self.add_item(self.i_close); self.add_item(self.i_cancel); self.add_item(self.i_voice)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.execute("UPDATE config SET tk_emoji_claim=?, tk_emoji_admin=?, tk_emoji_close=?, tk_emoji_cancel=?, tk_emoji_voice=? WHERE guild_id=?", (self.i_claim.value, self.i_admin.value, self.i_close.value, self.i_cancel.value, self.i_voice.value, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.followup.send("✅ Botões atualizados!")
        await self.cog.send_admin_panel(self.origin, is_edit=True)

class CategoryModal(ui.Modal):
    def __init__(self, bot, cog, origin, category_id=None, current_name="", current_desc="", current_emoji="", current_loc=None):
        super().__init__(title="Editar Categoria" if category_id else "Nova Categoria")
        self.bot = bot; self.cog = cog; self.origin = origin; self.cat_id = category_id
        self.c_name = ui.TextInput(label="Nome", default=current_name, placeholder="Ex: Financeiro")
        self.c_desc = ui.TextInput(label="Descrição", default=current_desc, placeholder="Ex: Problemas de pagamento...")
        self.c_emoji = ui.TextInput(label="Emoji", default=current_emoji, placeholder="💰")
        self.c_loc = ui.TextInput(label="ID Categoria Discord (Opcional)", default=str(current_loc) if current_loc else "", required=False)
        self.add_item(self.c_name); self.add_item(self.c_desc); self.add_item(self.c_emoji); self.add_item(self.c_loc)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        loc_id = int(self.c_loc.value) if self.c_loc.value.isdigit() else None
        if self.cat_id:
            await self.bot.db.execute("UPDATE ticket_categories SET label=?, description=?, emoji=?, location_id=? WHERE id=?", (self.c_name.value, self.c_desc.value, self.c_emoji.value, loc_id, self.cat_id))
            msg = "✅ Categoria Atualizada!"
        else:
            await self.bot.db.execute("INSERT INTO ticket_categories (guild_id, label, description, emoji, location_id) VALUES (?, ?, ?, ?, ?)", (interaction.guild.id, self.c_name.value, self.c_desc.value, self.c_emoji.value, loc_id))
            msg = "✅ Categoria Criada!"
        await self.bot.db.commit()
        await interaction.followup.send(msg)
        await self.cog.send_admin_panel(self.origin, is_edit=True)

# ====================================================
# ⭐ SISTEMA DE AVALIAÇÃO (RATING)
# ====================================================
class RatingView(ui.View):
    def __init__(self, bot, guild, staff_member, transcript_url):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild = guild
        self.staff_member = staff_member
        self.transcript_url = transcript_url
    
    async def rate(self, interaction, stars):
        # 1. Salva no Banco
        staff_id = self.staff_member.id if self.staff_member else 0
        await self.bot.db.execute("INSERT INTO staff_ratings (guild_id, staff_id, user_id, stars, date) VALUES (?, ?, ?, ?, ?)", (self.guild.id, staff_id, interaction.user.id, stars, datetime.datetime.now().isoformat()))
        await self.bot.db.commit()
        
        # 2. Envia Embed para o Canal de Log
        async with self.bot.db.execute("SELECT rating_channel_id FROM config WHERE guild_id = ?", (self.guild.id,)) as cursor:
            res = await cursor.fetchone()
        
        if res and res[0]:
            rating_channel = self.guild.get_channel(res[0])
            if rating_channel:
                embed_log = discord.Embed(title="⭐ Nova Avaliação Recebida", color=0xf1c40f) # Dourado
                embed_log.set_thumbnail(url=self.bot.user.display_avatar.url)
                
                stars_emoji = "⭐" * stars
                embed_log.add_field(name="👤 Cliente", value=interaction.user.mention, inline=True)
                embed_log.add_field(name="👮 Staff Avaliado", value=self.staff_member.mention if self.staff_member else "Ninguém", inline=True)
                embed_log.add_field(name="📊 Nota", value=f"{stars_emoji} ({stars}/5)", inline=False)
                
                # Link do Transcript
                if self.transcript_url and self.transcript_url != "#":
                    embed_log.add_field(name="🔗 Transcript", value=f"[**Acessar Atendimento**]({self.transcript_url})", inline=False)
                
                embed_log.set_footer(text=f"ID Cliente: {interaction.user.id}")
                embed_log.timestamp = datetime.datetime.now()
                
                try: await rating_channel.send(embed=embed_log)
                except: pass

        # 3. Atualiza DM com Agradecimento
        embed_thanks = discord.Embed(title="Obrigado!", description=f"Sua avaliação de **{stars} estrelas** foi registrada com sucesso.", color=discord.Color.green())
        await interaction.response.edit_message(embed=embed_thanks, view=None)

    @ui.button(emoji="1️⃣", style=discord.ButtonStyle.secondary)
    async def b1(self, i, b): await self.rate(i, 1)
    @ui.button(emoji="2️⃣", style=discord.ButtonStyle.secondary)
    async def b2(self, i, b): await self.rate(i, 2)
    @ui.button(emoji="3️⃣", style=discord.ButtonStyle.secondary)
    async def b3(self, i, b): await self.rate(i, 3)
    @ui.button(emoji="4️⃣", style=discord.ButtonStyle.secondary)
    async def b4(self, i, b): await self.rate(i, 4)
    @ui.button(emoji="5️⃣", style=discord.ButtonStyle.success)
    async def b5(self, i, b): await self.rate(i, 5)

# ====================================================
# VIEWS CONTROLADORAS
# ====================================================

class TicketControlView(ui.View):
    def __init__(self, bot, e_claim=None, e_admin=None, e_close=None, e_voice=None):
        super().__init__(timeout=None)
        self.bot = bot
        if e_claim: self.claim_ticket.emoji = parse_emoji(e_claim)
        if e_admin: self.admin_panel.emoji = parse_emoji(e_admin)
        if e_close: self.close_ticket.emoji = parse_emoji(e_close)
        if e_voice: self.create_voice.emoji = parse_emoji(e_voice)

    @ui.button(label="Assumir Ticket", style=discord.ButtonStyle.secondary, custom_id="tk_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        await self.bot.db.execute("UPDATE active_tickets SET claimed_by = ? WHERE channel_id = ?", (interaction.user.id, interaction.channel.id))
        await self.bot.db.commit()
        message = interaction.message
        embed = message.embeds[0]
        new_fields = [f for f in embed.fields if "Staff Responsável" not in f.name]
        embed.clear_fields()
        for f in new_fields: embed.add_field(name=f.name, value=f.value, inline=f.inline)
        embed.add_field(name="👮 Staff Responsável", value=interaction.user.mention, inline=True)
        button.disabled = True
        button.label = f"Assumido por {interaction.user.name}"
        await message.edit(embed=embed, view=self)
        await interaction.followup.send(f"✅ **{interaction.user.mention}** assumiu o ticket!", ephemeral=True)

    @ui.button(label="Criar Call", style=discord.ButtonStyle.secondary, emoji="🔊", custom_id="tk_voice")
    async def create_voice(self, interaction: discord.Interaction, button: ui.Button):
        # Verifica permissão (apenas quem consegue ver o ticket pode criar? Não, apenas staff)
        # O ideal é verificar se o usuário tem permissão de gerenciar mensagens ou cargo suporte
        # Mas assumindo que quem vê o botão tem permissão de ver o canal...
        # Vamos restringir para quem tem permissão de Manage Channels ou é o Staff do ticket?
        # Simplificando: Se ele tem permissão de enviar mensagem no ticket e não é o bot
        
        await interaction.response.defer(ephemeral=True)
        
        # Nome da Call
        voice_name = f"Call - {interaction.channel.name}"
        
        # Verifica se já existe na categoria
        existing_voice = discord.utils.get(interaction.channel.category.voice_channels, name=voice_name)
        if existing_voice:
            return await interaction.followup.send(f"⚠️ Já existe uma call criada para este ticket: {existing_voice.mention}", ephemeral=True)
            
        try:
            # Cria a call com as mesmas permissões do canal de texto
            voice_channel = await interaction.guild.create_voice_channel(
                name=voice_name,
                category=interaction.channel.category,
                overwrites=interaction.channel.overwrites
            )
            await interaction.followup.send(f"✅ Call criada com sucesso: {voice_channel.mention}", ephemeral=True)
            await interaction.channel.send(f"🔊 **Call de Atendimento criada:** {voice_channel.mention}")
        except Exception as e:
            await interaction.followup.send(f"❌ Erro ao criar call: {e}", ephemeral=True)

    @ui.button(label="Painel Admin", style=discord.ButtonStyle.secondary, custom_id="tk_admin")
    async def admin_panel(self, interaction: discord.Interaction, button: ui.Button):
        view = TicketAdminOptionsView(self.bot)
        await interaction.response.send_message("🛠️ **Painel Administrativo do Ticket**", view=view, ephemeral=True)

    @ui.button(label="Fechar Ticket", style=discord.ButtonStyle.secondary, custom_id="tk_close")
    async def close_ticket(self, interaction: discord.Interaction, button: ui.Button):
        async with self.bot.db.execute("SELECT tk_emoji_cancel FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            res = await cursor.fetchone()
        cancel_emoji = res[0] if res and res[0] else "🛑"
        view = CloseTimerView(self.bot, interaction.user, cancel_emoji)
        await interaction.response.send_message("Fechando ticket em **20** segundos...\nClique abaixo para cancelar.", view=view)
        msg = await interaction.original_response()
        view.task = asyncio.create_task(perform_ticket_close_timer(self.bot, interaction.channel, interaction.user, view, msg))

class TicketAdminOptionsView(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot
    @ui.button(label="Adicionar Pessoa", emoji="➕", style=discord.ButtonStyle.secondary)
    async def add_member(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(MemberControlModal("add"))
    @ui.button(label="Remover Pessoa", emoji="➖", style=discord.ButtonStyle.secondary)
    async def remove_member(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(MemberControlModal("remove"))
    @ui.button(label="Notificar Autor", emoji="🔔", style=discord.ButtonStyle.primary)
    async def notify_user(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer(ephemeral=True)
        async with self.bot.db.execute("SELECT user_id FROM active_tickets WHERE channel_id = ?", (interaction.channel.id,)) as cursor:
            res = await cursor.fetchone()
        if res:
            try:
                user = await interaction.guild.fetch_member(res[0])
                await interaction.channel.send(f"🔔 {user.mention}, a equipe aguarda sua resposta!")
                embed_dm = discord.Embed(title="🔔 Atualização no seu Ticket", color=config.EMBED_COLOR)
                embed_dm.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
                embed_dm.set_thumbnail(url=self.bot.user.display_avatar.url)
                embed_dm.description = (f"Olá {user.mention},\nNossa equipe acaba de enviar uma solicitação no seu atendimento.")
                embed_dm.add_field(name="📍 Acesso Rápido", value=f"[Clique aqui para ir ao Ticket]({interaction.channel.jump_url})", inline=False)
                embed_dm.set_footer(text="Fique atento ao chat.", icon_url=self.bot.user.display_avatar.url)
                embed_dm.timestamp = datetime.datetime.now()
                try: await user.send(embed=embed_dm); feedback = "✅ Usuário notificado no Chat e via DM."
                except: feedback = "⚠️ Usuário notificado no Chat (DM Fechada)."
                await interaction.followup.send(feedback, ephemeral=True)
            except: await interaction.followup.send("❌ Autor não encontrado.", ephemeral=True)
        else: await interaction.followup.send("❌ Autor não encontrado.", ephemeral=True)
    @ui.button(label="Renomear Ticket", emoji="✏️", style=discord.ButtonStyle.secondary)
    async def rename_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(RenameTicketModal())

class CloseTimerView(ui.View):
    def __init__(self, bot, user, cancel_emoji):
        super().__init__(timeout=25)
        self.bot = bot; self.user = user; self.cancelled = False; self.task = None
        self.cancel.emoji = parse_emoji(cancel_emoji)

    @ui.button(label="CANCELAR FECHAMENTO", style=discord.ButtonStyle.success)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        self.cancelled = True
        if self.task: self.task.cancel()
        await interaction.message.delete()
        await interaction.response.send_message(f"✅ Fechamento cancelado por {interaction.user.mention}.", ephemeral=False)
        self.stop()

async def perform_ticket_close_timer(bot, channel, closed_by_user, view, message):
    try:
        for i in range(20, 0, -5):
            if view.cancelled: return
            try:
                await message.edit(content=f"Fechando ticket em **{i}** segundos...\nClique abaixo para cancelar.")
                await asyncio.sleep(5)
            except: pass

        if view.cancelled: return
        
        # === 1. DADOS ===
        async with bot.db.execute("SELECT user_id, opened_at, claimed_by FROM active_tickets WHERE channel_id = ?", (channel.id,)) as cursor:
            t_data = await cursor.fetchone()
        opener_id, opened_at_str, claimer_id = t_data if t_data else (None, None, None)
        
        opener = channel.guild.get_member(opener_id) if opener_id else None
        claimer = channel.guild.get_member(claimer_id) if claimer_id else None
        
        opened_dt = datetime.datetime.fromisoformat(opened_at_str) if opened_at_str else datetime.datetime.now()
        closed_dt = datetime.datetime.now()

        # === 2. TRANSCRIPT ===
        messages = [msg async for msg in channel.history(limit=None, oldest_first=True)]
        html_source = _gerar_html_transcript(channel, messages, opener, claimer, closed_by_user)
        
        file_name = f"transcript-{channel.guild.id}-{uuid.uuid4()}.html"
        file_path = os.path.join("transcripts", file_name)
        with open(file_path, "w", encoding="utf-8") as f: f.write(html_source)

        async with bot.db.execute("SELECT ticket_viewer_url, ticket_logs_id FROM config WHERE guild_id = ?", (channel.guild.id,)) as cursor:
            res_cfg = await cursor.fetchone()
        
        base_url = res_cfg[0] if res_cfg and res_cfg[0] else ""
        logs_id = res_cfg[1] if res_cfg else None
        if base_url and not base_url.endswith('/'): base_url += '/'
        final_url = f"{base_url}{file_name}" if base_url else "#"

        # === 3. LOG DE TICKET ===
        if logs_id:
            log_chan = bot.get_channel(logs_id)
            if log_chan:
                emb = discord.Embed(title=f"TICKET FECHADO: {channel.name.upper()}", color=config.EMBED_COLOR, description=f"[**Ver Transcript**]({final_url})")
                emb.add_field(name="Aberto por", value=f"{opener.mention} ({opener.id})" if opener else "N/A")
                emb.add_field(name="Assumido por", value=f"{claimer.mention} ({claimer.id})" if claimer else "Ninguém")
                emb.add_field(name="Fechado por", value=f"{closed_by_user.mention} ({closed_by_user.id})")
                emb.add_field(name="Datas", value=f"Inicio: <t:{int(channel.created_at.timestamp())}:F>\nFim: <t:{int(closed_dt.timestamp())}:F>")
                emb.set_thumbnail(url=bot.user.display_avatar.url)
                await log_chan.send(embed=emb)

        # === 4. DM DE AVALIAÇÃO (MELHORADA) ===
        if opener:
            try:
                # Embed Bonito na DM
                dm_embed = discord.Embed(title="Avaliação de Atendimento", description="Olá! Seu ticket foi encerrado.\nPor favor, reserve um momento para avaliar o atendimento recebido.", color=config.EMBED_COLOR)
                dm_embed.add_field(name="👮 Atendido por", value=claimer.mention if claimer else "Equipe", inline=False)
                dm_embed.add_field(name="📅 Data", value=discord.utils.format_dt(datetime.datetime.now(), style='f'), inline=False)
                dm_embed.set_thumbnail(url=bot.user.display_avatar.url)
                dm_embed.set_footer(text="Selecione de 1 a 5 estrelas abaixo")

                # Passamos o transcript_url para a View
                await opener.send(embed=dm_embed, view=RatingView(bot, channel.guild, claimer, final_url))
            except Exception as e:
                print(f"Erro ao enviar DM de avaliação: {e}")
            
    except asyncio.CancelledError: pass
    except Exception as e: print(f"Erro no fechamento: {e}")
    finally:
        if not view.cancelled:
            await bot.db.execute("DELETE FROM active_tickets WHERE channel_id = ?", (channel.id,))
            await bot.db.commit()
            
            # === 5. BACKUP WEBHOOK ===
            async with bot.db.execute("SELECT ticket_backup_webhook FROM config WHERE guild_id = ?", (channel.guild.id,)) as cursor:
                res_bkp = await cursor.fetchone()
            
            webhook_url = res_bkp[0] if res_bkp else None
            
            if webhook_url:
                try:
                    async with aiohttp.ClientSession() as session:
                        webhook = discord.Webhook.from_url(webhook_url, session=session)
                        # Re-open file to send
                        with open(file_path, "rb") as f:
                            file_to_send = discord.File(f, filename=file_name)
                            
                            # Embed estilo Log (Mais detalhado)
                            embed_bkp = discord.Embed(title=f"BACKUP TICKET: {channel.name.upper()}", color=discord.Color.light_grey())
                            if final_url and final_url != "#":
                                embed_bkp.description = f"[**Ver Transcript Online**]({final_url})"
                            
                            embed_bkp.add_field(name="Aberto por", value=f"{opener.mention} ({opener.id})" if opener else "N/A")
                            embed_bkp.add_field(name="Assumido por", value=f"{claimer.mention} ({claimer.id})" if claimer else "Ninguém")
                            embed_bkp.add_field(name="Fechado por", value=f"{closed_by_user.mention} ({closed_by_user.id})")
                            embed_bkp.add_field(name="Datas", value=f"Inicio: <t:{int(channel.created_at.timestamp())}:F>\nFim: <t:{int(closed_dt.timestamp())}:F>")
                            embed_bkp.set_thumbnail(url=bot.user.display_avatar.url)
                            embed_bkp.timestamp = datetime.datetime.now()
                            
                            await webhook.send(embed=embed_bkp, file=file_to_send, username="Ticket Backup System", avatar_url=bot.user.display_avatar.url)
                except Exception as e:
                    print(f"Erro ao enviar backup webhook: {e}")

            # === DELETAR VOICE CHANNEL ASSOCIADO ===
            try:
                voice_name = f"Call - {channel.name}"
                if channel.category:
                    voice_channel = discord.utils.get(channel.category.voice_channels, name=voice_name)
                    if voice_channel:
                        await voice_channel.delete()
            except Exception as e:
                print(f"Erro ao deletar call do ticket: {e}")

            await channel.delete()

# ====================================================
# VIEWS CONFIGURAÇÃO
# ====================================================

class BackupConfigModal(ui.Modal, title="📦 Backup via Webhook"):
    def __init__(self, bot, cog, origin, cur_webhook):
        super().__init__()
        self.bot = bot; self.cog = cog; self.origin = origin
        self.webhook = ui.TextInput(label="Webhook URL", placeholder="https://discord.com/api/webhooks/...", required=False, default=cur_webhook or "")
        self.add_item(self.webhook)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.execute("UPDATE config SET ticket_backup_webhook=? WHERE guild_id=?", (self.webhook.value, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.followup.send("✅ Webhook de Backup atualizado!")
        await self.cog.send_admin_panel(self.origin, is_edit=True)

class GlobalSettingsView(ui.View):
    def __init__(self, bot, cog, origin_interaction):
        super().__init__(timeout=120)
        self.bot = bot; self.cog = cog; self.origin = origin_interaction
    @ui.button(label="Editar Visual", emoji="🎨", style=discord.ButtonStyle.primary)
    async def edit_visual(self, interaction: discord.Interaction, button: ui.Button):
        async with self.bot.db.execute("SELECT ticket_title, ticket_desc, ticket_color, ticket_banner, ticket_viewer_url FROM config WHERE guild_id=?", (interaction.guild.id,)) as c:
            res = await c.fetchone()
        t, d, c, b, v = res if res else (None, None, None, None, None)
        await interaction.response.send_modal(VisualConfigModal(self.bot, self.cog, self.origin, t, d, c, b, v))
    @ui.button(label="Botões Internos", emoji="⚙️", style=discord.ButtonStyle.secondary)
    async def edit_buttons(self, interaction: discord.Interaction, button: ui.Button):
        async with self.bot.db.execute("SELECT tk_emoji_claim, tk_emoji_admin, tk_emoji_close, tk_emoji_cancel, tk_emoji_voice FROM config WHERE guild_id=?", (interaction.guild.id,)) as c:
            res = await c.fetchone()
        ec, ea, el, ecan, ev = res if res else (None, None, None, None, None)
        await interaction.response.send_modal(InternalButtonsModal(self.bot, self.cog, self.origin, ec, ea, el, ecan, ev))
    @ui.button(label="Configurar Backup", emoji="📦", style=discord.ButtonStyle.secondary, row=1)
    async def config_backup(self, interaction: discord.Interaction, button: ui.Button):
        async with self.bot.db.execute("SELECT ticket_backup_webhook FROM config WHERE guild_id=?", (interaction.guild.id,)) as c:
            res = await c.fetchone()
        wh = res[0] if res else None
        await interaction.response.send_modal(BackupConfigModal(self.bot, self.cog, self.origin, wh))
    @ui.select(cls=discord.ui.RoleSelect, placeholder="Definir Cargo Suporte", row=2)
    async def sel_role(self, interaction: discord.Interaction, select: ui.RoleSelect):
        await self.bot.db.execute("UPDATE config SET ticket_support_role_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message("✅ Cargo atualizado!", ephemeral=True)
        await self.cog.send_admin_panel(self.origin, is_edit=True)
    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Definir Categoria Padrão", channel_types=[discord.ChannelType.category], row=3)
    async def sel_cat(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await self.bot.db.execute("UPDATE config SET ticket_category_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message("✅ Categoria Padrão atualizada!", ephemeral=True)
        await self.cog.send_admin_panel(self.origin, is_edit=True)
    
    # SELEÇÃO DE CANAIS DE LOGS (Agrupados)
    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Definir Canal de Logs GERAIS", channel_types=[discord.ChannelType.text], row=4)
    async def sel_log(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await self.bot.db.execute("UPDATE config SET ticket_logs_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message("✅ Canal de logs de Tickets atualizado!", ephemeral=True)
        await self.cog.send_admin_panel(self.origin, is_edit=True)

class CategoryControlView(ui.View):
    def __init__(self, bot, cog, origin_interaction): super().__init__(timeout=120); self.bot=bot; self.cog=cog; self.origin=origin_interaction
    @ui.button(label="Nova Categoria", style=discord.ButtonStyle.success, emoji="➕")
    async def new_cat(self, i, b): await i.response.send_modal(CategoryModal(self.bot, self.cog, self.origin))
    @ui.button(label="Editar Categoria", style=discord.ButtonStyle.primary, emoji="✏️")
    async def edit_cat(self, i, b):
        async with self.bot.db.execute("SELECT id, label, description, emoji, location_id FROM ticket_categories WHERE guild_id = ?", (i.guild.id,)) as c: cats=await c.fetchall()
        if not cats: return await i.response.send_message("Nenhuma categoria.", ephemeral=True)
        await i.response.send_message("Selecione:", view=CategoryEditSelectView(self.bot, self.cog, self.origin, cats), ephemeral=True)
    @ui.button(label="Excluir Categoria", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def del_cat(self, i, b):
        async with self.bot.db.execute("SELECT id, label FROM ticket_categories WHERE guild_id = ?", (i.guild.id,)) as c: cats=await c.fetchall()
        if not cats: return await i.response.send_message("Nenhuma categoria.", ephemeral=True)
        await i.response.send_message("Selecione:", view=CategoryDeleteSelectView(self.bot, self.cog, self.origin, cats), ephemeral=True)
    
    # BOTÃO EXTRA PARA CONFIGURAR CANAL DE AVALIAÇÃO (Já que faltou espaço na View Principal)
    @ui.button(label="Definir Canal de Avaliações", style=discord.ButtonStyle.secondary, emoji="⭐", row=1)
    async def set_rating_channel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Selecione o canal para cair as avaliações:", view=RatingChannelSelectView(self.bot, self.cog, self.origin), ephemeral=True)

class RatingChannelSelectView(ui.View):
    def __init__(self, bot, cog, origin):
        super().__init__(timeout=60); self.bot=bot; self.cog=cog; self.origin=origin
    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Selecione o canal...", channel_types=[discord.ChannelType.text])
    async def callback(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await self.bot.db.execute("UPDATE config SET rating_channel_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Avaliações serão enviadas para {select.values[0].mention}!", ephemeral=True)
        await self.cog.send_admin_panel(self.origin, is_edit=True)

class CategoryEditSelectView(ui.View):
    def __init__(self, bot, cog, origin, cats):
        super().__init__(timeout=60); self.bot=bot; self.cog=cog; self.origin=origin; self.cats=cats
        options = [discord.SelectOption(label=c[1], description=c[2], emoji=parse_emoji(c[3]), value=str(c[0])) for c in cats]
        self.select = ui.Select(placeholder="Escolha...", options=options); self.select.callback = self.callback; self.add_item(self.select)
    async def callback(self, i):
        cid = int(self.select.values[0]); sel = next((c for c in self.cats if c[0] == cid), None)
        if sel: await i.response.send_modal(CategoryModal(self.bot, self.cog, self.origin, category_id=cid, current_name=sel[1], current_desc=sel[2], current_emoji=sel[3], current_loc=sel[4]))

class CategoryDeleteSelectView(ui.View):
    def __init__(self, bot, cog, origin, cats):
        super().__init__(timeout=60); self.bot=bot; self.cog=cog; self.origin=origin
        options = [discord.SelectOption(label=c[1], value=str(c[0])) for c in cats]
        self.select = ui.Select(placeholder="Excluir...", options=options); self.select.callback = self.callback; self.add_item(self.select)
    async def callback(self, i):
        await self.bot.db.execute("DELETE FROM ticket_categories WHERE id = ?", (int(self.select.values[0]),)); await self.bot.db.commit()
        await i.response.send_message("🗑️ Removida!", ephemeral=True); await self.cog.send_admin_panel(self.origin, is_edit=True)

class UserTicketSelect(ui.Select):
    def __init__(self, bot, cog, categories):
        options = [discord.SelectOption(label=c[1], description=c[2], emoji=parse_emoji(c[3]), value=str(c[0])) for c in categories]
        super().__init__(placeholder="➡ Escolha aqui sua categoria.", min_values=1, max_values=1, options=options, custom_id="ticket_panel_select"); self.bot=bot; self.cog=cog
    async def callback(self, i): await i.response.send_modal(TicketReasonModal(self.bot, self.cog, int(self.values[0])))

class UserTicketView(ui.View):
    def __init__(self, bot, cog, categories): super().__init__(timeout=None); self.add_item(UserTicketSelect(bot, cog, categories))

class AdminTicketView(ui.View):
    def __init__(self, bot, cog): super().__init__(timeout=None); self.bot=bot; self.cog=cog
    @ui.button(label="Configurações", style=discord.ButtonStyle.secondary, emoji="⚙️")
    async def config_main(self, i, b): await i.response.send_message("⚙️ **Painel de Configuração**", view=GlobalSettingsView(self.bot, self.cog, i), ephemeral=True)
    @ui.button(label="Gerenciar Categorias", style=discord.ButtonStyle.success, emoji="📂")
    async def cats_main(self, i, b): await i.response.send_message("📂 **Gestão de Categorias**", view=CategoryControlView(self.bot, self.cog, i), ephemeral=True)
    @ui.button(label="POSTAR PAINEL PÚBLICO", style=discord.ButtonStyle.primary, emoji="📢", row=1)
    async def post_panel(self, i, b):
        await i.response.defer(ephemeral=True)
        async with self.bot.db.execute("SELECT ticket_panel_channel_id, ticket_title, ticket_desc, ticket_color, ticket_banner FROM config WHERE guild_id = ?", (i.guild.id,)) as c: cfg=await c.fetchone()
        async with self.bot.db.execute("SELECT id, label, description, emoji FROM ticket_categories WHERE guild_id = ?", (i.guild.id,)) as c: cats=await c.fetchall()
        if not cats: return await i.followup.send("❌ Crie uma categoria antes.")
        chan = self.bot.get_channel(cfg[0]) if cfg[0] else i.channel
        INVISIBLE_WIDE_URL = "https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png"
        embed = discord.Embed(color=cfg[3] or config.EMBED_COLOR)
        embed.description = f"# {cfg[1] or 'ATENDIMENTO'}\n\n**Através do atendimento, você pode falar diretamente com nossa equipe.**\n\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{cfg[2]}"
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_image(url=cfg[4] if cfg[4] else INVISIBLE_WIDE_URL)
        await chan.send(embed=embed, view=UserTicketView(self.bot, self.cog, cats))
        if not cfg[0]: await self.bot.db.execute("UPDATE config SET ticket_panel_channel_id = ? WHERE guild_id = ?", (chan.id, i.guild.id)); await self.bot.db.commit()
        await i.followup.send(f"✅ Painel postado em {chan.mention}!")

async def setup(bot):
    await bot.add_cog(Tickets(bot))