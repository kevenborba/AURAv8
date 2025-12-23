import discord
from discord import app_commands, ui
import time
try:
    import psutil
except ImportError:
    psutil = None
import datetime
import sys
import os
import io
import importlib
import matplotlib.pyplot as plt
from collections import deque
from discord.ext import commands, tasks

try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import config
except ImportError:
    pass

class General(commands.Cog):
    async def cog_load(self):
        self.bot.add_view(PingView(self))

    def cog_unload(self):
        self.auto_update_ping.cancel()

    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
        self.latency_history = deque(maxlen=20)
        self.auto_update_ping.start()

    def generate_graph(self):
        """Gera um gráfico de latência em memória com eixos."""
        if not self.latency_history: return None
        
        fig, ax = plt.subplots(figsize=(8, 3)) 
        
        # Plotagem
        ax.plot(self.latency_history, color='#43b581', marker='o', markersize=4, linewidth=2)
        
        # Configuração dos Eixos
        ax.set_title("Latência (ms) - Últimos 20 Minutos", fontsize=12, color='white', pad=10)
        ax.set_ylabel("Ping (ms)", color='gray', fontsize=10)
        ax.set_xlabel("Tempo (minutos atrás)", color='gray', fontsize=10)
        
        # Grid leve
        ax.grid(True, linestyle='--', alpha=0.2)
        
        # Remove bordas desnecessárias
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_color('gray')
        ax.spines['left'].set_color('gray')
        
        # Ajusta layout
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', transparent=True)
        buf.seek(0)
        plt.close(fig)
        return buf

    async def get_db_latency(self):
        start = time.perf_counter()
        try:
            async with self.bot.db.execute("SELECT 1"): 
                pass
            end = time.perf_counter()
            return round((end - start) * 1000, 2)
        except:
            return 0

    async def _build_status_embed(self, guild, requester_name):
        # Coleta de dados
        discord_ping = round(self.bot.latency * 1000)
        self.latency_history.append(discord_ping)
        
        db_ping = await self.get_db_latency()
        if psutil:
            cpu_usage = psutil.cpu_percent()
            ram_usage = psutil.virtual_memory().percent
        else:
            cpu_usage = 0
            ram_usage = 0
        
        # Lógica de Status
        if discord_ping < 150:
            status_emoji = "🟢"
        elif discord_ping < 350:
            status_emoji = "🟠"
        else:
            status_emoji = "🔴"

        embed = discord.Embed(title="🚀 Monitor de Sistema", color=0x000000, timestamp=datetime.datetime.now())
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.description = f"**Status do Sistema:** {status_emoji}\n**Uptime:** <t:{int(self.start_time)}:R>"
        
        embed.add_field(name="📡 Rede", value=f"**Ping API:** `{discord_ping}ms`\n**Ping DB:** `{db_ping}ms`", inline=True)
        embed.add_field(name="💻 Hardware", value=f"**CPU:** `{cpu_usage}%`\n**RAM:** `{ram_usage}%`", inline=True)
        embed.add_field(name="⚙️ Servidor", value=f"**Membros:** `{guild.member_count}`\n**Region:** `BR`", inline=True)
        embed.set_footer(text=f"Solicitado por {requester_name} • Atualiza a cada 1 min")

        return embed

    @tasks.loop(minutes=1)
    async def auto_update_ping(self):
        async with self.bot.db.execute("SELECT message_id, channel_id, guild_id, user_id FROM active_pings") as cursor:
            pings = await cursor.fetchall()

        for msg_id, chan_id, guild_id, user_id in pings:
            try:
                guild = self.bot.get_guild(guild_id)
                if not guild: continue
                
                channel = guild.get_channel(chan_id)
                if not channel: continue
                
                try:
                    message = await channel.fetch_message(msg_id)
                except discord.NotFound:
                    # Mensagem não existe mais, limpa do DB
                    await self.bot.db.execute("DELETE FROM active_pings WHERE message_id = ?", (msg_id,))
                    await self.bot.db.commit()
                    continue

                user = guild.get_member(user_id)
                requester_name = user.name if user else "Desconhecido"

                embed = await self._build_status_embed(guild, requester_name)
                
                # Gráfico
                graph_buf = self.generate_graph()
                files = []
                if graph_buf:
                    files.append(discord.File(graph_buf, filename="graph.png"))
                    embed.set_image(url="attachment://graph.png")
                else:
                    embed.set_image(url="https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png")

                await message.edit(embed=embed, attachments=files)
            
            except Exception as e:
                print(f"❌ [PING] Erro ao atualizar msg {msg_id}: {e}")

    @auto_update_ping.before_loop
    async def before_auto_update(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="ping", description="📊 Exibe o painel de controle.")
    async def ping(self, interaction: discord.Interaction):
        importlib.reload(config) 
        await interaction.response.defer()
        await self.send_status_embed(interaction)

    async def send_status_embed(self, interaction: discord.Interaction, is_update=False):
        embed = await self._build_status_embed(interaction.guild, interaction.user.name)

        # Gráfico
        graph_buf = self.generate_graph()
        files = []
        if graph_buf:
            files.append(discord.File(graph_buf, filename="graph.png"))
            embed.set_image(url="attachment://graph.png")
        else:
            embed.set_image(url="https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png")

        view = PingView(self)
        
        if is_update:
            await interaction.edit_original_response(embed=embed, view=view, attachments=files)
        else:
            msg = await interaction.followup.send(embed=embed, view=view, files=files)
            # Registra no DB para auto-update
            await self.bot.db.execute("INSERT OR REPLACE INTO active_pings (message_id, channel_id, guild_id, user_id) VALUES (?, ?, ?, ?)", 
                                      (msg.id, interaction.channel.id, interaction.guild.id, interaction.user.id))
            await self.bot.db.commit()

    @app_commands.command(name="help", description="📚 Central de Ajuda e Comandos.")
    async def help_command(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        # 1. Identificar Tier
        raw_tier = 'free'
        try:
            async with self.bot.db.execute("SELECT tier FROM licenses WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
                row = await cursor.fetchone()
            if row: raw_tier = row[0]
        except: pass
        
        # DEBUG: Ver o que está vindo do banco
        print(f"🕵️ [HELP DEBUG] Guild: {interaction.guild.name} | Raw Tier: '{raw_tier}'")
        print(f"🕵️ [HELP DEBUG] Available Map Keys: {list(self.bot.tier_map.keys())}")

        # 2. Inicializar View com Dropdown
        view = HelpView(self.bot, interaction.user, raw_tier)
        embed = view.get_home_embed()

        await interaction.followup.send(embed=embed, view=view)

class HelpSelect(ui.Select):
    def __init__(self, bot, tier, mapping):
        self.bot = bot
        self.tier = tier
        self.mapping = mapping
        
        options = [
            discord.SelectOption(
                label="Início", 
                description="Voltar para a tela principal.", 
                emoji="🏠", 
                value="home"
            )
        ]
        
        # Emojis para categorias conhecidas
        category_emojis = {
            'general': '🌐', 'admin': '🛡️', 'sales': '💰', 'tickets': '🎫', 
            'faction_actions': '⚔️', 'hierarchy': '👑', 'punishments': '⚖️',
            'giveaway_system': '🎉', 'suggestions': '💡', 'welcome': '👋',
            'logs': '📜', 'monitor': '🖥️', 'setagem': '🏷️', 'timesheet': '⏱️',
            'streaming': '📡', 'staff_stats': '📊', 'verification': '✅',
            'bugs': '🐛', 'police': '👮', 'monitor': '📈', 'embed_creator': '🎨',
            'webserver': '🔗'
        }
        
        # Adicionar opções baseadas no mapeamento
        # Mapping: {'General': [Command, Command...], ...}
        for cog_name in sorted(mapping.keys()):
            emoji = category_emojis.get(cog_name.lower(), '🔹')
            options.append(discord.SelectOption(
                label=cog_name,
                description=f"Ver comandos do módulo {cog_name}",
                emoji=emoji,
                value=cog_name
            ))

        super().__init__(
            placeholder="Selecione um módulo para ver os comandos...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "home":
            await interaction.response.edit_message(embed=self.view.get_home_embed(), view=self.view)
        else:
            cog_name = self.values[0]
            commands = self.mapping.get(cog_name, [])
            embed = self.view.get_category_embed(cog_name, commands)
            await interaction.response.edit_message(embed=embed, view=self.view)

class HelpView(ui.View):
    def __init__(self, bot, user, tier):
        super().__init__(timeout=180)
        self.bot = bot
        self.user = user
        self.raw_tier = tier
        
        # Normalização do Tier
        self.tier = self._normalize_tier(tier)
        print(f"🕵️ [HELP DEBUG] Normalized Tier: '{self.tier}'")
        
        self.current_mapping = self._get_commands_mapping()
        
        # Adiciona o Dropdown
        self.add_item(HelpSelect(bot, self.tier, self.current_mapping))

    def _normalize_tier(self, raw_tier):
        """Converte nomes de licenças complexos para as chaves simples do DB."""
        t = str(raw_tier).lower().strip()
        
        # Mapa de Alias
        if 'start' in t: return 'start'
        if 'facção' in t or 'faccao' in t or 'faction' in t: return 'faction'
        if 'police' in t: return 'police'
        if 'v8' in t or 'aura' in t: return 'v8'
        
        return 'free' # Fallback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.user:
            await interaction.response.send_message("🚫 Esse menu não é para você.", ephemeral=True)
            return False
        return True

    def _get_commands_mapping(self):
        """Filtra comandos baseado no Tier do servidor com Loose Matching."""
        mapping = {}
        
        # Pega a lista de cogs permitidos para este tier
        # db_list = ['embed_creator', 'admin', 'sorteio', ...]
        db_list = self.bot.tier_map.get(self.tier, [])
        
        # Cria set normalizado para busca rápida
        # 'embed_creator' -> 'embedcreator'
        allowed_normalized = {m.lower().replace("_", "").replace(" ", "") for m in db_list}
        
        # Adiciona módulos públicos/essenciais que podem não estar na lista do banco
        public_modules = ['general', 'sales', 'admin']
        for p in public_modules: allowed_normalized.add(p)
        
        for cog_name, cog in self.bot.cogs.items():
            # Normaliza nome da Classe/Cog
            # Ex: 'EmbedCreator' -> 'embedcreator'
            # Ex: 'FactionActions' -> 'factionactions'
            # Ex: 'sorteio' -> 'sorteio'
            cog_norm = cog_name.lower().replace("_", "").replace(" ", "")
            
            # Debug Only
            # print(f"🔍 Checking Cog: {cog_name} -> {cog_norm}")
            
            # Verifica se está na lista permitida
            is_allowed = False
            
            # 1. Match Exato (por segurança)
            if cog_name.lower() in db_list: is_allowed = True
            
            # 2. Match Normalizado (Loose)
            elif cog_norm in allowed_normalized: is_allowed = True
            
            if not is_allowed:
                continue
                
            # Coleta comandos do Cog
            cog_commands = []
            for cmd in cog.walk_app_commands():
                # Ignora comandos sem descrição (opcional) ou subcomandos soltos
                if hasattr(cmd, 'parent') and cmd.parent:
                    full_name = f"/ {cmd.parent.name} {cmd.name}"
                else:
                    full_name = f"/ {cmd.name}"
                
                cog_commands.append((full_name, cmd.description))
            
            if cog_commands:
                mapping[cog_name] = cog_commands
                
        return mapping

    def get_home_embed(self):
        embed = discord.Embed(
            title="⚡ Central de Comandos & Ajuda",
            description=(
                f"Olá **{self.user.name}**! Bem-vindo ao painel de ajuda interativo.\n\n"
                f"💎 **Plano Ativo:** `{self.tier.upper()}`\n"
                f"📂 **Módulos Disponíveis:** `{len(self.current_mapping)}`\n\n"
                "Use o **menu abaixo** para navegar entre as categorias de comandos.\n"
                "Cada módulo contém ferramentas específicas para gestão do seu servidor."
            ),
            color=config.EMBED_COLOR
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_image(url="https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png")
        embed.set_footer(text="Aura System • Design by Senior Graphics", icon_url=self.bot.user.display_avatar.url)
        return embed

    def get_category_embed(self, cog_name, commands_list):
        emoji_map = {
            'general': '🌐', 'admin': '🛡️', 'sales': '💰', 'tickets': '🎫', 
            'faction_actions': '⚔️', 'hierarchy': '👑', 'punishments': '⚖️',
            'giveaway_system': '🎉', 'suggestions': '💡', 'welcome': '👋',
            'logs': '📜', 'monitor': '🖥️', 'setagem': '🏷️', 'timesheet': '⏱️'
        }
        emoji = emoji_map.get(cog_name.lower(), '🔹')
        
        embed = discord.Embed(
            title=f"{emoji} Módulo: {cog_name}",
            description=f"Visualizando comandos disponíveis para **{cog_name}**.",
            color=config.EMBED_COLOR
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        # Paginação simples se tiver muitos comandos (aqui vou listar todos, mas formatado)
        desc_text = ""
        for name, desc in commands_list:
            desc_text += f"> `{name}`\n> ▫️ *{desc}*\n\n"
            
        if not desc_text:
            desc_text = "Nenhum comando encontrado."
            
        embed.add_field(name="Lista de Comandos", value=desc_text, inline=False)
        embed.set_footer(text=f"Plano: {self.tier.upper()} • Total: {len(commands_list)} comandos")
        
        return embed

class PingView(ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @ui.button(label="Atualizar", style=discord.ButtonStyle.primary, emoji="🔄", custom_id="ping_refresh_btn")
    async def refresh_button(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        await self.cog.send_status_embed(interaction, is_update=True)

    @ui.button(label="Limpar", style=discord.ButtonStyle.secondary, emoji="🗑️", custom_id="ping_clear_btn")
    async def clear_button(self, interaction: discord.Interaction, button: ui.Button):
        # Remove do DB antes de deletar
        await self.cog.bot.db.execute("DELETE FROM active_pings WHERE message_id = ?", (interaction.message.id,))
        await self.cog.bot.db.commit()
        
        await interaction.message.delete()

async def setup(bot):
    await bot.add_cog(General(bot))