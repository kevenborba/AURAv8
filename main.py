import sys
import os

# Adiciona o diretório de bibliotecas locais ao path do Python
# Isso é necessário porque as deps foram instaladas em /app/.lib
if os.path.exists("/app/.lib"):
    sys.path.append("/app/.lib")

import discord
import asyncio
import traceback
from discord.ext import commands
from dotenv import load_dotenv

# Carrega variáveis de ambiente ANTES de importar módulos que as utilizam (como o dashboard)
load_dotenv()

# Importação completa do banco de dados
from database.bot_db import create_db, get_db_connection, check_guild_config
from dashboard.app import init_dashboard, run_dashboard
TOKEN = os.getenv('DISCORD_TOKEN')

# ====================================================
# 🚀 CONFIGURAÇÃO OFICIAL (INTENTS)
# ====================================================
# Isso exige que as 3 chaves (Presence, Server Members, Message Content)
# estejam ativadas no Discord Developer Portal.
intents = discord.Intents.all()

import logging
from collections import deque

# Handler de Logs para o Console do Painel
class ListLogHandler(logging.Handler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log_queue = deque(maxlen=100) # Guarda as últimas 100 linhas

    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_queue.append(msg)
        except Exception:
            self.handleError(record)

# Instância global do Handler
console_handler = ListLogHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s: %(message)s', datefmt='%d/%m/%Y %H:%M:%S'))
logging.getLogger().addHandler(console_handler)

class CityBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents, help_command=None, case_insensitive=True)
        self.db = None
        self.synced = False
        self.maintenance_mode = False # Flag do Modo Manutenção
        self.log_handler = console_handler # Referência para o Dashboard acessar
        self.tier_map = {} # Permissões Dinâmicas

    async def load_tier_permissions(self):
        """Carrega as permissões de tiers do banco de dados."""
        if not self.db: return
        
        try:
            print("🔄 [TIERS] Carregando definições de tiers...")
            async with self.db.execute("SELECT tier_name, module_name FROM tier_definitions") as cursor:
                rows = await cursor.fetchall()
            
            new_map = {'start': [], 'faction': [], 'police': [], 'v8': []}
            for tier, module in rows:
                if tier not in new_map: new_map[tier] = []
                new_map[tier].append(module)
                
            self.tier_map = new_map
            print(f"✅ [TIERS] Definições carregadas: {len(rows)} regras.")
        except Exception as e:
            print(f"❌ [TIERS] Falha ao carregar tiers: {e}")

    # ====================================================
    # 🔧 COMANDO DE EMERGÊNCIA: FIX BOT
    # ====================================================
    async def on_message(self, message):
        if message.author.bot: return
        
        # Apenas administradores
        if message.content == "!fix_bot" and message.author.guild_permissions.administrator:
            status_msg = await message.channel.send("🚨 **Iniciando Correção de Comandos...**")
            
            try:
                # 1. Limpa Comandos Globais (Remove Duplicatas Fantasmas)
                await status_msg.edit(content="🧹 [1/4] Limpando comandos globais antigos...")
                self.tree.clear_commands(guild=None)
                await self.tree.sync(guild=None) # Força a limpeza global

                # 2. Recarrega Cogs (Reler arquivos do disco)
                await status_msg.edit(content="🔄 [2/4] Recarregando módulos (Cogs)...")
                loaded = []
                if os.path.exists('./cogs'):
                    for filename in os.listdir('./cogs'):
                        if filename.endswith('.py'):
                            cog_name = f'cogs.{filename[:-3]}'
                            try:
                                await self.reload_extension(cog_name)
                                loaded.append(filename)
                            except commands.ExtensionNotLoaded:
                                await self.load_extension(cog_name)
                                loaded.append(filename)
                            except Exception as e:
                                await message.channel.send(f"⚠️ Erro ao carregar `{filename}`: {e}")

                # 3. Sincroniza Comandos APENAS para esta Guild (Instantâneo)
                await status_msg.edit(content=f"☁️ [3/4] Sincronizando Tree LOCAL (Cogs: {len(loaded)})...")
                
                # DEBUG CONSOLE
                print("📋 [DEBUG] Comandos identificados na Tree antes do Sync:")
                for cmd in self.tree.get_commands():
                    print(f"   - /{cmd.name} (Parent: {cmd.parent})")

                self.tree.copy_global_to(guild=message.guild)
                synced = await self.tree.sync(guild=message.guild)
                
                print(f"✅ [DEBUG] Comandos Sincronizados com Sucesso: {len(synced)}")
                for cmd in synced:
                    print(f"   + /{cmd.name} (ID: {cmd.id})")
                
                # 4. Finaliza
                await status_msg.edit(content=f"✅ **BOT CORRIGIDO!**\n\n"
                                            f"🧹 Globais: Limpos (Zero duplicatas)\n"
                                            f"📦 Módulos: {len(loaded)} recarregados\n"
                                            f"🔁 Locais: {len(synced)} sincronizados\n\n"
                                            f"⚠️ **IMPORTANTE:** Dê **Ctrl+R** agora para ver os comandos.")
                
            except Exception as e:
                import traceback
                traceback.print_exc()
                await status_msg.edit(content=f"❌ **FALHA CRÍTICA:** {e}")
        
        await self.process_commands(message)



    async def on_guild_join(self, guild):
        """Sincroniza comandos automaticamente ao entrar em um novo servidor."""
        print(f"📥 [AUTO-SYNC] Entrou em: {guild.name} ({guild.id})")
        try:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"✅ [AUTO-SYNC] Comandos sincronizados para: {guild.name}")
        except Exception as e:
            print(f"❌ [AUTO-SYNC] Falha ao sincronizar: {e}")

    async def maintenance_check(self, interaction: discord.Interaction):
        """Bloqueia interações se o modo manutenção estiver ativo, exceto para o Dono."""
        if self.maintenance_mode and interaction.user.id != int(os.getenv('OWNER_ID', 0)):
             await interaction.response.send_message("⚠️ **O Bot está em manutenção!** Tente novamente mais tarde.", ephemeral=True)
             return False
        return True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Global Check para Slash Commands (Interactions)."""
        # 1. Maintenance Check
        if not await self.maintenance_check(interaction): return False

        # 2. License Check
        if not interaction.guild: return True # DMs liberadas
        if not interaction.command: return True # Componentes soltos

        # Pega o nome do Cog
        cog_name = interaction.command.binding.__class__.__name__.lower() if interaction.command.binding else "unknown" # Ex: tickets, admin
        if not cog_name: return True 
        
        # Dono Bypass
        if interaction.user.id == int(os.getenv('OWNER_ID', 0)): return True

        # Verifica Banco
        guild_id = interaction.guild.id
        async with self.db.execute("SELECT status, tier FROM licenses WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            await interaction.response.send_message("🔒 **Este servidor não possui uma licença ativa.**", ephemeral=True)
            return False

        status, tier = row
        if status != 'active':
             await interaction.response.send_message("🔒 **Licença Suspensa ou Expirada.**", ephemeral=True)
             return False

        # Verifica Permissão Dinâmica
        allowed_cogs = self.tier_map.get(tier, [])
        if 'general' not in allowed_cogs: allowed_cogs.append('general')
        
        if cog_name not in allowed_cogs:
             await interaction.response.send_message(f"💎 **Recurso Bloqueado.**\nO módulo `{cog_name}` não está incluso no plano **{tier.upper()}**.", ephemeral=True)
             return False

        return True
        
        # HACK: Mapear comandos para Cogs ou usar a estrutura de module.
        # interaction.command.binding é a instância da classe (Cog).
        cog_name = "Unknown"
        if hasattr(interaction.command, 'binding'):
            cog = interaction.command.binding
            # Se for instância de Cog, pega o nome da classe
            if isinstance(cog, commands.Cog):
                 cog_name = cog.__class__.__name__
            else:
                 cog_name = str(cog)
        
        # Se não achou cog, libera (ex: comandos soltos no main)
        if cog_name == "Unknown": return True

        normalized_cog = cog_name.lower().replace('cogs.', '')
        
        # Exceções
        if normalized_cog in ['sales', 'admin', 'general']: return True 

        # Database Check
        tier = 'free'
        try:
             async with self.db.execute("SELECT tier FROM licenses WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
                 row = await cursor.fetchone()
             if row: tier = row[0]
        except:
             pass

        # Se não tem licença nenhuma
        if tier == 'free':
             await interaction.response.send_message("🚫 **Licença Inválida.** Adquira um plano.", ephemeral=True)
             return False

        allowed_cogs = self.TIER_MAP.get(tier, [])
        # Check permission
        is_allowed = False
        for allowed in allowed_cogs:
             if allowed.lower() in normalized_cog:
                 is_allowed = True
                 break
        
        if not is_allowed:
             await interaction.response.send_message(f"🔒 **Funcionalidade Bloqueada.** Seu plano ({tier.upper()}) não cobre `{cog_name}`.", ephemeral=True)
             return False

        return True

    async def setup_hook(self):
        print("⚙️ [SYSTEM] Iniciando setup...")
        
        # 1. Inicia Banco de Dados
        await create_db()
        self.db = await get_db_connection()
        print("✅ [DATABASE] Conexão estabelecida.")

        # 1.1 Carrega Tiers
        await self.load_tier_permissions()
        
        # Setagem do Global Interaction Check
        # O discord.py chama bot.interaction_check para todo slash command
        self.tree.interaction_check = self.interaction_check
        
        # 2. Carrega Cogs (Plugins)
        print("🔄 [SYSTEM] Carregando Cogs...")
        if os.path.exists('./cogs'):
            for filename in os.listdir('./cogs'):
                if filename.endswith('.py'):
                    try:
                        await self.load_extension(f'cogs.{filename[:-3]}')
                        print(f'   ├─ 🧩 {filename} carregado.')
                    except Exception as e:
                        print(f'   └─ ❌ FALHA CRÍTICA em {filename}:')
                        traceback.print_exc()

        # 3. Inicia Painel Web (Background Task)
        print("🌐 [SYSTEM] Iniciando Dashboard...")
        init_dashboard(self)
        self.loop.create_task(run_dashboard())

        # 4. Sincroniza Comandos (/)
        print("☁️ [SYSTEM] Auto-Sync Global desativado para evitar duplicatas.")
        # try:
        #     await self.tree.sync() 
        #     print("✅ [SYSTEM] Sincronização concluída.")
        # except Exception as e:
        #     print(f"⚠️ [SYSTEM] Aviso na sincronização (Rate Limit ou Erro): {e}")

    async def close(self):
        if self.db: await self.db.close()
        await super().close()

    async def on_ready(self):
        print(f'''
        ╔════════════════════════════════════════╗
        ║  🤖 {self.user.name} ESTÁ ONLINE!      ║
        ║  ID: {self.user.id}                    ║
        ╚════════════════════════════════════════╝
        ''')
        
        # 4. Verifica Configurações dos Servidores
        print("🔍 [SYSTEM] Verificando configurações dos servidores...")
        for guild in self.guilds:
            if self.db:
                await check_guild_config(guild.id, self.db)
        print(f"✅ [SYSTEM] Configurações validadas para {len(self.guilds)} servidores.")
        
        # 5. Define Status
        try:
            await self.change_presence(activity=discord.Game(name="Gerenciando a Cidade"), status=discord.Status.online)
            print("🎮 [SYSTEM] Status definido com sucesso.")
        except Exception as e:
            print(f"⚠️ [SYSTEM] Não foi possível definir status: {e}")

    async def on_guild_join(self, guild):
        print(f"➕ [GUILD JOIN] Novo servidor: {guild.name} (ID: {guild.id})")
        if self.db:
            await check_guild_config(guild.id, self.db)

    async def on_guild_remove(self, guild):
        print(f"➖ [GUILD LEAVE] Removido de: {guild.name} (ID: {guild.id})")
        # Registra na Audit Log para aparecer na "Fila de Limpeza" do painel
        if self.db:
            from datetime import datetime
            await self.db.execute("INSERT INTO audit_logs (user_id, action, target, timestamp) VALUES (?, ?, ?, ?)",
                                  (self.user.id, "BOT_REMOVED", guild.id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            await self.db.commit()

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        print(f"❌ [ERROR] Comando '{ctx.command}' falhou: {error}")
        traceback.print_exc()
        try:
            await ctx.send(f"❌ **Erro no Comando:** `{error}`")
        except: pass

bot = CityBot()

if __name__ == '__main__':
    try:
        bot.run(TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        print("\n❌ ERRO DE PERMISSÃO:")
        print("Você esqueceu de ativar os 'Privileged Gateway Intents' no site do Discord Developer.")
        print("Vá em: https://discord.com/developers/applications -> Bot -> Privileged Gateway Intents")
        print("Ative as 3 opções (Presence, Server Members, Message Content) e salve.")