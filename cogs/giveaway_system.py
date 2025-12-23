import discord
from discord.ext import commands, tasks
from discord import app_commands, ui
import datetime
import random
import asyncio
import json

class GiveawaySystem(commands.GroupCog, name="sorteio"):
    def __init__(self, bot):
        self.bot = bot
        
    async def cog_load(self):
        # Tabela PRINCIPAL de Sorteios
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                message_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                guild_id INTEGER,
                title TEXT,
                description TEXT,
                prize TEXT,
                winners_count INTEGER,
                end_time TIMESTAMP,
                host_id INTEGER,
                requirements TEXT DEFAULT '{}',
                status TEXT DEFAULT 'OPEN'
            )
        """)
        
        # Tabela de PARTICIPANTES
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS giveaway_entries (
                giveaway_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY (giveaway_id, user_id)
            )
        """)
        await self.bot.db.commit()
        print("✅ [Giveaway] Tabelas carregadas.")
        
        # Inicia loop
        self.check_giveaways.start()

    def cog_unload(self):
        try: self.check_giveaways.cancel()
        except: pass

    # ====================================================
    # 🔄 PERSISTÊNCIA & LOAD
    # ====================================================
    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(GiveawayView(self.bot, None))
        self.bot.add_view(EndedGiveawayView(self.bot))
        print("✅ [Giveaway] View persistente carregada.")

    # ====================================================
    # ⚙️ CONFIGURAÇÃO
    # ====================================================
    @app_commands.command(name="config", description="Configura aparência dos sorteios.")
    @app_commands.describe(hex_color="Cor do Embed (Ex: #FF0000)", emoji="Emoji do Botão (Ex: 🎉)")
    async def config_giveaway(self, interaction: discord.Interaction, hex_color: str = None, emoji: str = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Apenas administradores.", ephemeral=True)
            
        async with self.bot.db.execute("SELECT giveaway_color, giveaway_emoji FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            data = await cursor.fetchone()
            
        current_color = data[0] if data else 3447003
        current_emoji = data[1] if data else "🎉"
        
        new_color = current_color
        new_emoji = current_emoji
        
        msg = []
        
        if hex_color:
            try:
                hex_clean = hex_color.replace("#", "")
                new_color = int(hex_clean, 16)
                msg.append(f"🎨 Cor atualizada para `#{hex_clean}`")
            except:
                return await interaction.response.send_message("❌ Cor inválida! Use formato Hex (Ex: #FF0000).", ephemeral=True)
                
        if emoji:
            new_emoji = emoji
            msg.append(f"🎟️ Emoji atualizado para {emoji}")
            
        await self.bot.db.execute("""
            INSERT INTO config (guild_id, giveaway_color, giveaway_emoji)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
            giveaway_color = excluded.giveaway_color,
            giveaway_emoji = excluded.giveaway_emoji
        """, (interaction.guild.id, new_color, new_emoji))
        await self.bot.db.commit()
        
        if not msg:
            return await interaction.response.send_message(f"ℹ️ Nenhuma alteração feita.\nAtual: Cor `#{new_color:X}`, Emoji {new_emoji}", ephemeral=True)
            
        await interaction.response.send_message("\n".join(msg), ephemeral=True)

    # ====================================================
    # 📝 COMANDOS (SUBCOMANDOS)
    # ====================================================
    
    @app_commands.command(name="criar", description="Inicia um novo sorteio.")
    @app_commands.describe(role_req="Cargo obrigatório para participar (Opcional)")
    async def create_cmd(self, interaction: discord.Interaction, role_req: discord.Role = None):
        # Passa o role_req para o Modal via construtor
        await interaction.response.send_modal(GiveawayModal(self.bot, role_req))

    @app_commands.command(name="reroll", description="Refaz o sorteio de uma mensagem.")
    async def reroll_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RerollModal(self.bot))

    @app_commands.command(name="encerrar", description="Encerra um sorteio imediatamente.")
    async def end_cmd(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EndGiveawayModal(self.bot, self))

    # ====================================================
    # 🔄 LOOP DE VALIDAÇÃO
    # ====================================================
    @tasks.loop(seconds=10)
    async def check_giveaways(self):
        await self.bot.wait_until_ready()
        now = datetime.datetime.now()
        
        async with self.bot.db.execute("SELECT message_id, channel_id, guild_id, prize, winners_count, host_id, title, description FROM giveaways WHERE status = 'OPEN' AND end_time <= ?", (now,)) as cursor:
            ended_giveaways = await cursor.fetchall()
            
        for gw in ended_giveaways:
            await self.end_giveaway(gw)

    async def end_giveaway(self, gw_data):
        # Desempacota com segurança (caso tabela mude, mas aqui controlamos)
        message_id, channel_id, guild_id, prize, winners_count, host_id, title, desc = gw_data
        
        # 1. Marca como FINALIZADO
        await self.bot.db.execute("UPDATE giveaways SET status = 'FINISHED' WHERE message_id = ?", (message_id,))
        await self.bot.db.commit()

        guild = self.bot.get_guild(guild_id)
        if not guild: return

        channel = guild.get_channel(channel_id)
        if not channel: return

        # 2. Busca Participantes
        async with self.bot.db.execute("SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (message_id,)) as cursor:
            participants = [row[0] for row in await cursor.fetchall()]

        # 3. Sorteia
        if len(participants) < winners_count:
            winners = participants 
        else:
            winners = random.sample(participants, winners_count)
            
        # 4. Anuncia
        try:
            msg = await channel.fetch_message(message_id) 
        except:
            return 

        if not winners:
            await channel.send(f"⚠️ O sorteio **{title or prize}** acabou, mas ninguém participou. 😢\n{msg.jump_url}")
            await msg.edit(view=None) 
            return

        winners_mentions = ", ".join([f"<@{uid}>" for uid in winners])
        
        # Busca config de cor
        async with self.bot.db.execute("SELECT giveaway_color FROM config WHERE guild_id = ?", (guild_id,)) as cursor:
             data = await cursor.fetchone()
        color = data[0] if data and data[0] else 0xf1c40f 

        embed = discord.Embed(title=f"🎉 {title or 'TEMOS VENCEDORES!'}", description=f"O sorteio **{prize}** foi finalizado!", color=color)
        if desc:
            embed.description += f"\n\n{desc}"
            
        embed.add_field(name="🏆 Ganhador(es)", value=winners_mentions)
        embed.add_field(name="Link do Sorteio", value=f"[Ir para Mensagem]({msg.jump_url})")
        
        # Tenta pegar avatar do primeiro ganhador
        first_winner = guild.get_member(winners[0])
        if first_winner:
            embed.set_thumbnail(url=first_winner.display_avatar.url)
        else:
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            
        view = EndedGiveawayView(self.bot)
        
        await channel.send(content=f"🎉 Parabéns {winners_mentions}!", embed=embed, view=view)
        
        # Atualiza Embed Original
        original_embed = msg.embeds[0]
        original_embed.color = 0x2ecc71 # Verde (Finalizado)
        
        if len(original_embed.fields) > 0:
            original_embed.set_field_at(0, name="🏆 Vencedores", value=winners_mentions, inline=False)
        else:
            original_embed.add_field(name="🏆 Vencedores", value=winners_mentions, inline=False)
            
        original_embed.set_footer(text="Sorteio Encerrado")
        
        await msg.edit(embed=original_embed, view=None)

# ====================================================
# 🎲 END MODAL (GLOBAL)
# ====================================================
class EndGiveawayModal(ui.Modal, title="Encerrar Sorteio"):
    msg_id = ui.TextInput(label="ID da Mensagem do Sorteio", style=discord.TextStyle.short)
    
    def __init__(self, bot, cog):
        super().__init__()
        self.bot = bot; self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            m_id = int(self.msg_id.value)
        except: return await interaction.response.send_message("❌ ID inválido.", ephemeral=True)
        
        async with self.bot.db.execute("SELECT message_id, channel_id, guild_id, prize, winners_count, host_id, title, description FROM giveaways WHERE message_id = ?", (m_id,)) as cursor:
            gw = await cursor.fetchone()
            
        if not gw: return await interaction.response.send_message("❌ Sorteio não encontrado.", ephemeral=True)
        
        await self.cog.end_giveaway(gw)
        await interaction.response.send_message("✅ Sorteio encerrado forçadamente.", ephemeral=True)

class EndedGiveawayView(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @ui.button(label="Reroll (Admin)", style=discord.ButtonStyle.danger, emoji="🔄", custom_id="gw_reroll_btn")
    async def reroll_button(self, interaction: discord.Interaction, button: ui.Button):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Apenas administradores.", ephemeral=True)
            
        await interaction.response.send_modal(RerollModal(self.bot))

# ====================================================
# 🎲 REROLL MODAL (GLOBAL)
# ====================================================
class RerollModal(ui.Modal, title="Reroll (Refazer Sorteio)"):
    msg_id = ui.TextInput(label="ID da Mensagem do Sorteio", style=discord.TextStyle.short)
    winners_qty = ui.TextInput(label="Novos Ganhadores", default="1", style=discord.TextStyle.short)
    
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        try:
            m_id = int(self.msg_id.value)
            qty = int(self.winners_qty.value)
        except: return await interaction.response.send_message("❌ ID ou Quantidade inválidos.", ephemeral=True)
        
        async with self.bot.db.execute("SELECT channel_id, prize FROM giveaways WHERE message_id = ?", (m_id,)) as cursor:
            res = await cursor.fetchone()
            
        if not res: return await interaction.response.send_message("❌ Sorteio não encontrado no DB.", ephemeral=True)
        
        channel_id, prize = res
        channel = interaction.guild.get_channel(channel_id)
        
        # Busca participantes
        async with self.bot.db.execute("SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (m_id,)) as cursor:
            participants = [row[0] for row in await cursor.fetchall()]
            
        if not participants:
             return await interaction.response.send_message("❌ Ninguém participou desse sorteio.", ephemeral=True)
             
        winners = random.sample(participants, min(len(participants), qty))
        winners_mentions = ", ".join([f"<@{uid}>" for uid in winners])
        
        await channel.send(f"🔄 **REROLL!** Novo(s) ganhador(es) do sorteio de **{prize}**:\n🎉 {winners_mentions}!")
        await interaction.response.send_message("✅ Reroll realizado!", ephemeral=True)

# ====================================================
# 🖥️ MODAL DE CRIAÇÃO (AGORA COM TITULO/DESC/CARGO VIA ARG)
# ====================================================
class GiveawayModal(ui.Modal, title="Criar Sorteio"):
    # Limite de fields no modal é 5.
    # 1. Título (Curto)
    # 2. Descrição (Paragraph)
    # 3. Prêmio (Curto)
    # 4. Duração (Curto)
    # 5. Ganhadores (Curto)
    
    gw_title = ui.TextInput(label="Título (Opcional)", placeholder="Ex: Sorteio Relâmpago!", required=False, style=discord.TextStyle.short)
    gw_desc = ui.TextInput(label="Descrição (Opcional)", placeholder="Ex: Patrocinado pela loja X...", required=False, style=discord.TextStyle.paragraph)
    prize = ui.TextInput(label="Prêmio", placeholder="Ex: Nitro Classic, 50k", style=discord.TextStyle.short)
    duration = ui.TextInput(label="Duração (m/h/d)", placeholder="Ex: 10m, 2h, 1d", style=discord.TextStyle.short)
    winners = ui.TextInput(label="Nº Ganhadores", placeholder="1", default="1", style=discord.TextStyle.short)
    
    def __init__(self, bot, role_req: discord.Role = None):
        super().__init__()
        self.bot = bot
        self.role_req = role_req # Salva o cargo passado via comando slash

    async def on_submit(self, interaction: discord.Interaction):
        # Validação de Tempo
        time_str = self.duration.value.lower()
        seconds = 0
        if time_str.endswith("m"): seconds = int(time_str[:-1]) * 60
        elif time_str.endswith("h"): seconds = int(time_str[:-1]) * 3600
        elif time_str.endswith("d"): seconds = int(time_str[:-1]) * 86400
        else: return await interaction.response.send_message("❌ Formato de tempo inválido! Use m (minutos), h (horas) ou d (dias).", ephemeral=True)
        
        end_time = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
        timestamp = int(end_time.timestamp())
        
        requirements = {}
        role_mention = ""
        
        # Usa o cargo passado no argumento
        if self.role_req:
            requirements['role_id'] = self.role_req.id
            role_mention = f"\n🔒 **Requisito:** {self.role_req.mention}"

        try: winners_count = int(self.winners.value)
        except: return await interaction.response.send_message("❌ Nº de Ganhadores deve ser um número.", ephemeral=True)

        # BUSCA CONFIG (COR / EMOJI)
        async with self.bot.db.execute("SELECT giveaway_color, giveaway_emoji FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            data = await cursor.fetchone()
        
        if data and data[0]: color = data[0]
        else: color = 0x3498db
        
        if data and data[1]: emoji_btn = data[1]
        else: emoji_btn = "🎟️"

        # Titulo e Desc
        final_title = self.gw_title.value or "🎉 SORTEIO INICIADO!"
        final_desc = self.gw_desc.value or f"Participe reagindo abaixo!"

        embed = discord.Embed(title=final_title, description=f"{final_desc}\n\n🎁 **Prêmio:** {self.prize.value}\n👑 **Patrocinador:** {interaction.user.mention}{role_mention}\n\n🏆 **Vencedores:** {winners_count}\n⏰ **Termina:** <t:{timestamp}:R> (<t:{timestamp}:f>)", color=color)
        embed.add_field(name="👥 Participantes: 0", value="\u200b", inline=False)
        embed.set_footer(text="Boa sorte!")
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        view = GiveawayView(self.bot, None, emoji=emoji_btn)
        
        await interaction.response.send_message(embed=embed, view=view)
        msg = await interaction.original_response()
        
        await self.bot.db.execute("""
            INSERT INTO giveaways (message_id, channel_id, guild_id, prize, winners_count, end_time, host_id, requirements, title, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (msg.id, interaction.channel.id, interaction.guild.id, self.prize.value, winners_count, end_time, interaction.user.id, json.dumps(requirements), self.gw_title.value, self.gw_desc.value))
        await self.bot.db.commit()

# ====================================================
# 🔘 VIEW DO SORTEIO (GLOBAL)
# ====================================================
class GiveawayView(ui.View):
    def __init__(self, bot, giveaway_id, emoji="🎟️"):
        super().__init__(timeout=None)
        self.bot = bot
        self.giveaway_id = giveaway_id
        
        # Cria botão com callback manual
        btn = ui.Button(label=f"Participar {emoji}", style=discord.ButtonStyle.secondary, custom_id="gw_join")
        btn.callback = self.join_callback # Bind manual
        self.add_item(btn)

    async def join_callback(self, interaction: discord.Interaction):
        # Verifica Requisitos
        async with self.bot.db.execute("SELECT requirements FROM giveaways WHERE message_id = ?", (interaction.message.id,)) as cursor:
            res = await cursor.fetchone()
            
        if res:
            try:
                reqs = json.loads(res[0])
                if reqs.get('role_id'):
                    role = interaction.guild.get_role(reqs['role_id'])
                    if role and role not in interaction.user.roles:
                         return await interaction.response.send_message(f"🔒 **Acesso Negado:** Você precisa do cargo {role.mention} para participar.", ephemeral=True)
            except: pass

        joined = False
        try:
            await self.bot.db.execute("INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)", (interaction.message.id, interaction.user.id))
            await self.bot.db.commit()
            joined = True
            await interaction.response.send_message("✅ **Sucesso!** Você entrou no sorteio. Boa sorte! 🍀", ephemeral=True)
        except:
            try:
                await self.bot.db.execute("DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?", (interaction.message.id, interaction.user.id))
                await self.bot.db.commit()
                joined = False
                await interaction.response.send_message("❌ **Você saiu** do sorteio.", ephemeral=True)
            except Exception as e:
                 await interaction.response.send_message(f"Erro: {e}", ephemeral=True)
                 return

        # UPDATE LIVE COUNTER
        try:
            async with self.bot.db.execute("SELECT count(*) FROM giveaway_entries WHERE giveaway_id = ?", (interaction.message.id,)) as cursor:
                count = (await cursor.fetchone())[0]
            
            embed = interaction.message.embeds[0]
            # Procura o campo Participantes (ou usa o index 0 se tiver certeza)
            field_idx = -1
            for i, f in enumerate(embed.fields):
                if "Participantes" in f.name:
                    field_idx = i
                    break
            
            if field_idx != -1:
                embed.set_field_at(field_idx, name=f"👥 Participantes: {count}", value="\u200b", inline=False)
            else:
                # Se não achar, adiciona (caso de embeds antigos)
                embed.add_field(name=f"👥 Participantes: {count}", value="\u200b", inline=False)
                
            await interaction.message.edit(embed=embed)
        except: pass

async def setup(bot):
    await bot.add_cog(GiveawaySystem(bot))
