import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime
import aiosqlite

INVISIBLE_WIDE_URL = "https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png"

class Logs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # Migração Automática de DB
        print("🔍 [LOGS] Verificando colunas de log no banco de dados...")
        try:
            # Tenta adicionar colunas se não existirem
            async with self.bot.db.execute("SELECT log_voice_channel_id, log_message_channel_id, log_nickname_channel_id, log_ban_channel_id FROM config LIMIT 1") as cursor:
                pass
        except Exception:
            print("⚠️ [LOGS] Colunas de log não encontradas ou incompletas. Atualizando...")
            try:
                # Adiciona colunas uma a uma (SQLite não falha se já existir em versões recentes, mas garantindo)
                columns = ["log_voice_channel_id", "log_message_channel_id", "log_nickname_channel_id", "log_ban_channel_id"]
                for col in columns:
                    try:
                        await self.bot.db.execute(f"ALTER TABLE config ADD COLUMN {col} INTEGER")
                    except: pass
                await self.bot.db.commit()
                print("✅ [LOGS] Colunas verificadas/adicionadas.")
            except Exception as e:
                print(f"❌ [LOGS] Erro na migração: {e}")

    # ====================================================
    # ⚙️ PAINEL DE CONFIGURAÇÃO
    # ====================================================
    @app_commands.command(name="painel_logs", description="Configura os canais de logs.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_logs(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        async with self.bot.db.execute("SELECT log_voice_channel_id, log_message_channel_id, log_nickname_channel_id, log_ban_channel_id FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()
            
        voice_id = row[0] if row else None
        msg_id = row[1] if row else None
        nick_id = row[2] if row else None
        ban_id = row[3] if row else None
        
        embed = discord.Embed(title="⚙️ Configuração de Logs", color=0x2b2d31)
        embed.description = (
            f"**Canais Atuais**\n"
            f"🎤 Voz: {('<#' + str(voice_id) + '>') if voice_id else '🔴 Não definido'}\n"
            f"💬 Mensagens: {('<#' + str(msg_id) + '>') if msg_id else '🔴 Não definido'}\n"
            f"🏷️ Nickname: {('<#' + str(nick_id) + '>') if nick_id else '🔴 Não definido'}\n"
            f"🔨 Punições: {('<#' + str(ban_id) + '>') if ban_id else '🔴 Não definido'}\n\n"
            "Selecione abaixo os canais para cada tipo de log."
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        view = LogConfigView(self.bot)
        await interaction.followup.send(embed=embed, view=view)

    # ====================================================
    # 👂 LISTENERS (EVENTOS)
    # ====================================================
    
    # --- VOZ ---
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot: return
        
        # Busca canal de log
        async with self.bot.db.execute("SELECT log_voice_channel_id FROM config WHERE guild_id = ?", (member.guild.id,)) as cursor:
            row = await cursor.fetchone()
        if not row or not row[0]: return
        
        log_channel = member.guild.get_channel(row[0])
        if not log_channel: return

        embed = discord.Embed(timestamp=datetime.datetime.now())
        embed.set_author(name=f"{member.display_name} ({member.id})", icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_image(url=INVISIBLE_WIDE_URL)

        # Entrou
        if not before.channel and after.channel:
            embed.title = "📥 Entrou em Canal de Voz"
            embed.color = 0x2ecc71 # Verde
            embed.description = f"**Canal:** {after.channel.mention}"
            
        # Saiu
        elif before.channel and not after.channel:
            embed.title = "📤 Saiu de Canal de Voz"
            embed.color = 0xe74c3c # Vermelho
            embed.description = f"**Canal:** {before.channel.mention}"
            
        # Trocou
        elif before.channel and after.channel and before.channel != after.channel:
            embed.title = "🔄 Trocou de Canal de Voz"
            embed.color = 0xf1c40f # Amarelo
            embed.description = f"**De:** {before.channel.mention}\n**Para:** {after.channel.mention}"
            
        else:
            return # Mudança de estado irrelevante (mute/deafen)

        await log_channel.send(embed=embed)

    # --- MENSAGEM APAGADA ---
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot or not message.guild: return

        async with self.bot.db.execute("SELECT log_message_channel_id FROM config WHERE guild_id = ?", (message.guild.id,)) as cursor:
            row = await cursor.fetchone()
        if not row or not row[0]: return
        
        log_channel = message.guild.get_channel(row[0])
        if not log_channel: return

        embed = discord.Embed(title="🗑️ Mensagem Apagada", color=0xe74c3c, timestamp=datetime.datetime.now())
        embed.set_author(name=f"{message.author.display_name} ({message.author.id})", icon_url=message.author.display_avatar.url)
        embed.description = f"**Canal:** {message.channel.mention}\n\n**Conteúdo:**\n{message.content or '*[Sem conteúdo de texto]*'}"
        
        # Se tiver anexos
        if message.attachments:
            embed.add_field(name="Anexos", value=f"{len(message.attachments)} arquivo(s)", inline=False)

        embed.set_thumbnail(url=message.author.display_avatar.url)
        embed.set_image(url=INVISIBLE_WIDE_URL)
        
        await log_channel.send(embed=embed)

    # --- MENSAGEM EDITADA ---
    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.bot or not before.guild: return
        if before.content == after.content: return # Ignora mudanças que não são de texto (ex: embed load)

        async with self.bot.db.execute("SELECT log_message_channel_id FROM config WHERE guild_id = ?", (before.guild.id,)) as cursor:
            row = await cursor.fetchone()
        if not row or not row[0]: return
        
        log_channel = before.guild.get_channel(row[0])
        if not log_channel: return

        embed = discord.Embed(title="✏️ Mensagem Editada", color=0x3498db, timestamp=datetime.datetime.now())
        embed.set_author(name=f"{before.author.display_name} ({before.author.id})", icon_url=before.author.display_avatar.url)
        embed.description = f"**Canal:** {before.channel.mention}\n\n**[Link da Mensagem]({after.jump_url})**"
        
        embed.add_field(name="Antigo", value=before.content[:1024] or "*[Vazio]*", inline=False)
        embed.add_field(name="Novo", value=after.content[:1024] or "*[Vazio]*", inline=False)

        embed.set_thumbnail(url=before.author.display_avatar.url)
        embed.set_image(url=INVISIBLE_WIDE_URL)
        
        await log_channel.send(embed=embed)

    # --- NICKNAME ALTERADO ---
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.nick == after.nick: return
        
        async with self.bot.db.execute("SELECT log_nickname_channel_id FROM config WHERE guild_id = ?", (before.guild.id,)) as cursor:
            row = await cursor.fetchone()
        if not row or not row[0]: return
        
        log_channel = before.guild.get_channel(row[0])
        if not log_channel: return

        embed = discord.Embed(title="🏷️ Nickname Alterado", color=0x9b59b6, timestamp=datetime.datetime.now())
        embed.set_author(name=f"{after.display_name} ({after.id})", icon_url=after.display_avatar.url)
        
        embed.add_field(name="Antigo", value=f"`{before.nick or before.name}`", inline=True)
        embed.add_field(name="Novo", value=f"`{after.nick or after.name}`", inline=True)
        
        embed.set_thumbnail(url=after.display_avatar.url)
        embed.set_image(url=INVISIBLE_WIDE_URL)
        
        await log_channel.send(embed=embed)

    # --- MEMBRO BANIDO ---
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        async with self.bot.db.execute("SELECT log_ban_channel_id FROM config WHERE guild_id = ?", (guild.id,)) as cursor:
            row = await cursor.fetchone()
        if not row or not row[0]: return
        
        log_channel = guild.get_channel(row[0])
        if not log_channel: return

        embed = discord.Embed(title="🔨 Membro Banido", color=0xff0000, timestamp=datetime.datetime.now())
        embed.set_author(name=f"{user.name} ({user.id})", icon_url=user.display_avatar.url)
        embed.description = f"**Usuário:** {user.mention}\n**ID:** `{user.id}`"
        
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_image(url=INVISIBLE_WIDE_URL)
        
        await log_channel.send(embed=embed)

    # --- MEMBRO DESBANIDO ---
    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        async with self.bot.db.execute("SELECT log_ban_channel_id FROM config WHERE guild_id = ?", (guild.id,)) as cursor:
            row = await cursor.fetchone()
        if not row or not row[0]: return
        
        log_channel = guild.get_channel(row[0])
        if not log_channel: return

        embed = discord.Embed(title="🔓 Membro Desbanido", color=0x2ecc71, timestamp=datetime.datetime.now())
        embed.set_author(name=f"{user.name} ({user.id})", icon_url=user.display_avatar.url)
        embed.description = f"**Usuário:** {user.mention}\n**ID:** `{user.id}`"
        
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.set_image(url=INVISIBLE_WIDE_URL)
        
        await log_channel.send(embed=embed)

class LogConfigView(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=120)
        self.bot = bot

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Selecione Canal de Logs de VOZ", channel_types=[discord.ChannelType.text], row=0)
    async def sel_voice(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await self.bot.db.execute("UPDATE config SET log_voice_channel_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Log de Voz definido para {select.values[0].mention}!", ephemeral=True)

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Selecione Canal de Logs de MENSAGEM", channel_types=[discord.ChannelType.text], row=1)
    async def sel_msg(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await self.bot.db.execute("UPDATE config SET log_message_channel_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Log de Mensagens definido para {select.values[0].mention}!", ephemeral=True)

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Selecione Canal de Logs de NICKNAME", channel_types=[discord.ChannelType.text], row=2)
    async def sel_nick(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await self.bot.db.execute("UPDATE config SET log_nickname_channel_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Log de Nickname definido para {select.values[0].mention}!", ephemeral=True)

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Selecione Canal de Logs de PUNIÇÕES", channel_types=[discord.ChannelType.text], row=3)
    async def sel_ban(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await self.bot.db.execute("UPDATE config SET log_ban_channel_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Log de Punições definido para {select.values[0].mention}!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Logs(bot))
