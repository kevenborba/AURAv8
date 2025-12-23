import discord
from discord.ext import tasks, commands
from discord import app_commands, ui
import json
import datetime
import asyncio

# ====================================================
# 🎨 CORES E CONSTANTES
# ====================================================
COLOR_OPEN = 0x000000      # Preto (Aberto)
COLOR_FULL = 0x3498db      # Azul (Lotado)
COLOR_WIN = 0x2ecc71       # Verde (Vitória)
COLOR_LOSS = 0xe74c3c      # Vermelho (Derrota)
INVISIBLE_WIDE_URL = "https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png"

def parse_emoji(custom_emoji):
    if not custom_emoji: return None
    custom_emoji = custom_emoji.strip()
    if custom_emoji.startswith("<"):
        try: return discord.PartialEmoji.from_str(custom_emoji)
        except: pass
    return custom_emoji

class FactionActions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_ranking_loop.start()

    def cog_unload(self):
        self.auto_ranking_loop.cancel()

    # ====================================================
    # � LOOP DE RANKING AUTOMÁTICO
    # ====================================================
    @tasks.loop(hours=1)
    async def auto_ranking_loop(self):
        async with self.bot.db.execute("SELECT guild_id, action_ranking_channel_id FROM config") as cursor:
            configs = await cursor.fetchall()
        
        for guild_id, channel_id in configs:
            if not channel_id: continue
            
            guild = self.bot.get_guild(guild_id)
            if not guild: continue
            
            channel = guild.get_channel(channel_id)
            if not channel: continue
            
            embed = await self._build_ranking_embed(guild)
            
            # Tenta editar a última mensagem do bot ou envia uma nova
            try:
                last_message = None
                async for msg in channel.history(limit=10):
                    if msg.author == self.bot.user:
                        last_message = msg
                        break
                
                if last_message:
                    await last_message.edit(embed=embed)
                else:
                    await channel.send(embed=embed)

                # Backup Webhook
                async with self.bot.db.execute("SELECT action_ranking_webhook FROM config WHERE guild_id = ?", (guild_id,)) as cursor:
                    res = await cursor.fetchone()
                
                webhook_url = res[0] if res else None
                if webhook_url:
                    try:
                        async with aiohttp.ClientSession() as session:
                            webhook = discord.Webhook.from_url(webhook_url, session=session)
                            await webhook.send(embed=embed, username=f"Backup Ranking - {guild.name}", avatar_url=self.bot.user.display_avatar.url)
                        print(f"✅ [WEBHOOK] Backup enviado com sucesso para Guild {guild_id}")
                    except Exception as we:
                        print(f"⚠️ [WEBHOOK ERROR] Falha ao enviar backup: {we}")

            except Exception as e:
                print(f"❌ [RANKING ERROR] Erro no loop de ranking (Guild {guild_id}): {e}")
                import traceback
                traceback.print_exc()

    @auto_ranking_loop.before_loop
    async def before_auto_ranking(self):
        print("⏳ [RANKING] Aguardando bot estar pronto...")
        await self.bot.wait_until_ready()
        print("✅ [RANKING] Bot pronto. Loop iniciado.")



    # ====================================================
    # �🛠️ COMANDOS DE CONFIGURAÇÃO
    # ====================================================
    @app_commands.command(name="painel_acoes", description="Painel de Configuração das Ações.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.send_config_panel(interaction)

    async def send_config_panel(self, interaction: discord.Interaction, is_edit=False):
        async with self.bot.db.execute("SELECT * FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()
            cfg = dict(zip([d[0] for d in cursor.description], row)) if row else {}

        embed = discord.Embed(title="⚙️ Configuração de Ações", color=0x2b2d31)
        embed.description = (
            f"**Canais & Cargos**\n"
            f"📢 Canal de Ações: {('<#' + str(cfg.get('action_channel_id')) + '>') if cfg.get('action_channel_id') else '🔴 Não definido'}\n"
            f"📜 Canal de Logs: {('<#' + str(cfg.get('action_logs_channel_id')) + '>') if cfg.get('action_logs_channel_id') else '🔴 Não definido'}\n"
            f"🏆 Canal de Ranking: {('<#' + str(cfg.get('action_ranking_channel_id')) + '>') if cfg.get('action_ranking_channel_id') else '🔴 Não definido'}\n"
            f"🛡️ Cargo de Menção: {('<@&' + str(cfg.get('action_role_id')) + '>') if cfg.get('action_role_id') else '🔴 Não definido'}\n\n"
            f"**Emojis Atuais**\n"
            f"Participar: {cfg.get('action_emoji_join') or '🔫'}\n"
            f"Cancelar: {cfg.get('action_emoji_leave') or '✖️'}\n"
            f"Vitória: {cfg.get('action_emoji_win') or '🏆'}\n"
            f"Derrota: {cfg.get('action_emoji_loss') or '💀'}\n"
            f"Notificar: {cfg.get('action_emoji_notify') or '🔔'}\n"
            f"Editar: {cfg.get('action_emoji_edit') or '✏️'}\n"
        )
        
        view = ActionConfigView(self.bot, self)
        if is_edit: await interaction.edit_original_response(embed=embed, view=view)
        else: await interaction.followup.send(embed=embed, view=view)

    async def _get_emojis(self, guild_id):
        async with self.bot.db.execute("SELECT action_emoji_join, action_emoji_leave, action_emoji_win, action_emoji_loss, action_emoji_notify, action_emoji_edit FROM config WHERE guild_id = ?", (guild_id,)) as cursor:
            row = await cursor.fetchone()
        if not row: return {}
        return {
            'join': row[0], 'leave': row[1], 'win': row[2], 'loss': row[3], 'notify': row[4], 'edit': row[5]
        }

    async def _check_db_columns(self):
        async with self.bot.db.execute("PRAGMA table_info(faction_actions)") as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        
        if "category" not in columns:
            print("⚠️ Coluna 'category' não encontrada em faction_actions. Adicionando...")
            await self.bot.db.execute("ALTER TABLE faction_actions ADD COLUMN category TEXT DEFAULT 'PVP'")
            await self.bot.db.commit()
            print("✅ Coluna 'category' adicionada com sucesso.")
            
        # Tabela de Bônus Manual
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS ranking_bonus (
                user_id INTEGER,
                guild_id INTEGER,
                bonus_wins INTEGER DEFAULT 0,
                bonus_actions INTEGER DEFAULT 0,
                bonus_mvps INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            )
        """)
        await self.bot.db.commit()

        # Webhook Column (Config Table)
        async with self.bot.db.execute("PRAGMA table_info(config)") as cursor:
            cols = [row[1] for row in await cursor.fetchall()]
            
        if "action_ranking_webhook" not in cols:
             print("⚠️ Coluna 'action_ranking_webhook' não encontrada em config. Adicionando...")
             await self.bot.db.execute("ALTER TABLE config ADD COLUMN action_ranking_webhook TEXT")
             await self.bot.db.commit()
             print("✅ Coluna 'action_ranking_webhook' adicionada.")

    # ====================================================
    # 📊 RANKING
    # ====================================================
    @app_commands.command(name="ranking_acoes", description="Mostra o ranking dos membros mais ativos nas ações.")
    @app_commands.describe(categoria="Filtrar por categoria (Opcional)")
    @app_commands.choices(categoria=[
        app_commands.Choice(name="PVP", value="PVP"),
        app_commands.Choice(name="Fuga", value="Fuga"),
        app_commands.Choice(name="Geral (Todas)", value="ALL")
    ])
    async def ranking_actions(self, interaction: discord.Interaction, categoria: str = "ALL"):
        await interaction.response.defer()
        embed = await self._build_ranking_embed(interaction.guild, category=categoria if categoria != "ALL" else None)
        await interaction.followup.send(embed=embed)

    async def _build_ranking_embed(self, guild, category=None):
        # Busca todas as ações finalizadas (WIN ou LOSS)
        query = "SELECT participants, status, mvp_id FROM faction_actions WHERE guild_id = ? AND status IN ('WIN', 'LOSS')"
        params = [guild.id]
        
        if category:
            query += " AND category = ?"
            params.append(category)
            
        async with self.bot.db.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
            
        print(f"📊 [RANKING DEBUG] Guild {guild.id} | Categoria: {category} | Rows: {len(rows)}")
        if rows:
            print(f"   > Exemplo Row 0: {rows[0]}")
            
        scores = {}
        
        if rows:
            for row in rows:
                try:
                    participants = json.loads(row[0]) if row[0] else []
                except Exception as e:
                    print(f"⚠️ [RANKING ERROR] Falha ao ler participantes da Row: {row} -> {e}")
                    participants = []

                status = row[1]
                mvp_id = row[2]
                
                for uid in participants:
                    if uid not in scores: scores[uid] = {'total': 0, 'wins': 0, 'mvps': 0}
                    scores[uid]['total'] += 1
                    if status == 'WIN': scores[uid]['wins'] += 1
                
                if mvp_id:
                    if mvp_id not in scores: scores[mvp_id] = {'total': 0, 'wins': 0, 'mvps': 0}
                    scores[mvp_id]['mvps'] += 1
        
        # Injeta Pontos Manuais (Bônus)
        async with self.bot.db.execute("SELECT user_id, bonus_actions, bonus_wins, bonus_mvps FROM ranking_bonus WHERE guild_id = ?", (guild.id,)) as cursor:
             bonus_rows = await cursor.fetchall()
             
        for uid, b_act, b_wins, b_mvps in bonus_rows:
            if uid not in scores: scores[uid] = {'total': 0, 'wins': 0, 'mvps': 0}
            scores[uid]['total'] += b_act
            scores[uid]['wins'] += b_wins
            scores[uid]['mvps'] += b_mvps

        # Ordena por total de participações
        sorted_scores = sorted(scores.items(), key=lambda x: x[1]['total'], reverse=True)[:10]
        
        embed = discord.Embed(title=f"🏆 Ranking de Ações ({category if category else 'Geral'})", color=COLOR_OPEN)
        description = ""
        
        if not sorted_scores:
            description = "Nenhum dado relevante."
        else:
            for idx, (uid, stats) in enumerate(sorted_scores):
                user = guild.get_member(uid)
                name = user.mention if user else f"ID: {uid}"
                win_rate = int((stats['wins'] / stats['total']) * 100) if stats['total'] > 0 else 0
                
                emoji = "🥇" if idx == 0 else "🥈" if idx == 1 else "🥉" if idx == 2 else f"{idx+1}."
                description += f"**{emoji} {name}**\n└ ⚔️ {stats['total']} Ações | 🏆 {stats['wins']} Vitórias ({win_rate}%) | ⭐ {stats['mvps']} MVPs\n\n"
            
        embed.description = description
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_image(url=INVISIBLE_WIDE_URL)
        embed.timestamp = datetime.datetime.now()
        
        return embed

    @app_commands.command(name="resetar_ranking_acoes", description="⚠️ Zera todo o histórico de ações e ranking.")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_ranking(self, interaction: discord.Interaction):
        embed = discord.Embed(title="⚠️ PERIGO: Resetar Ranking", color=0xe74c3c)
        embed.description = (
            "Você está prestes a **APAGAR TODO O HISTÓRICO** de ações e votos de MVP deste servidor.\n"
            "Isso zerará o ranking e não poderá ser desfeito.\n\n"
            "Tem certeza que deseja continuar?"
        )
        await interaction.response.send_message(embed=embed, view=ResetRankingConfirmView(self.bot), ephemeral=True)

    @app_commands.command(name="adicionar_pontos", description="➕ Adiciona pontos manuais ao ranking (Recuperação de dados).")
    @app_commands.describe(membro="Membro para adicionar pontos", acoes="Quantidade de ações", vitorias="Quantidade de vitórias", mvps="Quantidade de MVPs")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_points(self, interaction: discord.Interaction, membro: discord.Member, acoes: int = 0, vitorias: int = 0, mvps: int = 0):
        await interaction.response.defer(ephemeral=True)
        
        # Update or Insert (Upsert)
        await self.bot.db.execute("""
            INSERT INTO ranking_bonus (user_id, guild_id, bonus_actions, bonus_wins, bonus_mvps)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET
            bonus_actions = bonus_actions + excluded.bonus_actions,
            bonus_wins = bonus_wins + excluded.bonus_wins,
            bonus_mvps = bonus_mvps + excluded.bonus_mvps
        """, (membro.id, interaction.guild.id, acoes, vitorias, mvps))
        
        await self.bot.db.commit()
        await interaction.followup.send(f"✅ Adicionado para {membro.mention}:\n+ {acoes} Ações\n+ {vitorias} Vitórias\n+ {mvps} MVPs", ephemeral=True)

    @app_commands.command(name="remover_pontos", description="⚠️ Remove TODOS os pontos manuais de um usuário.")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_points(self, interaction: discord.Interaction, membro: discord.Member):
        await self.bot.db.execute("DELETE FROM ranking_bonus WHERE user_id = ? AND guild_id = ?", (membro.id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Pontos manuais de {membro.mention} removidos.", ephemeral=True)



    # ====================================================
    # 🚀 COMANDO DE CRIAÇÃO (PREFIXO - FALLBACK)
    # ====================================================
    @commands.command(name="acao_txt", aliases=["act_old"])
    async def create_action_prefix(self, ctx, acao: str, data: str, hora: str, vagas: int, categoria: str = "PVP"):
        """Cria uma ação (Modo Texto). Uso: !criar_acao "Nome" "Data" "Hora" Vagas Categoria"""
        # Adapta o Context para parecer uma Interaction (Duck Typing básico)
        class FakeInteraction:
            def __init__(self, context):
                self.user = context.author
                self.guild = context.guild
                self.channel = context.channel
                self.message = context.message
                self.response = self
                self.followup = self
            
            async def defer(self, ephemeral=True):
                await ctx.message.add_reaction("⏳")
            
            async def send_message(self, content=None, embed=None, view=None, ephemeral=True):
                 # Ignora ephemeral no prefix command
                 await ctx.send(content=content, embed=embed, view=view)
            
            async def send(self, content=None, embed=None, view=None, ephemeral=True):
                 await ctx.send(content=content, embed=embed, view=view)

        fake_interaction = FakeInteraction(ctx)
        
        # Chama a função original do Slash Command
        await self.create_action(fake_interaction, acao, data, hora, vagas, categoria)

    # ====================================================
    # 🚀 COMANDO DE CRIAÇÃO
    # ====================================================
    @app_commands.command(name="criar_acao", description="Cria uma nova ação para a facção.")
    @app_commands.describe(acao="Nome da Ação", data="Data (Ex: Hoje, 12/12)", hora="Horário (Ex: 20:00)", vagas="Número de vagas", categoria="Tipo de ação")
    @app_commands.choices(categoria=[
        app_commands.Choice(name="PVP", value="PVP"),
        app_commands.Choice(name="Fuga", value="Fuga")
    ])
    async def create_action(self, interaction: discord.Interaction, acao: str, data: str, hora: str, vagas: int, categoria: str):
        # Wrapper para o Slash Command
        await interaction.response.defer(ephemeral=True)
        await self._create_action_logic(interaction, acao, f"{data} às {hora}", vagas, categoria)

    # ----------------------------------------------------
    # Lógica Central de Criação (Reutilizável)
    # ----------------------------------------------------
    async def _create_action_logic(self, interaction: discord.Interaction, acao: str, data_hora_str: str, vagas: int, categoria: str):
        try:
            # 1. Verifica Configurações
            async with self.bot.db.execute("SELECT action_channel_id, action_role_id FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
                res = await cursor.fetchone()
            
            if not res or not res[0]:
                return await interaction.followup.send("❌ Canal de ações não configurado! Use `/painel_acoes`.", ephemeral=True)
            
            channel = self.bot.get_channel(res[0])
            role_id = res[1]
            role = interaction.guild.get_role(role_id) if role_id else None
            
            if not channel:
                return await interaction.followup.send("❌ Canal configurado não encontrado.", ephemeral=True)

            # 2. Prepara Dados Iniciais
            action_data = {
                "name": acao,
                "datetime": data_hora_str,
                "slots": vagas,
                "responsible": interaction.user.id,
                "participants": [],
                "cancellations": [],
                "status": "OPEN",
                "profit": None,
                "category": categoria
            }

            # 3. Gera Embed e View
            embed = self._build_embed(interaction.guild, action_data)
            
            emojis = await self._get_emojis(interaction.guild.id)
            view = ActionView(self.bot, action_data, emojis)

            # 4. Envia Mensagem (com menção se houver cargo)
            content = role.mention if role else None
            try:
                message = await channel.send(content=content, embed=embed, view=view)
            except Exception as e:
                return await interaction.followup.send(f"❌ Erro ao enviar mensagem no canal {channel.mention}: {e}\nVerifique permissões do bot.", ephemeral=True)

            # 5. Salva no Banco
            try:
                await self.bot.db.execute("""
                    INSERT INTO faction_actions (
                        message_id, channel_id, guild_id, responsible_id, 
                        action_name, date_time, slots, status, participants, cancellations, category
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    message.id, channel.id, interaction.guild.id, interaction.user.id,
                    acao, data_hora_str, vagas, "OPEN", json.dumps([]), json.dumps([]), categoria
                ))
                await self.bot.db.commit()
            except Exception as dbe:
                # Tenta apagar a mensagem se falhar no banco para não ficar fantasma
                await message.delete()
                raise dbe

            await interaction.followup.send(f"✅ Ação criada com sucesso em {channel.mention}!", ephemeral=True)
            
        except Exception as error:
            import traceback
            traceback.print_exc()
            await interaction.followup.send(f"❌ **Erro Crítico:** {error}", ephemeral=True)

    # ====================================================
    # 📦 HELPER: CONSTRUTOR DE EMBED
    # ====================================================
    def _build_embed(self, guild, data):
        # Define Cor baseada no Status
        if data['status'] == 'WIN': color = COLOR_WIN
        elif data['status'] == 'LOSS': color = COLOR_LOSS
        elif data['status'] == 'FULL': color = COLOR_FULL
        else: color = COLOR_OPEN

        embed = discord.Embed(title=f"⚔️ {data['name']} | {data.get('category', 'PVP')}", color=color)
        
        responsible = guild.get_member(data['responsible'])
        resp_name = responsible.mention if responsible else "Desconhecido"

        embed.add_field(name="📅 Data/Hora", value=data['datetime'], inline=True)
        embed.add_field(name="👮 Responsável", value=resp_name, inline=True)
        
        # Lista de Participantes
        participants_text = ""
        slots = data['slots']
        participants = data['participants']
        
        for i in range(slots):
            idx = i + 1
            if i < len(participants):
                uid = participants[i]
                user = guild.get_member(uid)
                name = user.mention if user else f"ID: {uid}"
                participants_text += f"`{idx}.` {name}\n"
            else:
                participants_text += f"`{idx}.` *Vaga Disponível*\n"
        
        embed.add_field(name=f"👥 Escalados ({len(data['participants'])}/{data['slots']})", value=participants_text, inline=False)

        # Lucro (se houver)
        if data.get('profit'):
            embed.add_field(name="💰 Lucro", value=f"```\n{data['profit']}\n```", inline=False)

        # Cancelamentos
        if data.get('cancellations'):
            cancel_text = ""
            for c in data['cancellations']:
                user = guild.get_member(c['user_id'])
                name = user.name if user else "Desconhecido"
                cancel_text += f"• **{name}**: {c['reason']}\n"
            embed.add_field(name="⚠️ Cancelamentos", value=cancel_text, inline=False)

        # MVP
        if data.get('mvp_id'):
            embed.add_field(name="⭐ MVP da Ação", value=f"<@{data['mvp_id']}>", inline=False)

        embed.set_footer(text=f"Status: {data['status']}")
        embed.timestamp = datetime.datetime.now()
        
        # Ultra Wide & Avatar
        embed.set_image(url=INVISIBLE_WIDE_URL)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)

        return embed

    # ====================================================
    # 🔄 RECARREGAR VIEWS (PERSISTÊNCIA)
    # ====================================================
    @commands.Cog.listener()
    async def on_ready(self):
        await self._check_db_columns()
        self.bot.add_view(ActionView(self.bot, {}))
        self.bot.add_view(ActionCreationDashboard(self.bot, self))
        print("✅ [FactionActions] Dashboard de Criação carregado.")

    # ====================================================
    # 🖥️ PAINEL DE CRIAÇÃO (WORKAROUND)
    # ====================================================
    # ====================================================
    # 🖥️ PAINEL DE CRIAÇÃO (WORKAROUND)
    # ====================================================
    @commands.hybrid_command(name="painel_criacao", aliases=["setup_criacao", "criar_painel"])
    @commands.has_permissions(administrator=True)
    async def setup_creation_panel(self, ctx):
        """Posta o Painel de Criação de Ações (Premium)"""
        print(f"🔧 [DEBUG] Comando setup_criacao chamado por {ctx.author}")
        try:
            # Tenta deletar mensagem original se for texto
            if ctx.interaction is None:
                try: 
                    await ctx.message.delete()
                except: pass
            else:
                await ctx.interaction.response.defer(ephemeral=True)

            embed = discord.Embed(title="CENTRAL DE OPERAÇÕES", color=0x2b2d31)
            embed.description = (
                "Para iniciar uma nova operação, utilize o botão abaixo.\n"
                "Preencha o formulário com atenção aos horários e limites de vagas."
            )
            embed.set_image(url=INVISIBLE_WIDE_URL)
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            embed.set_footer(text="Sistema de Gestão de Facções")
            
            view = ActionCreationDashboard(self.bot, self)
            
            # Se for slash, envia no canal (não ephemeral)
            if ctx.interaction:
                await ctx.channel.send(embed=embed, view=view)
                await ctx.interaction.followup.send("✅ Painel enviado!", ephemeral=True)
            else:
                await ctx.send(embed=embed, view=view)
                
            print("✅ [DEBUG] Painel enviado com sucesso.")
            
        except Exception as e:
            print(f"❌ [DEBUG] Erro no setup_criacao: {e}")
            import traceback
            traceback.print_exc()
            if ctx.interaction:
                await ctx.interaction.followup.send(f"❌ Erro: {e}", ephemeral=True)
            else:
                await ctx.send(f"❌ Erro: {e}")

# ====================================================
# 🖥️ VIEWS E MODAIS (EXTERNAS)
# ====================================================

class ActionCreationDashboard(ui.View):
    def __init__(self, bot, cog):
        super().__init__(timeout=None)
        self.bot = bot
        self.cog = cog

    @ui.button(label="Criar Nova Ação", style=discord.ButtonStyle.secondary, emoji="📝", custom_id="dashboard_create_btn")
    async def create_btn(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(ActionCreationModal(self.bot, self.cog))

class ActionCreationModal(ui.Modal, title="Nova Operação"):
    name = ui.TextInput(label="Nome da Ação", placeholder="Ex: Invasão Favela...", style=discord.TextStyle.short)
    date = ui.TextInput(label="Data e Hora", placeholder="Ex: Hoje às 20:00", style=discord.TextStyle.short)
    slots = ui.TextInput(label="Vagas", placeholder="Número de participantes (Ex: 15)", style=discord.TextStyle.short)

    def __init__(self, bot, cog):
        super().__init__()
        self.bot = bot; self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            vagas = int(self.slots.value)
        except:
            return await interaction.response.send_message("❌ O campo 'Vagas' deve ser um número.", ephemeral=True)
            
        # Pede a Categoria
        view = CategorySelectView(self.bot, self.cog, self.name.value, self.date.value, vagas)
        await interaction.response.send_message("📂 **Selecione a Categoria da Operação:**", view=view, ephemeral=True)

class CategorySelectView(ui.View):
    def __init__(self, bot, cog, name, date, slots):
        super().__init__(timeout=60)
        self.bot = bot; self.cog = cog
        self.data = {'name': name, 'date': date, 'slots': slots}

    @ui.select(placeholder="Selecione a Categoria...", options=[
        discord.SelectOption(label="PVP (Tiroteio)", value="PVP", emoji="🔫"),
        discord.SelectOption(label="Fuga (Perseguição)", value="Fuga", emoji="🚔"),
        discord.SelectOption(label="Reunião", value="Reunião", emoji="📜"),
        discord.SelectOption(label="Outro", value="Outro", emoji="❓")
    ])
    async def select_category(self, interaction: discord.Interaction, select: ui.Select):
        category = select.values[0]
        
        # Chama o helper de lógica
        await self.cog._create_action_logic(interaction, self.data['name'], self.data['date'], self.data['slots'], category)

# ====================================================
# 🖥️ VIEWS E MODAIS (DO SISTEMA DE AÇÃO)
# ====================================================

class ActionView(ui.View):
    def __init__(self, bot, action_data, emojis=None):
        super().__init__(timeout=None)
        self.bot = bot
        self.action_data = action_data
        
        if emojis:
            if emojis.get('join'): self.join_action.emoji = parse_emoji(emojis['join'])
            if emojis.get('leave'): self.leave_action.emoji = parse_emoji(emojis['leave'])
            if emojis.get('win'): self.win_action.emoji = parse_emoji(emojis['win'])
            if emojis.get('loss'): self.loss_action.emoji = parse_emoji(emojis['loss'])
            if emojis.get('notify'): self.notify_participants.emoji = parse_emoji(emojis['notify'])
            if emojis.get('edit'): self.edit_action.emoji = parse_emoji(emojis['edit'])

        # Atualiza label do botão de participar
        if self.action_data and 'participants' in self.action_data and 'slots' in self.action_data:
            participants_len = len(self.action_data['participants'])
            slots = self.action_data['slots']
            
            if participants_len >= slots:
                self.join_action.label = "Lotado"
                self.join_action.disabled = True
                self.join_action.style = discord.ButtonStyle.danger
            else:
                self.join_action.label = f"Participar ({participants_len}/{slots})"
                self.join_action.disabled = False

    async def _update_message(self, interaction, new_data):
        # Atualiza DB
        await self.bot.db.execute("""
            UPDATE faction_actions 
            SET status=?, participants=?, cancellations=?, profit=?, action_name=?, date_time=?, slots=?
            WHERE message_id=?
        """, (
            new_data['status'], json.dumps(new_data['participants']), 
            json.dumps(new_data['cancellations']), new_data.get('profit'), 
            new_data['name'], new_data['datetime'], new_data['slots'],
            interaction.message.id
        ))
        await self.bot.db.commit()

        # Reconstrói Embed
        cog = self.bot.get_cog("FactionActions")
        embed = cog._build_embed(interaction.guild, new_data)
        
        # Busca emojis atualizados
        emojis = await cog._get_emojis(interaction.guild.id)
        
        # Cria nova view com emojis corretos
        new_view = ActionView(self.bot, new_data, emojis)
        
        # Atualiza View (se necessário desabilitar botões)
        if new_data['status'] in ['WIN', 'LOSS']:
            for child in new_view.children:
                if getattr(child, "custom_id", "") != "act_mvp":
                    child.disabled = True


        await interaction.message.edit(embed=embed, view=new_view)

    async def _get_current_data(self, interaction):
        # Busca dados atualizados do DB
        async with self.bot.db.execute("SELECT * FROM faction_actions WHERE message_id = ?", (interaction.message.id,)) as cursor:
            row = await cursor.fetchone()
        
        if not row: return None
        
        cols = [d[0] for d in cursor.description]
        data = dict(zip(cols, row))
        
        data['participants'] = json.loads(data['participants'])
        data['cancellations'] = json.loads(data['cancellations'])
        
        # Renomeia chaves para compatibilidade
        data['name'] = data['action_name']
        data['datetime'] = data['date_time']
        data['responsible'] = data['responsible_id']
        
        return data

    @ui.button(label="Participar", style=discord.ButtonStyle.secondary, emoji="🔫", custom_id="act_join")
    async def join_action(self, interaction: discord.Interaction, button: ui.Button):
        data = await self._get_current_data(interaction)
        if not data: return await interaction.response.send_message("❌ Ação não encontrada.", ephemeral=True)

        if data['status'] in ['WIN', 'LOSS']:
            return await interaction.response.send_message("❌ Esta ação já foi finalizada.", ephemeral=True)

        if interaction.user.id in data['participants']:
            return await interaction.response.send_message("⚠️ Você já está participando!", ephemeral=True)

        if len(data['participants']) >= data['slots']:
            return await interaction.response.send_message("❌ Ação lotada!", ephemeral=True)

        data['participants'].append(interaction.user.id)
        
        if len(data['participants']) >= data['slots']:
            data['status'] = 'FULL'
        
        await self._update_message(interaction, data)
        await interaction.response.send_message("✅ Você entrou na ação!", ephemeral=True)

    @ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, emoji="✖️", custom_id="act_leave")
    async def leave_action(self, interaction: discord.Interaction, button: ui.Button):
        data = await self._get_current_data(interaction)
        if interaction.user.id not in data['participants']:
            return await interaction.response.send_message("⚠️ Você não está nessa ação.", ephemeral=True)

        await interaction.response.send_modal(CancelModal(self.bot, self, data))

    @ui.button(label="Vitória", style=discord.ButtonStyle.secondary, emoji="🏆", custom_id="act_win")
    async def win_action(self, interaction: discord.Interaction, button: ui.Button):
        data = await self._get_current_data(interaction)
        if interaction.user.id != data['responsible']: return await interaction.response.send_message("❌ Apenas o responsável.", ephemeral=True)
        
        await interaction.response.send_modal(ProfitModal(self.bot, self, data))

    @ui.button(label="Derrota", style=discord.ButtonStyle.secondary, emoji="💀", custom_id="act_loss")
    async def loss_action(self, interaction: discord.Interaction, button: ui.Button):
        data = await self._get_current_data(interaction)
        if interaction.user.id != data['responsible']: return await interaction.response.send_message("❌ Apenas o responsável.", ephemeral=True)

        data['status'] = 'LOSS'
        await self._update_message(interaction, data)
        await self._log_result(interaction, data) # Loga o resultado
        await interaction.response.send_message("✅ Resultado registrado: Derrota.", ephemeral=True)

    @ui.button(label="Votação MVP", style=discord.ButtonStyle.primary, emoji="⭐", custom_id="act_mvp", row=2)
    async def mvp_action(self, interaction: discord.Interaction, button: ui.Button):
        data = await self._get_current_data(interaction)
        
        if not data: return await interaction.response.send_message("❌ Ação não encontrada.", ephemeral=True)

        if data['status'] not in ['WIN', 'LOSS']:
            return await interaction.response.send_message("❌ A ação precisa ser finalizada antes.", ephemeral=True)
            
        if data.get('mvp_id'):
            return await interaction.response.send_message("❌ O MVP já foi definido.", ephemeral=True)
            
        # Verifica se usuário é participante ou responsável
        if interaction.user.id not in data['participants'] and interaction.user.id != data['responsible']:
            return await interaction.response.send_message("❌ Apenas participantes podem votar.", ephemeral=True)

        view = MVPVotingView(self.bot, data, interaction.message)
        await interaction.response.send_message("⭐ **Votação de MVP Iniciada!**\nSelecione abaixo quem foi o destaque da ação.", view=view, ephemeral=True)

    # === NOVOS BOTÕES ===
    @ui.button(label="Notificar", style=discord.ButtonStyle.secondary, emoji="🔔", custom_id="act_notify", row=1)
    async def notify_participants(self, interaction: discord.Interaction, button: ui.Button):
        data = await self._get_current_data(interaction)
        if interaction.user.id != data['responsible']: return await interaction.response.send_message("❌ Apenas o responsável.", ephemeral=True)
        
        if not data['participants']:
            return await interaction.response.send_message("⚠️ Ninguém para notificar.", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        count = 0
        for uid in data['participants']:
            try:
                user = await interaction.guild.fetch_member(uid)
                embed = discord.Embed(title="🔔 Lembrete de Ação", description=f"A ação **{data['name']}** vai começar em breve!\n\n📅 {data['datetime']}", color=COLOR_OPEN)
                embed.add_field(name="Link", value=f"[Ir para Ação]({interaction.message.jump_url})")
                embed.set_image(url=INVISIBLE_WIDE_URL)
                embed.set_thumbnail(url=self.bot.user.display_avatar.url)
                await user.send(embed=embed)
                count += 1
            except: pass
            
        await interaction.followup.send(f"✅ Notificação enviada para {count} membros na DM.", ephemeral=True)

    @ui.button(label="Editar", style=discord.ButtonStyle.secondary, emoji="✏️", custom_id="act_edit", row=1)
    async def edit_action(self, interaction: discord.Interaction, button: ui.Button):
        data = await self._get_current_data(interaction)
        if interaction.user.id != data['responsible']: return await interaction.response.send_message("❌ Apenas o responsável.", ephemeral=True)
        
        await interaction.response.send_modal(EditActionModal(self.bot, self, data))

    # Helper para Log
    async def _log_result(self, interaction, data):
        async with self.bot.db.execute("SELECT action_logs_channel_id FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            res = await cursor.fetchone()
            
        if res and res[0]:
            log_chan = interaction.guild.get_channel(res[0])
            if log_chan:
                color = COLOR_WIN if data['status'] == 'WIN' else COLOR_LOSS
                embed = discord.Embed(title=f"Relatório de Ação: {data['name']}", color=color)
                embed.add_field(name="Resultado", value="🏆 VITÓRIA" if data['status'] == 'WIN' else "💀 DERROTA", inline=True)
                embed.add_field(name="Responsável", value=f"<@{data['responsible']}>", inline=True)
                
                # Lista de Participantes
                participants_list = [f"<@{uid}>" for uid in data['participants']]
                participants_str = ", ".join(participants_list) if participants_list else "Nenhum"
                embed.add_field(name="Participantes", value=participants_str, inline=False)

                if data.get('profit'):
                    embed.add_field(name="Lucro", value=f"```\n{data['profit']}\n```", inline=False)
                if data.get('mvp_id'):
                    embed.add_field(name="⭐ MVP", value=f"<@{data['mvp_id']}>", inline=False)
                
                embed.set_thumbnail(url=self.bot.user.display_avatar.url)
                embed.timestamp = datetime.datetime.now()
                await log_chan.send(embed=embed)

class MVPVotingView(ui.View):
    def __init__(self, bot, data, message):
        super().__init__(timeout=300)
        self.bot = bot
        self.data = data
        self.message = message
        
        # Cria opções do Select
        options = []
        for uid in data['participants']:
            user = message.guild.get_member(uid)
            name = user.display_name if user else f"ID: {uid}"
            options.append(discord.SelectOption(label=name, value=str(uid), emoji="👤"))
            
        if not options:
            options.append(discord.SelectOption(label="Nenhum participante", value="0"))
            
        self.select = ui.Select(placeholder="Escolha o MVP...", options=options[:25])
        self.select.callback = self.vote_callback
        self.add_item(self.select)

    async def vote_callback(self, interaction: discord.Interaction):
        target_id = int(self.select.values[0])
        if target_id == 0: return await interaction.response.send_message("❌ Opção inválida.", ephemeral=True)
        
        # Registra Voto
        try:
            await self.bot.db.execute("INSERT INTO action_mvp_votes (message_id, voter_id, target_id) VALUES (?, ?, ?)", (self.message.id, interaction.user.id, target_id))
            await self.bot.db.commit()
            await interaction.response.send_message(f"✅ Voto registrado em <@{target_id}>!", ephemeral=True)
        except:
            # Se já votou, atualiza
            await self.bot.db.execute("UPDATE action_mvp_votes SET target_id = ? WHERE message_id = ? AND voter_id = ?", (target_id, self.message.id, interaction.user.id))
            await self.bot.db.commit()
            await interaction.response.send_message(f"✅ Voto atualizado para <@{target_id}>!", ephemeral=True)

    @ui.button(label="Encerrar Votação (Responsável)", style=discord.ButtonStyle.danger, row=1)
    async def close_voting(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.data['responsible']:
            return await interaction.response.send_message("❌ Apenas o responsável pode encerrar.", ephemeral=True)
            
        # Contabiliza Votos
        async with self.bot.db.execute("SELECT target_id, COUNT(*) as votes FROM action_mvp_votes WHERE message_id = ? GROUP BY target_id ORDER BY votes DESC LIMIT 1", (self.message.id,)) as cursor:
            res = await cursor.fetchone()
            
        if not res:
            return await interaction.response.send_message("⚠️ Nenhum voto registrado.", ephemeral=True)
            
        mvp_id = res[0]
        votes = res[1]
        
        # Atualiza Ação com MVP
        await self.bot.db.execute("UPDATE faction_actions SET mvp_id = ? WHERE message_id = ?", (mvp_id, self.message.id))
        await self.bot.db.commit()
        
        # Atualiza Embed da Ação
        self.data['mvp_id'] = mvp_id
        cog = self.bot.get_cog("FactionActions")
        embed = cog._build_embed(interaction.guild, self.data)
        await self.message.edit(embed=embed)
        
        # Loga novamente com MVP
        view = ui.View.from_message(self.message) # Tenta pegar a view original
        if isinstance(view, ActionView):
             await view._log_result(interaction, self.data)
        else:
             # Fallback se não conseguir recuperar a view
             pass

        await interaction.response.edit_message(content=f"🏆 **MVP Definido:** <@{mvp_id}> com {votes} votos!", view=None, embed=None)

class CancelModal(ui.Modal, title="Cancelar Participação"):
    reason = ui.TextInput(label="Motivo do cancelamento", style=discord.TextStyle.short, placeholder="Ex: Tive que sair...")

    def __init__(self, bot, view, data):
        super().__init__()
        self.bot = bot; self.view = view; self.data = data

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.user.id in self.data['participants']:
            self.data['participants'].remove(interaction.user.id)
        
        self.data['cancellations'].append({"user_id": interaction.user.id, "reason": self.reason.value})

        if self.data['status'] == 'FULL': self.data['status'] = 'OPEN'

        await self.view._update_message(interaction, self.data)
        await interaction.response.send_message("✅ Participação cancelada.", ephemeral=True)

class ProfitModal(ui.Modal, title="Registrar Vitória"):
    profit = ui.TextInput(label="Lucro da Ação", style=discord.TextStyle.paragraph, placeholder="Ex: 1x Glock, 50k dinheiro sujo...")

    def __init__(self, bot, view, data):
        super().__init__()
        self.bot = bot; self.view = view; self.data = data

    async def on_submit(self, interaction: discord.Interaction):
        self.data['status'] = 'WIN'
        self.data['profit'] = self.profit.value
        
        await self.view._update_message(interaction, self.data)
        await self.view._log_result(interaction, self.data) # Loga o resultado
        await interaction.response.send_message("✅ Vitória registrada com lucro!", ephemeral=True)

class EditActionModal(ui.Modal, title="Editar Ação"):
    def __init__(self, bot, view, data):
        super().__init__()
        self.bot = bot; self.view = view; self.data = data
        
        self.m_name = ui.TextInput(label="Nome da Ação", default=data['name'], style=discord.TextStyle.short)
        self.m_date = ui.TextInput(label="Data/Hora", default=data['datetime'], style=discord.TextStyle.short)
        self.m_slots = ui.TextInput(label="Vagas", default=str(data['slots']), style=discord.TextStyle.short)
        
        self.add_item(self.m_name)
        self.add_item(self.m_date)
        self.add_item(self.m_slots)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_slots = int(self.m_slots.value)
        except:
            return await interaction.response.send_message("❌ Vagas deve ser um número.", ephemeral=True)
            
        self.data['name'] = self.m_name.value
        self.data['datetime'] = self.m_date.value
        self.data['slots'] = new_slots
        
        # Recalcula status se necessário
        if len(self.data['participants']) >= new_slots:
            if self.data['status'] == 'OPEN': self.data['status'] = 'FULL'
        else:
            if self.data['status'] == 'FULL': self.data['status'] = 'OPEN'
            
        await self.view._update_message(interaction, self.data)
        await interaction.response.send_message("✅ Ação editada.", ephemeral=True)

class ActionConfigView(ui.View):
    def __init__(self, bot, cog):
        super().__init__(timeout=120)
        self.bot = bot
        self.cog = cog

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Definir Canal de Ações", channel_types=[discord.ChannelType.text], row=0)
    async def sel_channel(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await self.bot.db.execute("UPDATE config SET action_channel_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message("✅ Canal de Ações atualizado!", ephemeral=True)
        await self.cog.send_config_panel(interaction, is_edit=True)

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Definir Canal de Logs", channel_types=[discord.ChannelType.text], row=1)
    async def sel_logs(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await self.bot.db.execute("UPDATE config SET action_logs_channel_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message("✅ Canal de Logs atualizado!", ephemeral=True)
        await self.cog.send_config_panel(interaction, is_edit=True)

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Definir Canal de Ranking Automático", channel_types=[discord.ChannelType.text], row=2)
    async def sel_ranking(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await self.bot.db.execute("UPDATE config SET action_ranking_channel_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message("✅ Canal de Ranking atualizado!", ephemeral=True)
        await self.cog.send_config_panel(interaction, is_edit=True)

    @ui.select(cls=discord.ui.RoleSelect, placeholder="Definir Cargo de Menção", row=3)
    async def sel_role(self, interaction: discord.Interaction, select: ui.RoleSelect):
        await self.bot.db.execute("UPDATE config SET action_role_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message("✅ Cargo de Menção atualizado!", ephemeral=True)
        await self.cog.send_config_panel(interaction, is_edit=True)

    @ui.button(label="Configurar Emojis", style=discord.ButtonStyle.primary, emoji="🎨", row=4)
    async def config_emojis(self, interaction: discord.Interaction, button: ui.Button):
        # Fetch current emojis
        async with self.bot.db.execute("SELECT action_emoji_join, action_emoji_leave, action_emoji_win, action_emoji_loss, action_emoji_notify, action_emoji_edit FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()
        
        emojis = row if row else (None, None, None, None, None, None)
        await interaction.response.send_modal(ActionEmojiModal(self.bot, self.cog, interaction, emojis))

    @ui.button(label="Emoji Editar", style=discord.ButtonStyle.secondary, emoji="✏️", row=4)
    async def config_edit_emoji(self, interaction: discord.Interaction, button: ui.Button):
        async with self.bot.db.execute("SELECT action_emoji_edit FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            res = await cursor.fetchone()
    @ui.button(label="Configurar Webhook", style=discord.ButtonStyle.secondary, emoji="🔗", row=4)
    async def config_webhook(self, interaction: discord.Interaction, button: ui.Button):
        async with self.bot.db.execute("SELECT action_ranking_webhook FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            res = await cursor.fetchone()
        current = res[0] if res else ""
        await interaction.response.send_modal(WebhookConfigModal(self.bot, self.cog, interaction, current))

class WebhookConfigModal(ui.Modal, title="🔗 Configurar Backup Webhook"):
    def __init__(self, bot, cog, origin, current):
        super().__init__()
        self.bot = bot; self.cog = cog; self.origin = origin
        self.webhook_url = ui.TextInput(label="URL do Webhook", default=current, required=False, placeholder="https://discord.com/api/webhooks/...")
        self.add_item(self.webhook_url)

    async def on_submit(self, interaction: discord.Interaction):
        url = self.webhook_url.value.strip()
        if url and not url.startswith("http"):
            return await interaction.response.send_message("❌ URL inválida.", ephemeral=True)
            
        await self.bot.db.execute("UPDATE config SET action_ranking_webhook = ? WHERE guild_id = ?", (url, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message("✅ Webhook de backup atualizado!", ephemeral=True)
        await self.cog.send_config_panel(self.origin, is_edit=True)

class ActionEmojiModal(ui.Modal, title="🎨 Configurar Emojis"):
    def __init__(self, bot, cog, origin, current_emojis):
        super().__init__()
        self.bot = bot
        self.cog = cog
        self.origin = origin
        
        self.e_join = ui.TextInput(label="Participar", default=current_emojis[0] or "🔫", required=True)
        self.e_leave = ui.TextInput(label="Cancelar", default=current_emojis[1] or "✖️", required=True)
        self.e_win = ui.TextInput(label="Vitória", default=current_emojis[2] or "🏆", required=True)
        self.e_loss = ui.TextInput(label="Derrota", default=current_emojis[3] or "💀", required=True)
        self.e_notify = ui.TextInput(label="Notificar", default=current_emojis[4] or "🔔", required=True)
        
        self.add_item(self.e_join)
        self.add_item(self.e_leave)
        self.add_item(self.e_win)
        self.add_item(self.e_loss)
        self.add_item(self.e_notify)
        
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.execute("""
            UPDATE config SET 
            action_emoji_join=?, action_emoji_leave=?, action_emoji_win=?, action_emoji_loss=?, action_emoji_notify=?
            WHERE guild_id=?
        """, (self.e_join.value, self.e_leave.value, self.e_win.value, self.e_loss.value, self.e_notify.value, interaction.guild.id))
        await self.bot.db.commit()
        
        await interaction.followup.send("✅ Emojis principais atualizados!", ephemeral=True)
        await self.cog.send_config_panel(self.origin, is_edit=True)

class ActionEditEmojiModal(ui.Modal, title="🎨 Emoji de Edição"):
    def __init__(self, bot, cog, origin, current):
        super().__init__()
        self.bot = bot; self.cog = cog; self.origin = origin
        self.e_edit = ui.TextInput(label="Editar", default=current, required=True)
        self.add_item(self.e_edit)
    
    async def on_submit(self, interaction: discord.Interaction):
        await self.bot.db.execute("UPDATE config SET action_emoji_edit=? WHERE guild_id=?", (self.e_edit.value, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message("✅ Emoji de edição atualizado!", ephemeral=True)
        await self.cog.send_config_panel(self.origin, is_edit=True)

class ResetRankingConfirmView(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot

    @ui.button(label="SIM, ZERAR TUDO", style=discord.ButtonStyle.danger, emoji="💣")
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        
        # Deleta dados do servidor
        await self.bot.db.execute("DELETE FROM faction_actions WHERE guild_id = ?", (interaction.guild.id,))
        await self.bot.db.execute("DELETE FROM action_mvp_votes WHERE guild_id = ?", (interaction.guild.id,))
        await self.bot.db.commit()
        
        await interaction.edit_original_response(content="✅ **Ranking resetado com sucesso!** Todo o histórico foi apagado.", embed=None, view=None)

    @ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.edit_original_response(content="❌ Operação cancelada.", embed=None, view=None)

async def setup(bot):
    await bot.add_cog(FactionActions(bot))
