import discord
from discord.ext import commands, tasks
import logging
import datetime
import time
from collections import deque
import io
try:
    import psutil
except ImportError:
    psutil = None
import matplotlib.pyplot as plt
import sys
import os

# --- CONFIGURAÇÃO ---
# ID do Admin (Fallback se não tiver no DB)
DEFAULT_ADMIN_ID = 216807300810276866 
INVISIBLE_WIDE_URL = "https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png"

# Configuração de Logs em Memória
log_stream = io.StringIO()
handler = logging.StreamHandler(log_stream)
handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%H:%M:%S'))
logging.getLogger().addHandler(handler)

class MonitorView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🔄 Atualizar", style=discord.ButtonStyle.primary, custom_id="mon_refresh")
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.update_panel()

    @discord.ui.button(label="🧹 Limpar Logs", style=discord.ButtonStyle.secondary, custom_id="mon_clear")
    async def clear_logs(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.cog.log_buffer.clear()
        log_stream.truncate(0)
        log_stream.seek(0)
        await interaction.response.send_message("🧹 Logs limpos.", ephemeral=True)
        await self.cog.update_panel()

    @discord.ui.button(label="🔒 Manutenção", style=discord.ButtonStyle.danger, custom_id="mon_lock")
    async def maintenance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔒 Modo manutenção ativado (Simulação).", ephemeral=True)

    @discord.ui.button(label="🛑 Desligar", style=discord.ButtonStyle.danger, custom_id="mon_shutdown")
    async def shutdown(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🛑 Desligando...", ephemeral=True)
        await self.cog.bot.close()

class Monitor(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
        self.admin_id = DEFAULT_ADMIN_ID
        
        self.stats = {"msgs": 0, "cmds": 0, "errors": 0, "uploads": 0}
        self.dm_message = None
        self.is_monitoring = False
        self.log_buffer = deque(maxlen=15)
        self.latency_history = deque(maxlen=20)
        
        # Configuração do Matplotlib
        plt.style.use('dark_background')

    async def cog_load(self):
        self.bot.add_view(MonitorView(self))
        print("[+] [Monitor] Views persistentes carregadas.")
        
        # Tenta carregar ID do admin de uma tabela global (se existir) ou usa o default
        # Como o bot usa config por guild, vamos manter o default por enquanto ou criar uma tabela global futura
        # Para este MVP, usaremos o ID hardcoded/default.
        
        # Inicia monitoramento se o bot já estiver pronto
        if self.bot.is_ready():
            await self.start_session()

    def get_uptime_str(self):
        diff = int(time.time() - self.start_time)
        d, r = divmod(diff, 86400); h, r = divmod(r, 3600); m, s = divmod(r, 60)
        return f"{d}d {h}h {m}m {s}s"

    def get_logs(self):
        # Captura logs do stream
        raw = log_stream.getvalue().split('\n')
        for line in raw:
            if line.strip(): self.log_buffer.append(line)
        log_stream.truncate(0); log_stream.seek(0)
        return "\n".join(list(self.log_buffer))

    def generate_graph(self):
        """Gera um gráfico de latência em memória com eixos."""
        if not self.latency_history: return None
        
        fig, ax = plt.subplots(figsize=(8, 3)) # Um pouco maior para caber labels
        
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

    # --- Listeners ---
    @commands.Cog.listener()
    async def on_ready(self):
        if not self.is_monitoring: await self.start_session()

    @commands.Cog.listener()
    async def on_message(self, m):
        if m.author.bot: return
        self.stats["msgs"] += 1
        if m.attachments: self.stats["uploads"] += 1

    @commands.Cog.listener()
    async def on_command_completion(self, ctx): self.stats["cmds"] += 1
    
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error): self.stats["errors"] += 1

    # --- Logica ---
    async def start_session(self):
        try:
            user = await self.bot.fetch_user(self.admin_id)
            if not user: 
                print(f"⚠️ [Monitor] Admin ID {self.admin_id} não encontrado.")
                return
            
            # Tenta criar DM se não existir
            if not user.dm_channel: await user.create_dm()

            # Envia mensagem inicial
            self.dm_message = await user.send("🚀 **Cockpit Iniciado...**", view=MonitorView(self))
            self.is_monitoring = True
            
            if not self.update_loop.is_running(): 
                self.update_loop.start()
                
        except Exception as e: 
            print(f"❌ [Monitor] Erro ao iniciar sessão DM: {e}")

    async def update_panel(self):
        if not self.dm_message: return
        try:
            # Coleta dados
            logs = self.get_logs() or "..."
            ping = round(self.bot.latency * 1000)
            self.latency_history.append(ping)
            
            # Hardware Stats
            if psutil:
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory().percent
            else:
                cpu = 0
                ram = 0
            
            # Alertas Inteligentes
            if ping > 500: await self.send_alert(f"⚠️ Alta Latência: {ping}ms")
            if cpu > 90: await self.send_alert(f"⚠️ Alta CPU: {cpu}%")
            if ram > 90: await self.send_alert(f"⚠️ Alta RAM: {ram}%")

            # Define cor
            color = 0x000000 
            status_emoji = "🟢" if ping < 200 else ("🟠" if ping < 500 else "🔴")

            embed = discord.Embed(title="🚀 Cockpit de Controle", color=color, timestamp=datetime.datetime.now())
            
            # Thumbnail com Avatar do Bot
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            
            # Descrição com Status Principal
            embed.description = f"**Status do Sistema:** {status_emoji}\n**Uptime:** `{self.get_uptime_str()}`"
            
            # Campos lado a lado
            embed.add_field(name="📡 Rede", value=f"**Ping:** `{ping}ms`\n**Msgs:** `{self.stats['msgs']}`", inline=True)
            embed.add_field(name="💻 Hardware", value=f"**CPU:** `{cpu}%`\n**RAM:** `{ram}%`", inline=True)
            embed.add_field(name="⚙️ Bot", value=f"**Cmds:** `{self.stats['cmds']}`\n**Erros:** `{self.stats['errors']}`", inline=True)

            # Terminal
            embed.add_field(name=">_ Terminal", value=f"```ini\n{logs[-800:]}\n```", inline=False)
            embed.set_footer(text="Atualização a cada 1 minuto")

            # Gráfico
            graph_buf = self.generate_graph()
            files = []
            if graph_buf:
                files.append(discord.File(graph_buf, filename="graph.png"))
                embed.set_image(url="attachment://graph.png")
            else:
                embed.set_image(url=INVISIBLE_WIDE_URL)

            await self.dm_message.edit(embed=embed, attachments=files)
            
        except discord.NotFound:
            # Se a mensagem foi apagada, tenta reiniciar
            self.update_loop.cancel()
            self.is_monitoring = False
            await self.start_session()
        except Exception as e: 
            print(f"❌ [Monitor] Erro Loop: {e}")

    async def send_alert(self, msg):
        """Envia alerta na DM sem atrapalhar o painel."""
        if self.dm_message:
            try: await self.dm_message.channel.send(f"🚨 **ALERTA:** {msg}", delete_after=60)
            except: pass

    @tasks.loop(minutes=1) 
    async def update_loop(self):
        await self.update_panel()

    @commands.hybrid_command(name="monitor", hidden=True, description="Força o início do painel de monitoramento.")
    async def force_mon(self, ctx):
        if ctx.author.id == self.admin_id:
            try: await ctx.message.delete()
            except: pass
            
            if ctx.interaction:
                await ctx.send("Iniciando...", ephemeral=True, delete_after=2)
            
            await self.start_session()

async def setup(bot):
    await bot.add_cog(Monitor(bot))
