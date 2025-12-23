import os
import asyncio
import psutil
from quart import Quart, render_template, redirect, url_for, request, session, jsonify
from discord.ext import commands

import aiohttp
from quart import Quart, render_template, redirect, url_for, request, session, jsonify, abort, Blueprint, send_from_directory

# Inicializa o App Quart
app = Quart(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.getenv("DASHBOARD_SECRET", "troque_isso_por_algo_seguro_123")

# Blueprint do Painel de Dono (Prefix /owner)
owner_bp = Blueprint('owner', __name__, url_prefix='/owner')

# Configurações OAuth2
CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
OWNER_ID = int(os.getenv("OWNER_ID", 0))
API_ENDPOINT = "https://discord.com/api/v10"

# Referência global ao Bot
bot = None

def init_dashboard(bot_instance):
    """Inicializa a conexão entre o Bot e o Painel"""
    global bot
    bot = bot_instance

# =========================================
# 🔐 AUTENTICAÇÃO
# =========================================

@owner_bp.route('/login')
async def login():
    """Redireciona para o Discord Login"""
    scope = "identify guilds"
    url = f"https://discord.com/api/oauth2/authorize?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope={scope}"
    return redirect(url)

@owner_bp.route('/callback')
async def callback():
    """Recebe o código do Discord e troca por Token"""
    try:
        code = request.args.get('code')
        if not code: return "Erro: Nenhum código recebido.", 400

        # Debug
        print(f"DEBUG: Callback Code: {code}")
        print(f"DEBUG: Redirect URI: {REDIRECT_URI}")
        print(f"DEBUG: Client ID: {CLIENT_ID}")

        # Troca Code por Token
        data = {
            'client_id': CLIENT_ID,
            'client_secret': CLIENT_SECRET,
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': REDIRECT_URI
        }
        
        async with aiohttp.ClientSession() as cs:
            print("DEBUG: Enviando POST para token...")
            async with cs.post(f'{API_ENDPOINT}/oauth2/token', data=data) as r:
                print(f"DEBUG: Status Code da troca de token: {r.status}")
                if r.status != 200:
                    text_resp = await r.text()
                    return f"Erro na troca de token (Discord API): {r.status} - {text_resp}", 400
                    
                token_resp = await r.json()
                if 'error' in token_resp: return f"Erro no Login: {token_resp}", 400
                
                access_token = token_resp['access_token']

            # Pega dados do Usuário
            headers = {"Authorization": f"Bearer {access_token}"}
            print("DEBUG: Buscando dados do usuário...")
            async with cs.get(f'{API_ENDPOINT}/users/@me', headers=headers) as r:
                if r.status != 200:
                    return f"Erro ao pegar usuário: {r.status}", 400
                user = await r.json()
                
        # VERIFICAÇÃO DE SEGURANÇA (GOD MODE)
        print(f"DEBUG: User ID: {user.get('id')} vs Owner ID: {OWNER_ID}")
        if int(user['id']) != OWNER_ID:
            return "🚫 ACESSO NEGADO: Apenas o Dono Supremo pode entrar aqui.", 403

        # Salva na Sessão
        session['user'] = user
        return redirect(url_for('owner.index'))
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        print(trace)
        return f"<h1>Erro Interno (500)</h1><pre>{trace}</pre>", 500

@owner_bp.route('/logout')
async def logout():
    session.clear()
    return redirect(url_for('index'))

# =========================================
# 🏠 ROTAS BÁSICAS
# =========================================

@owner_bp.route('/')
async def index():
    """Página Inicial (Login ou Dashboard)"""
    user = session.get('user')
    if not user:
        return await render_template('login.html')
    
    return await render_template('index.html', user=user)

# =========================================
# 📊 API ENDPOINTS (Phase 2)
# =========================================

@owner_bp.route('/api/stats')
async def api_stats():
    """Retorna estatísticas vitais do Bot e da VPS"""
    print(f"DEBUG: api_stats called. Bot: {bot}")
    if not bot: return jsonify({"error": "Bot not ready"}), 503
    print(f"DEBUG: Bot User: {bot.user}")
    
    # VPS Stats
    cpu_usage = psutil.cpu_percent()
    ram = psutil.virtual_memory()
    
    return jsonify({
        "bot": {
            "name": bot.user.name if bot.user else "Unknown",
            "id": bot.user.id if bot.user else None,
            "ping": round(bot.latency * 1000),
            "guilds": len(bot.guilds),
            "users": sum(g.member_count for g in bot.guilds)
        },
        "vps": {
            "cpu": cpu_usage,
            "ram_percent": ram.percent,
            "ram_used_gb": round(ram.used / (1024**3), 2),
            "ram_total_gb": round(ram.total / (1024**3), 2)
        }
    })

# =========================================
# 🔑 LICENSES MANAGEMENT
# =========================================

@owner_bp.route('/licenses')
async def licenses_page():
    user = session.get('user')
    if not user: return redirect(url_for('login'))
    return await render_template('licenses.html', user=user)

@owner_bp.route('/api/debug/db')
async def api_debug_db():
    try:
        if not bot or not bot.db: return jsonify({"error": "Bot not ready"}), 503
        
        # 1. Check path
        import os
        cwd = os.getcwd()
        abs_path = os.path.abspath("database/bot_data.db")
        
        # 2. Check schema seen by connection
        columns = []
        async with bot.db.execute("PRAGMA table_info(licenses)") as cursor:
            rows = await cursor.fetchall()
            columns = [{"cid": r[0], "name": r[1], "type": r[2]} for r in rows]
            
        return jsonify({
             "cwd": cwd,
             "db_path_absolute": abs_path,
             "db_exists": os.path.exists(abs_path),
             "columns_seen_by_bot": columns
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@owner_bp.route('/api/licenses', methods=['GET'])
async def api_licenses_list():
    try:
        if not bot or not bot.db: return jsonify([]), 503
        
        async with bot.db.execute("SELECT guild_id, client_name, expiration_date, status, max_users, tier FROM licenses") as cursor:
            rows = await cursor.fetchall()
            
        data = []
        for row in rows:
            data.append({
                "guild_id": str(row[0]), # Stringify to avoid JS BigInt precision loss
                "client_name": row[1],
                "expiration_date": row[2],
                "status": row[3],
                "max_users": row[4],
                "tier": row[5] or 'start'
            })
        return jsonify(data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@owner_bp.route('/api/licenses/add', methods=['POST'])
async def api_licenses_add():
    data = await request.get_json()
    try:
        guild_id = int(data.get('guild_id'))
        client_name = data.get('client_name')
        days = int(data.get('days', 30))
        tier = data.get('tier', 'start')
        
        # Calcula data de expiração
        from datetime import datetime, timedelta
        exp_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        
        # 1. Verifica se já existe licença para este Guild
        async with bot.db.execute("SELECT key FROM licenses WHERE guild_id = ?", (guild_id,)) as cursor:
            existing = await cursor.fetchone()
            
        if existing:
            # UPDATE
            await bot.db.execute("""
                UPDATE licenses 
                SET client_name = ?, expiration_date = ?, status = 'active', max_users = ?, tier = ?
                WHERE guild_id = ?
            """, (client_name, exp_date, data.get('max_users', 100), tier, guild_id))
        else:
            # INSERT
            import uuid
            new_key = str(uuid.uuid4())
            await bot.db.execute("""
                INSERT INTO licenses (key, guild_id, client_name, expiration_date, status, max_users, tier)
                VALUES (?, ?, ?, ?, 'active', ?, ?)
            """, (new_key, guild_id, client_name, exp_date, data.get('max_users', 100), tier))
            
        await bot.db.commit()
        return jsonify({"success": True})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@owner_bp.route('/api/licenses/delete', methods=['POST'])
async def api_licenses_delete():
    data = await request.get_json()
    guild_id = data.get('guild_id')
    
    await bot.db.execute("DELETE FROM licenses WHERE guild_id = ?", (guild_id,))
    await bot.db.commit()
    return jsonify({"success": True})

@owner_bp.route('/api/licenses/renew', methods=['POST'])
async def api_licenses_renew():
    data = await request.get_json()
    guild_id = data.get('guild_id')
    
    # Adiciona 30 dias à data atual (ou à data de expiração atual se ainda for válida - TODO)
    from datetime import datetime, timedelta
    new_exp = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    
    await bot.db.execute("UPDATE licenses SET expiration_date = ?, status = 'active' WHERE guild_id = ?", (new_exp, guild_id))
    await bot.db.commit()
    return jsonify({"success": True})

# =========================================
# 🖥️ SERVERS & DATA MANAGEMENT
# =========================================

@owner_bp.route('/servers')
async def servers_page():
    user = session.get('user')
    if not user: return redirect(url_for('login'))
    return await render_template('servers.html', user=user)

@owner_bp.route('/api/servers', methods=['GET'])
async def api_servers_list():
    try:
        if not bot: return jsonify({"error": "Bot not ready"}), 503

        # 1. Servidores Ativos
        active_guilds = []
        print(f"DEBUG: api_servers_list called. Guilds count: {len(bot.guilds)}")
        for g in bot.guilds:
            print(f"DEBUG: Processing guild {g.name} ({g.id})")
            active_guilds.append({
                "id": str(g.id),
                "name": g.name,
                "icon": g.icon.url if g.icon else None,
                "member_count": g.member_count,
                "owner_id": str(g.owner_id)
            })

        # 2. Fila de Limpeza (Audit Logs)
        # Pega logs de BOT_REMOVED e verifica se o bot NÃO está mais lá
        cleaning_queue = []
        if bot.db:
            async with bot.db.execute("SELECT target, timestamp FROM audit_logs WHERE action = 'BOT_REMOVED' ORDER BY timestamp DESC") as cursor:
                rows = await cursor.fetchall()
                
            for row in rows:
                g_id = int(row[0])
                # Só adiciona se o bot realmente não estiver mais no servidor (evita falso positivo se foi re-adicionado)
                if not bot.get_guild(g_id):
                    cleaning_queue.append({
                        "target_id": str(g_id),
                        "timestamp": row[1]
                    })

        return jsonify({
            "active": active_guilds,
            "cleaning_queue": cleaning_queue
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@owner_bp.route('/api/servers/leave', methods=['POST'])
async def api_servers_leave():
    data = await request.get_json()
    guild_id = int(data.get('guild_id'))
    
    guild = bot.get_guild(guild_id)
    if guild:
        await guild.leave()
        return jsonify({"success": True, "message": f"Saiu de {guild.name}"})
    return jsonify({"error": "Guild not found"}), 404

@owner_bp.route('/api/servers/purge', methods=['POST'])
async def api_servers_purge():
    data = await request.get_json()
    guild_id = data.get('guild_id')
    
    if not bot.db: return jsonify({"error": "DB Error"}), 500

    # LISTA DE TABELAS PARA LIMPAR
    # Adicione aqui todas as tabelas que têm guild_id
    tables = [
        "config", "licenses", "active_tickets", "faction_actions", 
        "ticket_panels" # Adicionar outras se existirem
    ]
    
    deleted_count = 0
    try:
        for table in tables:
            # Verifica se tabela existe antes de tentar deletar (segurança)
            # Simplificação: assume que existem. Em prod, verificar sqlite_master.
            try:
                await bot.db.execute(f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,))
            except: pass # Ignora erro se tabela não tiver guild_id ou não existir
            
        # Remove também da Audit Log para sair da fila
        await bot.db.execute("DELETE FROM audit_logs WHERE target_id = ? AND action = 'BOT_REMOVED'", (guild_id,))
        
        await bot.db.commit()
        return jsonify({"success": True, "message": "Dados limpos com sucesso!"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =========================================
# 🛡️ GLOBAL BLACKLIST (GOD MODE)
# =========================================

@owner_bp.route('/bans')
async def bans_page():
    user = session.get('user')
    if not user: return redirect(url_for('owner.login'))
    return await render_template('blacklist.html', user=user)

@owner_bp.route('/api/bans', methods=['GET'])
async def api_bans_list():
    try:
        if not bot or not bot.db: return jsonify([]), 503
        
        async with bot.db.execute("SELECT user_id, reason, proof_url, timestamp FROM global_bans ORDER BY timestamp DESC") as cursor:
            rows = await cursor.fetchall()
            
        data = []
        for row in rows:
            data.append({
                "user_id": str(row[0]),
                "reason": row[1],
                "proof_url": row[2],
                "timestamp": row[3]
            })
        return jsonify(data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@owner_bp.route('/api/bans/add', methods=['POST'])
async def api_bans_add():
    try:
        data = await request.get_json()
        user_id = data.get('user_id')
        reason = data.get('reason')
        proof_url = data.get('proof_url')
        
        if not user_id: return jsonify({"error": "Missing ID"}), 400

        await bot.db.execute("INSERT OR REPLACE INTO global_bans (user_id, reason, proof_url, added_by) VALUES (?, ?, ?, ?)", 
                             (user_id, reason, proof_url, OWNER_ID))
        await bot.db.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@owner_bp.route('/api/bans/delete', methods=['POST'])
async def api_bans_delete():
    try:
        data = await request.get_json()
        user_id = data.get('user_id')
        
        await bot.db.execute("DELETE FROM global_bans WHERE user_id = ?", (user_id,))
        await bot.db.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =========================================
# 💻 LIVE CONSOLE & INFRA (GOD MODE)
# =========================================

@owner_bp.route('/console')
async def console_page():
    user = session.get('user')
    if not user: return redirect(url_for('owner.login'))
    return await render_template('console.html', user=user)

@owner_bp.route('/api/console')
async def api_console():
    if not bot or not hasattr(bot, 'log_handler'): 
        return jsonify(["❌ Erro: LogHandler não configurado no Bot."])
    
    # Retorna copia da lista para JSON
    return jsonify(list(bot.log_handler.log_queue))

@owner_bp.route('/api/maintenance', methods=['GET', 'POST'])
async def api_maintenance():
    if not bot: return jsonify({"error": "Bot not ready"}), 503
    
    if request.method == 'POST':
        bot.maintenance_mode = not bot.maintenance_mode
        return jsonify({"enabled": bot.maintenance_mode})
    
    return jsonify({"enabled": bot.maintenance_mode})

@owner_bp.route('/broadcast')
async def broadcast_page():
    user = session.get('user')
    if not user: return redirect(url_for('owner.login'))
    return await render_template('broadcast.html', user=user)

@owner_bp.route('/api/broadcast', methods=['POST'])
async def api_broadcast():
    if not bot: return jsonify({"error": "Bot not ready"}), 503
    
    data = await request.get_json()
    title = data.get('title')
    description = data.get('description')
    color = int(data.get('color', '#fbbf24').replace('#', ''), 16)
    image_url = data.get('image_url')
    target = data.get('target', 'owners')

    # Cria o Embed
    embed = discord.Embed(title=title, description=description, color=color)
    if image_url: embed.set_image(url=image_url)
    embed.set_footer(text="Mensagem Oficial do Sistema")

    sent_count = 0
    failed_count = 0

    for guild in bot.guilds:
        try:
            dest = None
            if target == 'owners':
                dest = guild.owner
            else:
                dest = guild.system_channel or guild.text_channels[0]
            
            if dest:
                await dest.send(embed=embed)
                sent_count += 1
        except:
            failed_count += 1
            
    return jsonify({
        "success": True, 
        "sent_count": sent_count, 
        "failed_count": failed_count
    })

# =========================================
# 🩺 HEALTH DOCTOR & GHOST JOIN (GOD MODE)
# =========================================

@owner_bp.route('/health')
async def health_page():
    user = session.get('user')
    if not user: return redirect(url_for('owner.login'))
    return await render_template('health.html', user=user)

@owner_bp.route('/api/health')
async def api_health():
    if not bot: return jsonify({"error": "Bot not ready"}), 503
    
    issues = []
    total_guilds = len(bot.guilds)
    
    for guild in bot.guilds:
        me = guild.me
        if not me.guild_permissions.administrator:
            issues.append({
                "guild_id": str(guild.id),
                "guild_name": guild.name,
                "error": "Faltam Permissões de Administrador"
            })
        elif not me.guild_permissions.embed_links:
             issues.append({
                "guild_id": str(guild.id),
                "guild_name": guild.name,
                "error": "Sem Permissão de Embed Links"
            })
            
    return jsonify({
        "total_guilds": total_guilds,
        "issues": issues
    })

@owner_bp.route('/api/ghost_join', methods=['POST'])
async def api_ghost_join():
    if not bot: return jsonify({"error": "Bot not ready"}), 503
    
    data = await request.get_json()
    guild_id = int(data.get('guild_id'))
    guild = bot.get_guild(guild_id)
    
    if not guild: return jsonify({"error": "Servidor não encontrado"}), 404
    
    # Tenta achar um canal para criar convite
    invite = None
    try:
        # Tenta canais de texto
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).create_instant_invite:
                invite = await channel.create_invite(max_uses=1, max_age=300, reason="Owner Ghost Join")
                break
    except Exception as e:
        return jsonify({"error": f"Falha ao criar convite: {str(e)}"}), 500
        
    if invite:
        return jsonify({"invite_url": invite.url})
    else:
        return jsonify({"error": "Não foi possível criar convite (sem permissão em nenhum canal?)"}), 400

# =========================================
# 🕵️ CHAT SPY (AUDIT VIEWER)
# =========================================

@owner_bp.route('/spy')
async def spy_page():
    user = session.get('user')
    if not user: return redirect(url_for('owner.login'))
    return await render_template('spy.html', user=user)

@owner_bp.route('/api/spy/channels')
async def api_spy_channels():
    if not bot: return jsonify({"error": "Bot not ready"}), 503
    
    guild_id = request.args.get('guild_id', type=int)
    if not guild_id: return jsonify([]), 400
    
    guild = bot.get_guild(guild_id)
    if not guild: return jsonify({"error": "Guild not found"}), 404
    
    channels = []
    # Lista apenas canais de texto que o bot pode ver
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).read_messages:
            channels.append({
                "id": str(channel.id),
                "name": channel.name,
                "position": channel.position
            })
            
    # Ordena por posição no discord
    channels.sort(key=lambda x: x['position'])
    return jsonify(channels)

@owner_bp.route('/api/spy/history')
async def api_spy_history():
    if not bot: return jsonify({"error": "Bot not ready"}), 503
    
    channel_id = request.args.get('channel_id', type=int)
    if not channel_id: return jsonify({"error": "Missing channel_id"}), 400
    
    channel = bot.get_channel(channel_id)
    if not channel: return jsonify({"error": "Channel not found"}), 404
    
    if not channel.permissions_for(channel.guild.me).read_message_history:
        return jsonify({"error": "Sem permissão de ler histórico"}), 403

    messages = []
    try:
        async for msg in channel.history(limit=50):
            messages.append({
                "id": str(msg.id),
                "content": msg.content,
                "author": {
                    "username": msg.author.name,
                    "avatar": msg.author.avatar.key if msg.author.avatar else None,
                    "bot": msg.author.bot
                },
                "timestamp": msg.created_at.isoformat(),
                "attachments": [{"url": a.url} for a in msg.attachments],
                "embeds": [e.to_dict() for e in msg.embeds]
            })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
        
    return jsonify({"messages": messages})

# =========================================
# 🧩 DYNAMIC TIERS & MODULES (Fase 13)
# =========================================

@owner_bp.route('/tiers')
async def tiers_page():
    user = session.get('user')
    if not user: return redirect(url_for('owner.login'))
    return await render_template('tiers.html', user=user)

@owner_bp.route('/api/tiers', methods=['GET'])
async def api_tiers_list():
    if not bot or not bot.db: return jsonify({"error": "Bot not ready"}), 503
    
    # 1. Busca Definições do Banco
    async with bot.db.execute("SELECT tier_name, module_name FROM tier_definitions") as cursor:
        rows = await cursor.fetchall()
        
    # Organiza: tier_data['v8'] = ['streaming', 'tickets']
    tier_data = {t: [] for t in ['start', 'faction', 'police', 'v8', 'owner']}
    defined_modules = set()
    
    for tier, module in rows:
        if tier not in tier_data: tier_data[tier] = []
        tier_data[tier].append(module)
        defined_modules.add(module)
        
    # 2. Identifica Módulos Reais (Cogs Carregados)
    # bot.cogs keys são CaseSensitive -> lower()
    loaded_cogs = [name.lower() for name in bot.cogs.keys()]
    loaded_cogs.sort()
    
    # 3. Detector de Órfãos (Orphan Logic)
    # Módulos carregados que não estão em NENHUM tier
    orphans = [cog for cog in loaded_cogs if cog not in defined_modules]
    
    return jsonify({
        "predictions": loaded_cogs, # Lista de todos os cogs disponíveis
        "tiers": tier_data,
        "orphans": orphans
    })

@owner_bp.route('/api/tiers/update', methods=['POST'])
async def api_tiers_update():
    if not bot or not bot.db: return jsonify({"error": "Bot not ready"}), 503
    
    data = await request.get_json()
    tier = data.get('tier')
    module = data.get('module')
    enabled = data.get('enabled')
    
    if not tier or not module: return jsonify({"error": "Missing data"}), 400
    
    try:
        if enabled:
            await bot.db.execute("INSERT OR IGNORE INTO tier_definitions (tier_name, module_name) VALUES (?, ?)", (tier, module))
        else:
            await bot.db.execute("DELETE FROM tier_definitions WHERE tier_name = ? AND module_name = ?", (tier, module))
            
        await bot.db.commit()
        
        # Recarrega no Bot imediatamente
        if hasattr(bot, 'load_tier_permissions'):
            await bot.load_tier_permissions()
        
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# =========================================
# 🗄️ DATABASE MANAGER
# =========================================

@owner_bp.route('/database')
async def database_page():
    user = session.get('user')
    if not user: return redirect(url_for('owner.login'))
    return await render_template('database.html', user=user)

@owner_bp.route('/api/database/cleanup_inactive', methods=['POST'])
async def api_database_cleanup_inactive():
    if not bot or not bot.db: return jsonify({"error": "Bot not ready"}), 503
    
    try:
        # 1. Identificar Guilds Ativas
        active_ids = [g.id for g in bot.guilds]
        
        # 2. Identificar Guilds no Banco (Exceto Licenses e global_bans)
        # Vamos varrer tabelas principais que usam guild_id
        tables = [
            "config", 
            "active_tickets", 
            "ticket_categories",
            "staff_ratings",
            "presence",
            "suggestion_votes",
            "faction_actions", 
            "action_mvp_votes",
            "active_pings",
            "active_streams",
            "embed_templates",
            "org_punishments", 
            "time_sessions"
        ]
        
        deleted_count = 0
        
        for table in tables:
            try:
                # 3. Verificação de Segurança (Coluna Existe?)
                # Isso impede erros caso o usuário tenha um banco antigo sem a migração
                async with bot.db.execute(f"PRAGMA table_info({table})") as cursor:
                    cols = [row[1] for row in await cursor.fetchall()]
                
                if "guild_id" not in cols:
                    print(f"⚠️ [CLEANUP] Tabela {table} pulada (sem guild_id).")
                    continue

                # 4. Pega IDs distintos na tabela
                async with bot.db.execute(f"SELECT DISTINCT guild_id FROM {table}") as cursor:
                    rows = await cursor.fetchall()
                    db_ids = [row[0] for row in rows if row[0]]
                    
                # 5. Identifica fantasmas (db_ids que nao estao em active_ids)
                ghost_ids = [gid for gid in db_ids if gid not in active_ids]
                
                if ghost_ids:
                    # Deleta em massa
                    placeholders = ','.join('?' for _ in ghost_ids)
                    await bot.db.execute(f"DELETE FROM {table} WHERE guild_id IN ({placeholders})", tuple(ghost_ids))
                    deleted_count += bot.db.total_changes
            except Exception as ex:
                print(f"❌ [CLEANUP ERROR] Falha na tabela {table}: {ex}")
                continue
                
        await bot.db.commit()
        
        return jsonify({"success": True, "deleted_rows": deleted_count})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@owner_bp.route('/api/database/stats')
async def api_db_stats():
    if not bot or not bot.db: return jsonify({"error": "Bot not ready"}), 503
    
    try:
        # File Size
        import os
        db_path = "database/bot_data.db"
        size_mb = os.path.getsize(db_path) / (1024 * 1024) if os.path.exists(db_path) else 0
        
        # Table Counts
        tables = ["licenses", "config", "audit_logs", "faction_actions", "active_tickets"]
        counts = {}
        total_rows = 0
        
        for table in tables:
            try:
                async with bot.db.execute(f"SELECT COUNT(*) FROM {table}") as cursor:
                    row = await cursor.fetchone()
                    count = row[0]
                    counts[table] = count
                    total_rows += count
            except:
                counts[table] = 0

        return jsonify({
            "size_mb": round(size_mb, 2),
            "total_rows": total_rows,
            "details": counts
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@owner_bp.route('/api/database/guilds')
async def api_db_guilds():
    if not bot or not bot.db: return jsonify({"error": "Bot not ready"}), 503
    
    try:
        # Pega todos os guilds distintos da tabela CONFIG (que é a base)
        # E cruza com nomes se possível via Bot, senão via banco
        # Idealmente, pega da tabela que tem mais dados. Vamos usar Licenses + Configs
        
        guilds_data = {}
        
        # 1. Pega configs
        async with bot.db.execute("SELECT guild_id FROM config") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                guilds_data[row[0]] = {"id": str(row[0]), "source": "config"}

        # 2. Pega licenças
        async with bot.db.execute("SELECT guild_id, client_name FROM licenses") as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                gid = row[0]
                if gid not in guilds_data:
                    guilds_data[gid] = {"id": str(gid), "source": "license"}
                guilds_data[gid]['name'] = row[1]
        
        # 3. Enriquece com dados do Bot (se online)
        results = []
        for gid, data in guilds_data.items():
            guild = bot.get_guild(gid)
            
            # Conta items (simples)
            items_count = 0 
            # (Poderíamos fazer queries pesadas aqui, mas vamos simplificar)
            
            status = "unknown"
            if guild:
                status = "online"
                data['name'] = guild.name
                data['member_count'] = guild.member_count
                items_count = len(guild.text_channels) # Exemplo bobo de stats
            else:
                status = "ghost" # Bot não está mais lá
            
            data['status'] = status
            data['items_count'] = items_count # Placeholder
            results.append(data)
            
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@owner_bp.route('/api/database/wipe_guild', methods=['POST'])
async def api_db_wipe():
    data = await request.get_json()
    guild_id = data.get('guild_id')
    keep_license = data.get('keep_license', True)
    
    if not guild_id: return jsonify({"error": "Missing guild_id"}), 400
    
    try:
        # LISTA DE TABELAS PARA LIMPAR
        tables = [
            "config", "ticket_categories", "active_tickets", "staff_ratings", 
            "presence", "suggestion_votes", "faction_actions", "action_mvp_votes",
            "active_pings", "embed_templates", "audit_logs"
        ]
        
        deleted_count = 0
        for table in tables:
            try:
                # Verifica se tabela tem coluna guild_id
                # (Assumindo que todas listadas acima têm. Se não, try/except segura)
                async with bot.db.execute(f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,)) as cursor:
                    deleted_count += cursor.rowcount
            except:
                pass
        
        # Limpa License se solicitado
        if not keep_license:
            async with bot.db.execute("DELETE FROM licenses WHERE guild_id = ?", (guild_id,)) as cursor:
                deleted_count += cursor.rowcount
                
        await bot.db.commit()
        return jsonify({"success": True, "deleted_rows": deleted_count})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@owner_bp.route('/api/database/backup')
async def api_db_backup():
    try:
        return await send_from_directory('database', 'bot_data.db', as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@owner_bp.route('/api/database/restore', methods=['POST'])
async def api_db_restore():
    files = await request.files
    f = files.get('file')
    
    if f:
        # Salva como .db (sobrescrevendo?? Perigoso! Mas é o pedido)
        # O ideal seria salvar um .bak antes
        import shutil
        shutil.copy("database/bot_data.db", "database/bot_data.db.bak")
        
        await f.save("database/bot_data.db")
        
        # Reinicia conexão DB no bot?? Complexo.
        # Melhor pedir restart.
        return jsonify({"success": True, "message": "Banco restaurado. REINICIE O BOT IMEDIATAMENTE."})
        
    return jsonify({"error": "No file"}), 400

# =========================================
# 📂 TRANSCRIPTS & ROOT
# =========================================

@app.route('/')
async def root():
    return "🤖 CityBot Transcript Server está Online! <br> <a href='/owner'>Acessar Painel do Dono</a>"

@app.route('/transcripts/<path:filename>')
async def serve_transcripts(filename):
    # Garante que a pasta existe
    if not os.path.exists('transcripts'):
        os.makedirs('transcripts')
    return await send_from_directory('transcripts', filename)

async def run_dashboard():
    """Função para rodar o servidor web (chamada pelo main.py)"""
    # Registra o Blueprint
    app.register_blueprint(owner_bp)
    
    port = int(os.getenv("PORT", 5000))
    # Hypercorn roda nativamente com asyncio, ideal para integrar com Discord.py
    from hypercorn.config import Config
    from hypercorn.asyncio import serve

    config = Config()
    config.bind = [f"0.0.0.0:{port}"]
    
    print(f"🌐 [DASHBOARD] Iniciando na porta {port}...")
    await serve(app, config)
