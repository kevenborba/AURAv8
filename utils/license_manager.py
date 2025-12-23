import discord
from discord.ext import commands
from datetime import datetime, timedelta
import aiosqlite

DB_NAME = "database/bot_data.db"

# Cache simples para evitar queries excessivas (Guild ID -> Status)
# Ex: {123456: {'status': 'active', 'expires': datetime...}}
LICENSE_CACHE = {}

async def get_license_status(guild_id: int, db_connection=None):
    """Verifica o status da licença no banco de dados"""
    
    # 1. Verifica Cache (TTL de 5 minutos poderia ser implementado aqui)
    if guild_id in LICENSE_CACHE:
        # Se expirou no cache, força re-check
        if LICENSE_CACHE[guild_id]['status'] == 'active':
            if datetime.now() > LICENSE_CACHE[guild_id]['expires']:
                pass # Continua para query
            else:
                return LICENSE_CACHE[guild_id]

    # Se não passou conexão, cria uma temporária (fallback)
    if db_connection:
        cursor = await db_connection.execute("SELECT status, expiration_date FROM licenses WHERE guild_id = ?", (guild_id,))
        row = await cursor.fetchone()
        await cursor.close()
        # Não fecha a conexão compartilhada!
        
        if not row:
            return {"status": "no_license", "msg": "🚫 **Este servidor não possui uma licença ativa.**"}
        
        status, exp_str = row
        try:
            expires = datetime.strptime(exp_str, "%Y-%m-%d")
        except:
            expires = datetime.max
            
        # Lógica de Vencimento
        if status == 'active' and datetime.now() > expires:
            grace_end = expires + timedelta(days=3)
            
            if datetime.now() < grace_end:
                return {"status": "grace_period", "msg": "⚠️ **Sua licença venceu!** Você tem 3 dias de carência. Renove agora."}
            else:
                await db_connection.execute("UPDATE licenses SET status = 'locked' WHERE guild_id = ?", (guild_id,))
                await db_connection.commit()
                return {"status": "locked", "msg": "🔒 **Licença Bloqueada.** O período de carência acabou. Contate o suporte."}
        
        if status == 'locked':
             return {"status": "locked", "msg": "🔒 **Licença Bloqueada.** Contate o suporte para desbloquear."}

        LICENSE_CACHE[guild_id] = {'status': 'active', 'expires': expires}
        return {"status": "active", "msg": None}

    else:
        # Fallback: Cria conexão nova (não recomendado para uso intenso)
        async with aiosqlite.connect(DB_NAME) as db:
            return await get_license_status(guild_id, db)

def check_license():
    """Decorator para comandos: Bloqueia se não tiver licença"""
    async def predicate(ctx):
        if not ctx.guild: return True 
        
        if await ctx.bot.is_owner(ctx.author): return True

        # Passa a conexão do bot para evitar locking
        db = getattr(ctx.bot, 'db', None)
        data = await get_license_status(ctx.guild.id, db)
        
        if data['status'] == 'active':
            return True
        
        if data['status'] == 'grace_period':
            await ctx.send(data['msg'], delete_after=10)
            return True
            
        if data['status'] in ['locked', 'no_license']:
            raise commands.CheckFailure(data['msg'])
            
        return False
    
    return commands.check(predicate)
