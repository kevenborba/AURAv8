import discord
from discord.ext import commands, tasks
import re
import aiohttp
import asyncio
from datetime import datetime

class Streaming(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Regex básico para Twitch e Youtube
        self.url_regex = re.compile(r"(https?://(?:www\.|go\.)?twitch\.tv/([a-z0-9_]+))|(https?://(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]+))|(https?://youtu\.be/([a-zA-Z0-9_-]+))")

    async def get_stream_metadata(self, url):
        """Tenta obter título e jogo da página (Simples Scraping)"""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"User-Agent": "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)"}
                async with session.get(url, headers=headers, timeout=5) as response:
                    if response.status != 200: return None
                    html = await response.text()
                    
                    # TENTA PEGAR O TÍTULO REAL DA LIVE
                    # Na Twitch, og:title costuma ser "Canal - Twitch"
                    # O título da live costuma estar em og:description ou description
                    
                    stream_title = "Transmissão Ao Vivo"
                    
                    # 1. Tenta og:description (Geralmente é o título na Twitch)
                    og_desc_match = re.search(r'<meta property="og:description" content="(.*?)"', html, re.IGNORECASE)
                    if og_desc_match: 
                        stream_title = og_desc_match.group(1)
                    else:
                        # 2. Tenta description normal
                        desc_match = re.search(r'<meta name="description" content="(.*?)"', html, re.IGNORECASE)
                        if desc_match:
                            stream_title = desc_match.group(1)
                        else:
                            # 3. Fallback para og:title
                            og_title_match = re.search(r'<meta property="og:title" content="(.*?)"', html, re.IGNORECASE)
                            if og_title_match:
                                stream_title = og_title_match.group(1).split(" - ")[0] # Remove sufixo se houver

                    # Tenta achar og:image (Thumbnail)
                    image_match = re.search(r'<meta property="og:image" content="(.*?)"', html, re.IGNORECASE)
                    thumb_url = image_match.group(1) if image_match else None

                    return {"title": stream_title, "game": "Ao Vivo", "thumb": thumb_url}
        except Exception as e:
            print(f"Erro scraping: {e}")
            return None

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        if not message.guild: return
        
        # 1. Verifica se está no canal de divulgação configurado
        config = await self.bot.db.execute("SELECT streaming_channel_id, streaming_role_id FROM config WHERE guild_id = ?", (message.guild.id,))
        row = await config.fetchone()
        
        if not row or not row[0]: return # Não configurado
        
        streaming_channel_id = row[0]
        streaming_role_id = row[1]
        
        if message.channel.id != streaming_channel_id: return

        # 2. Busca Link
        match = self.url_regex.search(message.content)
        if match:
            url = match.group(0)
            
            # Deleta msg original
            try: await message.delete() 
            except: pass
            
            # Placeholder msg
            processing_msg = await message.channel.send(f"🔄 Processando divulgação de {message.author.mention}...", delete_after=5)
            
            # 3. Fetch Metadata
            meta = await self.get_stream_metadata(url)
            stream_title = meta.get("title", 'Transmissão Ao Vivo') if meta else "Transmissão Ao Vivo"
            thumb_url = meta.get("thumb", None) if meta else None
            
            user_text = message.content.replace(url, "").strip()
            final_title = user_text if len(user_text) > 5 else stream_title

            # 4. Criar Embed (Estilo Ultra-Wide)
            # URL no título para torná-lo clicável
            embed = discord.Embed(title=final_title, url=url, color=0x9146FF) # Roxo Twitch
            
            # Header Neutro
            embed.set_author(name="🎥 TRANSMISSÃO INICIADA", icon_url=message.guild.icon.url if message.guild.icon else None)
            
            # Descrição com Menção Real
            embed.description = f"{message.author.mention} **está AO VIVO!**\nClique no título ou no botão abaixo para acompanhar."
            
            # Lógica Ultra-Wide: Se tiver thumb, usa ela (que já é wide). Se não, usa a linha transparente pra forçar largura.
            if thumb_url:
                embed.set_image(url=thumb_url)
            else:
                embed.set_image(url="https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png")
            
            embed.set_footer(text="Divulgação Automática AURA V8")
            
            # Adiciona Botão (Mantido pois é útil e visual)
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Assistir Agora", style=discord.ButtonStyle.link, url=url))
            
            # Envia Embed
            # Mensagem Externa Simplificada
            sent_msg = await message.channel.send(content=f"🔔 {message.author.mention} iniciou uma transmissão!", embed=embed, view=view)
            
            # 5. Dar Cargo
            if streaming_role_id:
                role = message.guild.get_role(streaming_role_id)
                if role:
                    try: await message.author.add_roles(role)
                    except: pass
            
            # 6. Salvar no DB
            await self.bot.db.execute("""
                INSERT INTO active_streams (message_id, channel_id, guild_id, user_id, start_time, stream_url)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (sent_msg.id, message.channel.id, message.guild.id, message.author.id, str(datetime.now()), url))
            await self.bot.db.commit()

    async def _terminate_stream(self, guild, user_id, active_stream_data):
        """Helper para encerrar uma live (usado pelo evento e pelo comando manual)"""
        msg_id, chan_id, guild_id, start_time_str = active_stream_data[0], active_stream_data[1], active_stream_data[2], active_stream_data[3] if len(active_stream_data) > 3 else None
        
        # 1. Remove do DB
        await self.bot.db.execute("DELETE FROM active_streams WHERE message_id = ?", (msg_id,))
        await self.bot.db.commit()
        
        # 2. Calcula Duração
        duration_str = "Poucos instantes"
        if start_time_str:
            try:
                start_dt = datetime.fromisoformat(start_time_str)
                delta = datetime.now() - start_dt
                hours, remainder = divmod(int(delta.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                duration_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m {seconds}s"
            except: pass

        # 3. Edita Embed
        if guild:
             channel = guild.get_channel(chan_id)
             if channel:
                 try:
                     msg = await channel.fetch_message(msg_id)
                     embed = msg.embeds[0]
                     embed.color = 0x2f3136 # Cinza/Preto
                     embed.title = "TRANSMISSÃO ENCERRADA" # Sem Emoji
                     embed.description = f"**Duração:** `{duration_str}`"
                     embed.set_footer(text="Acompanhe a próxima.")
                     
                     # Remove botão (View vazia)
                     await msg.edit(embed=embed, view=None)
                 except:    
                     pass

             # 4. Remove Cargo
             config = await self.bot.db.execute("SELECT streaming_role_id FROM config WHERE guild_id = ?", (guild.id,))
             row = await config.fetchone()
             if row and row[0]:
                 role = guild.get_role(row[0])
                 target_member = guild.get_member(user_id)
                 if role and target_member:
                     try: await target_member.remove_roles(role)
                     except: pass
        return True

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        # Otimização: Só checa se o user tiver cargo de streaming OU estiver na tabela active_streams
        is_streaming = False
        for activity in after.activities:
            if activity.type == discord.ActivityType.streaming:
                is_streaming = True
                break
        
        if is_streaming: return # Ainda está em live, ignora.

        # Se não está streaming, verifica se ele tinha uma live ativa no DB
        # E pega START_TIME também
        async with self.bot.db.execute("SELECT message_id, channel_id, guild_id, start_time FROM active_streams WHERE user_id = ? AND guild_id = ?", (after.id, after.guild.id)) as cursor:
            active_stream = await cursor.fetchone()
        
        if not active_stream: return # Não estava na nossa lista

        # ACABOU A LIVE
        await self._terminate_stream(after.guild, after.id, active_stream)

    @discord.app_commands.command(name="encerrar_live", description="🛑 Força o encerramento da divulgação de uma live.")
    @discord.app_commands.checks.has_permissions(manage_messages=True)
    async def force_end_live(self, interaction: discord.Interaction, usuario: discord.Member):
        async with self.bot.db.execute("SELECT message_id, channel_id, guild_id, start_time FROM active_streams WHERE user_id = ? AND guild_id = ?", (usuario.id, interaction.guild.id)) as cursor:
            active_stream = await cursor.fetchone()
            
        if not active_stream:
            await interaction.response.send_message(f"❌ **Erro:** Não encontrei nenhuma live ativa de {usuario.mention} no banco de dados.", ephemeral=True)
            return
            
        await self._terminate_stream(interaction.guild, usuario.id, active_stream)
        await interaction.response.send_message(f"✅ **Sucesso!** A live de {usuario.mention} foi encerrada manualmente.", ephemeral=True)

    @discord.app_commands.command(name="painel_streamer", description="⚙️ Painel Completo de Configuração do Streamer")
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def painel_streamer(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Busca config atual
        cursor = await self.bot.db.execute("SELECT streaming_channel_id, streaming_role_id FROM config WHERE guild_id = ?", (interaction.guild.id,))
        row = await cursor.fetchone()
        
        current_channel_id = row[0] if row else None
        current_role_id = row[1] if row else None
        
        current_channel = interaction.guild.get_channel(current_channel_id) if current_channel_id else None
        current_role = interaction.guild.get_role(current_role_id) if current_role_id else None

        embed = discord.Embed(title="📺 Configuração: Módulo Streamer", color=0x9146FF)
        embed.description = "Gerencie como o bot divulga lives automaticamente."
        
        embed.add_field(name="📢 Canal de Divulgação", value=current_channel.mention if current_channel else "❌ Não Configurado", inline=True)
        embed.add_field(name="🎭 Cargo 'Ao Vivo'", value=current_role.mention if current_role else "❌ Não Configurado", inline=True)
        
        embed.set_footer(text="Use o menu abaixo para alterar.")
        
        view = StreamingConfigView(self.bot, interaction.user)
        await interaction.followup.send(embed=embed, view=view)

    @discord.app_commands.command(name="bot_stream", description="📺 [V8] Status Personalizado. 'ativo=False' remove.")
    @discord.app_commands.describe(url="Link da Live", titulo="Mensagem do Status", ativo="True para ligar, False para desligar")
    async def force_stream(self, interaction: discord.Interaction, url: str = "https://twitch.tv/discord", titulo: str = "AURA V8", ativo: bool = True):
        # Check de Permissão (Dono ou V8)
        is_owner = interaction.user.id == int(interaction.client.owner_id or 0)
        if not is_owner:
             async with self.bot.db.execute("SELECT tier FROM licenses WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
                row = await cursor.fetchone()
             if not row or row[0] != 'v8':
                 await interaction.response.send_message("🔒 **Recurso Exclusivo V8.**", ephemeral=True)
                 return
        
        # Lógica de Ativar/Desativar
        if ativo:
            self.bot.presence_locked = True # Trava o Presence Loop
            await self.bot.change_presence(activity=discord.Streaming(name=titulo, url=url))
            await interaction.response.send_message(f"✅ **Stream Fixada!**\nO status rotativo foi pausado.\n\n📺 **Status:** `{titulo}`\n🔗 **Link:** `{url}`", ephemeral=True)
        else:
            self.bot.presence_locked = False # Destrava
            # Força o presence loop a rodar no próximo tick ou reseta status
            await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="Sistema Reiniciado"))
            await interaction.response.send_message("✅ **Stream Removida!**\nO status rotativo voltará em breve.", ephemeral=True)

class StreamingConfigView(discord.ui.View):
    def __init__(self, bot, author):
        super().__init__(timeout=180)
        self.bot = bot
        self.author = author

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="Selecione o Canal de Divulgação...", min_values=1, max_values=1, row=0)
    async def select_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        if interaction.user != self.author: return
        channel = select.values[0]
        
        await self.bot.db.execute("INSERT INTO config (guild_id, streaming_channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET streaming_channel_id = ?", (interaction.guild.id, channel.id, channel.id))
        await self.bot.db.commit()
        
        await interaction.response.send_message(f"✅ Canal definido para {channel.mention}", ephemeral=True)

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Selecione o Cargo 'Ao Vivo'...", min_values=1, max_values=1, row=1)
    async def select_role(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        if interaction.user != self.author: return
        role = select.values[0]
        
        await self.bot.db.execute("INSERT INTO config (guild_id, streaming_role_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET streaming_role_id = ?", (interaction.guild.id, role.id, role.id))
        await self.bot.db.commit()
        
        await interaction.response.send_message(f"✅ Cargo definido para {role.mention}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Streaming(bot))
