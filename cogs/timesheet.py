import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
import datetime
import asyncio

# ====================================================
# 🎨 CONSTANTES & UTILS
# ====================================================
# ====================================================
# 🎨 CONSTANTES & UTILS
# ====================================================
COLOR_ON_DUTY = 0x2ecc71      # Verde (Em Serviço)
COLOR_PAUSED = 0xf1c40f       # Amarelo (Pausa)
COLOR_OFF_DUTY = 0xe74c3c     # Vermelho (Fora de Serviço)
INVISIBLE_WIDE_URL = "https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png"
SEPARATOR = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

class Timesheet(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.management_update_loop.start()

    def cog_unload(self):
        self.management_update_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        # Registra a View de Dropdown para persistência
        self.bot.add_view(OperatorView(self.bot, None))
        print("✅ [Timesheet] Views persistentes carregadas.")

    # ====================================================
    # ⚙️ CONFIGURAÇÃO (PAINEL ADMIN)
    # ====================================================
    @app_commands.command(name="painel_ponto_config", description="⚙️ Configura os canais e cargos do Ponto Eletrônico.")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        async with self.bot.db.execute("SELECT ts_channel_operator, ts_channel_management, ts_channel_history, ts_role_id FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()
        
        cfg = row if row else (None, None, None, None)
        
        embed = discord.Embed(title="⚙️ Configuração do Ponto", color=0x2b2d31)
        embed.description = (
            "Selecione os canais correspondentes para cada função do sistema.\n\n"
            f"🟢 **Canal do Operador (/ponto):** {f'<#{cfg[0]}>' if cfg[0] else '🔴 Não definido'}\n"
            f"📊 **Painel de Gerência:** {f'<#{cfg[1]}>' if cfg[1] else '🔴 Não definido'}\n"
            f"📜 **Histórico (Logs):** {f'<#{cfg[2]}>' if cfg[2] else '🔴 Não definido'}\n"
            f"🛡️ **Cargo em Serviço:** {f'<@&{cfg[3]}>' if cfg[3] else '🔴 Não definido'}"
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        view = TimesheetConfigView(self.bot, interaction.user)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # ====================================================
    # 🟢 DEPARTAMENTO 1: OPERADOR (/ponto)
    # ====================================================
    @app_commands.command(name="ponto", description="📱 Abre seu cartão de ponto (Exclusivo no canal configurado).")
    async def open_timesheet(self, interaction: discord.Interaction):
        # 1. Verifica Canal Permitido
        async with self.bot.db.execute("SELECT ts_channel_operator FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()
            
        if not row or not row[0]:
            return await interaction.response.send_message("❌ Sistema não configurado. Peça a um admin.", ephemeral=True)
            
        if interaction.channel.id != row[0]:
            return await interaction.response.send_message(f"🚫 Use este comando apenas em <#{row[0]}>.", ephemeral=True)

        # 2. Verifica se já existe sessão aberta
        async with self.bot.db.execute("SELECT start_time, status, total_seconds FROM time_sessions WHERE user_id = ? AND guild_id = ? AND status != 'CLOSED' ORDER BY id DESC LIMIT 1", (interaction.user.id, interaction.guild.id)) as cursor:
            session = await cursor.fetchone()

        # 3. Cria Embed Inicial (Design Senior)
        embed = discord.Embed(title="PONTO ELETRÔNICO", color=COLOR_OFF_DUTY)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_image(url=INVISIBLE_WIDE_URL)
        embed.set_footer(text=f"Colaborador: {interaction.user.display_name}")
        
        status_txt = "🔴 **FORA DE SERVIÇO**"
        
        if session:
            start_str, status, total_prev = session
            ts_start = int(datetime.datetime.fromisoformat(start_str).timestamp())
            
            if status == 'OPEN':
                embed.color = COLOR_ON_DUTY
                embed.description = f"**EM SERVIÇO**\n{SEPARATOR}\n**Entrada:** <t:{ts_start}:t>\n**Tempo Decorrido:** <t:{ts_start}:R>\n{SEPARATOR}"
                status_txt = "EM SERVIÇO"
            else:
                embed.color = COLOR_PAUSED
                embed.description = f"**EM PAUSA**\n{SEPARATOR}\n**Desde:** <t:{ts_start}:R>\n**Status:** Aguardando retorno.\n{SEPARATOR}"
                status_txt = "EM PAUSA"
        else:
            embed.description = f"**FORA DE SERVIÇO**\n{SEPARATOR}\nUtilize o menu abaixo para iniciar seu turno.\n{SEPARATOR}"
            embed.color = COLOR_OFF_DUTY
            
        view = OperatorView(self.bot, interaction.user)
        # Envia como resposta efêmera (se não for thread, mas user pediu publico)
        # User pediu: "A embed também nao fica visivel so pra ele, fica como uma mensagem mesmo."
        await interaction.response.send_message(embed=embed, view=view)


    # ====================================================
    # 🏢 DEPARTAMENTO 2: GERÊNCIA (DASHBOARD)
    # ====================================================
    @tasks.loop(minutes=2)
    async def management_update_loop(self):
        for guild in self.bot.guilds:
            try:
                await self.update_management_panel(guild)
            except Exception as e:
                print(f"Erro no loop de gerência para {guild.name}: {e}")

    @app_commands.command(name="ponto_admin_force_panel", description="🛠️ Força a atualização do Painel de Gerência (Torre de Controle).")
    @app_commands.checks.has_permissions(administrator=True)
    async def force_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.update_management_panel(interaction.guild)
        await interaction.followup.send("✅ Painel de Gerência atualizado com sucesso!", ephemeral=True)

    async def update_management_panel(self, guild):
        """Atualiza a mensagem fixa no canal de gerência."""
        # 1. Busca Configuração
        async with self.bot.db.execute("SELECT ts_channel_management FROM config WHERE guild_id = ?", (guild.id,)) as cursor:
            row = await cursor.fetchone()
        
        if not row or not row[0]: return # Não configurado

        channel = guild.get_channel(row[0])
        if not channel: return

        # 2. Busca Sessões Abertas (Join com Users se possível, ou fetch manual)
        async with self.bot.db.execute("SELECT user_id, start_time, status FROM time_sessions WHERE guild_id = ? AND status != 'CLOSED' ORDER BY start_time DESC", (guild.id,)) as cursor:
            sessions = await cursor.fetchall()

        # 3. Monta Texto
        embed = discord.Embed(title="PAINEL DE GESTÃO", color=0xffffff)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_image(url=INVISIBLE_WIDE_URL)
        embed.set_footer(text=f"Atualizado às {datetime.datetime.now().strftime('%H:%M')}")

        if not sessions:
            desc = f"**Nenhum operador em serviço.**\n{SEPARATOR}"
        else:
            lines = []
            for uid, start_str, status in sessions:
                member = guild.get_member(uid)
                if not member: continue
                
                dt = datetime.datetime.fromisoformat(start_str)
                ts = int(dt.timestamp())
                
                # Visual Limpo (Sem Emojis)
                status_slug = "EM SERVIÇO" if status == 'OPEN' else "EM PAUSA"
                lines.append(f"{member.mention}\n▸ {status_slug} • <t:{ts}:R>")
            
            desc = f"{SEPARATOR}\n" + "\n\n".join(lines) + f"\n{SEPARATOR}"
        
        embed.description = desc
        
        # Estratégia: Busca última msg do bot no canal. Se for embed de Gerência, edita. Senão cria.
        target_msg = None
        async for msg in channel.history(limit=10):
            if msg.author == self.bot.user and msg.embeds and (msg.embeds[0].title == "🔭 Torre de Controle" or msg.embeds[0].title == "TORRE DE CONTROLE"):
                target_msg = msg
                break
        
        if target_msg:
            await target_msg.edit(embed=embed)
        else:
            await channel.send(embed=embed)


# ====================================================
# 🖥️ VIEWS
# ====================================================

class OperatorView(ui.View):
    def __init__(self, bot, user):
        super().__init__(timeout=None)
        self.bot = bot
        self.user = user

    @ui.select(placeholder="Selecione uma ação...", min_values=1, max_values=1, custom_id="timesheet_actions", options=[
        discord.SelectOption(label="Iniciar Serviço", value="START", description="Começar a contar as horas"),
        discord.SelectOption(label="Pausar", value="PAUSE", description="Pausa para almoço/descanso"),
        discord.SelectOption(label="Retomar", value="RESUME", description="Voltar da pausa"),
        discord.SelectOption(label="Encerrar Plantão", value="END", description="Finalizar e gerar relatório")
    ])
    async def callback(self, interaction: discord.Interaction, select: ui.Select):
        action = select.values[0]
        guild_id = interaction.guild.id
        user_id = interaction.user.id
        now = datetime.datetime.now()
        
        # Busca sessão atual
        async with self.bot.db.execute("SELECT id, start_time, status, total_seconds FROM time_sessions WHERE user_id = ? AND guild_id = ? AND status != 'CLOSED' ORDER BY id DESC LIMIT 1", (user_id, guild_id)) as cursor:
            session = await cursor.fetchone()

        # Busca Role Config
        async with self.bot.db.execute("SELECT ts_role_id, ts_channel_history FROM config WHERE guild_id = ?", (guild_id,)) as cursor:
            cfg = await cursor.fetchone()
        role_id = cfg[0] if cfg else None
        log_channel_id = cfg[1] if cfg else None

        role = interaction.guild.get_role(role_id) if role_id else None

        # LÓGICA DE TRANSIÇÃO
        msg_resp = ""
        new_status = ""
        
        if action == "START":
            if session:
                return await interaction.response.send_message("⚠️ Você já tem uma sessão aberta!", ephemeral=True)
            
            await self.bot.db.execute("INSERT INTO time_sessions (guild_id, user_id, start_time, status) VALUES (?, ?, ?, 'OPEN')", (guild_id, user_id, str(now)))
            
            # Pega ID da sessão criada
            async with self.bot.db.execute("SELECT id FROM time_sessions WHERE user_id = ? AND guild_id = ? ORDER BY id DESC LIMIT 1", (user_id, guild_id)) as cursor:
                 new_session = await cursor.fetchone()
            session_id = new_session[0]

            # Log Detalhado
            await self.bot.db.execute("INSERT INTO timesheet_logs (guild_id, user_id, action, timestamp, session_id, details) VALUES (?, ?, 'START', ?, ?, 'Início de Turno')", (guild_id, user_id, now, session_id))

            if role: await interaction.user.add_roles(role, reason="Ponto Iniciado")
            msg_resp = "Plantão Iniciado!"
            new_status = "OPEN"
            
        elif action == "PAUSE":
            if not session: return await interaction.response.send_message("Nenhuma sessão aberta.", ephemeral=True)
            if session[2] == 'PAUSED': return await interaction.response.send_message("Já está pausado.", ephemeral=True)
            
            await self.bot.db.execute("UPDATE time_sessions SET status = 'PAUSED' WHERE id = ?", (session[0],))
            # Log Detalhado
            await self.bot.db.execute("INSERT INTO timesheet_logs (guild_id, user_id, action, timestamp, session_id, details) VALUES (?, ?, 'PAUSE', ?, ?, 'Pausa Iniciada')", (guild_id, user_id, now, session[0]))
            
            msg_resp = "Plantão Pausado."
            new_status = "PAUSED"
            
        elif action == "RESUME":
            if not session: return await interaction.response.send_message("Nenhuma sessão aberta.", ephemeral=True)
            if session[2] == 'OPEN': return await interaction.response.send_message("Já está em andamento.", ephemeral=True)
            
            await self.bot.db.execute("UPDATE time_sessions SET status = 'OPEN' WHERE id = ?", (session[0],))
            # Log Detalhado
            await self.bot.db.execute("INSERT INTO timesheet_logs (guild_id, user_id, action, timestamp, session_id, details) VALUES (?, ?, 'RESUME', ?, ?, 'Retorno de Pausa')", (guild_id, user_id, now, session[0]))
            
            msg_resp = "Plantão Retomado."
            new_status = "OPEN"
            
        elif action == "END":
            if not session: return await interaction.response.send_message("Nenhuma sessão aberta.", ephemeral=True)
            
            # Calcula Total
            start_dt = datetime.datetime.fromisoformat(session[1])
            duration = (now - start_dt).total_seconds()
            
            await self.bot.db.execute("UPDATE time_sessions SET status = 'CLOSED', end_time = ?, total_seconds = ? WHERE id = ?", (str(now), int(duration), session[0]))
            
            # Log Detalhado Final
            await self.bot.db.execute("INSERT INTO timesheet_logs (guild_id, user_id, action, timestamp, session_id, details) VALUES (?, ?, 'END', ?, ?, 'Fim de Turno')", (guild_id, user_id, now, session[0]))

            if role: await interaction.user.remove_roles(role, reason="Ponto Encerrado")
            
            h = int(duration // 3600)
            m = int((duration % 3600) // 60)
            msg_resp = f"Plantão Encerrado. Duração: {h}h {m}m"
            new_status = "CLOSED"
            
            # Monta Relatório Detalhado
            if log_channel_id:
                chan = interaction.guild.get_channel(log_channel_id)
                if chan:
                    # Busca histórico de pausas
                    async with self.bot.db.execute("SELECT action, timestamp FROM timesheet_logs WHERE session_id = ? ORDER BY id ASC", (session[0],)) as cursor:
                        logs = await cursor.fetchall()
                    
                    pauses_txt = ""
                    for act, ts in logs:
                        dt_log = datetime.datetime.fromisoformat(str(ts))
                        if act == 'PAUSE': pauses_txt += f"**Pausa:** {dt_log.strftime('%H:%M')}\n"
                        elif act == 'RESUME': pauses_txt += f"**Volta:** {dt_log.strftime('%H:%M')}\n"
                    
                    if not pauses_txt: pauses_txt = "*Nenhuma pausa.*"

                    e_log = discord.Embed(title="Registro de Ponto Completo", color=0x95a5a6)
                    e_log.description = f"**Colaborador:** {interaction.user.mention}\n{SEPARATOR}\n"
                    e_log.description += f"**Data:** {now.strftime('%d/%m/%Y')}\n"
                    e_log.description += f"**Entrada:** {start_dt.strftime('%H:%M')}\n"
                    e_log.description += f"**Saída:** {now.strftime('%H:%M')}\n"
                    e_log.description += f"**Tempo Total:** {h}h {m}m\n\n"
                    e_log.description += f"**Histórico de Pausas:**\n{pauses_txt}\n{SEPARATOR}"
                    e_log.set_footer(text=f"ID Sessão: {session[0]}")
                    e_log.set_thumbnail(url=interaction.user.display_avatar.url)
                    e_log.set_image(url=INVISIBLE_WIDE_URL)
                    
                    await chan.send(embed=e_log)

        await self.bot.db.commit()
        await interaction.response.send_message(msg_resp, ephemeral=True)
        
        # Atualiza a Embed do Operador (Design Consistent)
        try:
            embed = interaction.message.embeds[0]
            embed.set_image(url=INVISIBLE_WIDE_URL)
            
            if new_status == 'OPEN':
                embed.color = COLOR_ON_DUTY
                # Se foi START, usa now, se foi RESUME, mantém start original (precisaria buscar do banco)
                # Simplificação: Usamos timestamps relativos na visualização
                display_ts = int(datetime.datetime.fromisoformat(session[1]).timestamp()) if session else int(now.timestamp())
                embed.description = f"**EM SERVIÇO**\n{SEPARATOR}\n**Entrada:** <t:{display_ts}:t>\n**Tempo Decorrido:** <t:{display_ts}:R>\n{SEPARATOR}"
                
            elif new_status == 'PAUSED':
                embed.color = COLOR_PAUSED
                embed.description = f"**EM PAUSA**\n{SEPARATOR}\n**Pausa em:** <t:{int(now.timestamp())}:t>\n**Status:** Aguardando retorno.\n{SEPARATOR}"
                
            elif new_status == 'CLOSED':
                embed.color = COLOR_OFF_DUTY
                embed.description = f"**PLANTÃO ENCERRADO**\n{SEPARATOR}\n**Total Trabalhado:** `{h}h {m}m`\n**Saída:** {now.strftime('%d/%m/%Y às %H:%M')}\n{SEPARATOR}"
            
            await interaction.message.edit(embed=embed)
        except Exception as e:
            print(f"Erro ao editar embed: {str(e)}")

        # Atualiza Painel de Gerência
        cog = self.bot.get_cog("Timesheet")
        if cog: await cog.update_management_panel(interaction.guild)


class TimesheetConfigView(ui.View):
    def __init__(self, bot, user):
        super().__init__(timeout=180)
        self.bot = bot
        self.user = user

    async def update_config(self, interaction, column, value):
        await self.bot.db.execute(f"UPDATE config SET {column} = ? WHERE guild_id = ?", (value, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.response.send_message(f"✅ Configuração atualizada!", ephemeral=True)

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Canal do Operador (/ponto)", channel_types=[discord.ChannelType.text])
    async def sel_op(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await self.update_config(interaction, 'ts_channel_operator', select.values[0].id)

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Painel de Gerência", channel_types=[discord.ChannelType.text])
    async def sel_man(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await self.update_config(interaction, 'ts_channel_management', select.values[0].id)

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Canal de Logs/Histórico", channel_types=[discord.ChannelType.text])
    async def sel_log(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await self.update_config(interaction, 'ts_channel_history', select.values[0].id)

    @ui.select(cls=discord.ui.RoleSelect, placeholder="Cargo 'Em Serviço'")
    async def sel_role(self, interaction: discord.Interaction, select: ui.RoleSelect):
        await self.update_config(interaction, 'ts_role_id', select.values[0].id)

async def setup(bot):
    await bot.add_cog(Timesheet(bot))

