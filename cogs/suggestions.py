import discord
import sys
import os
import datetime
from discord.ext import commands
from discord import app_commands, ui

try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import config
except ImportError:
    class config:
        EMBED_COLOR = 0x000000

# IMAGEM TRANSPARENTE WIDE (Força a largura do Embed)
INVISIBLE_WIDE_URL = "https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png"

def parse_emoji(custom_emoji):
    if not custom_emoji: return None
    try: return discord.PartialEmoji.from_str(custom_emoji)
    except: return custom_emoji

class Suggestions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ====================================================
    # 🖥️ PAINEL ADMIN
    # ====================================================
    @app_commands.command(name="painel_sugestoes", description="Configura o sistema de sugestões")
    @app_commands.checks.has_permissions(administrator=True)
    async def sugg_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.send_panel(interaction)

    async def send_panel(self, interaction: discord.Interaction, is_edit=False):
        async with self.bot.db.execute("SELECT * FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            row = await cursor.fetchone()
            data = dict(zip([d[0] for d in cursor.description], row)) if row else {}

        chan_id = data.get('sugg_channel_id')
        chan = self.bot.get_channel(chan_id) if chan_id else None
        
        color = data.get('sugg_color') or config.EMBED_COLOR
        up_emj = data.get('sugg_up_emoji') or "✅"
        down_emj = data.get('sugg_down_emoji') or "❌"
        count = data.get('sugg_count', 0)

        embed = discord.Embed(title="💡 Gerenciador de Sugestões", color=color)
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        status = f"✅ Ativo em {chan.mention}" if chan else "🔴 Canal não definido"
        
        embed.description = (
            f"Configure por aqui onde as sugestões serão enviadas e o visual delas.\n\n"
            f"📢 **Canal Atual:** {status}\n"
            f"🔢 **Próximo ID:** `#{count + 1:03d}`\n\n"
            f"**Visual:**\n"
            f"🎨 Cor Base: `#{hex(color)[2:].upper()}`\n"
            f"👍 Emoji Aprovar: {up_emj}\n"
            f"👎 Emoji Reprovar: {down_emj}\n"
        )
        
        view = AdminSuggView(self.bot, self)
        
        if is_edit: await interaction.edit_original_response(embed=embed, view=view)
        else: await interaction.followup.send(embed=embed, view=view)

    # ====================================================
    # 📨 EVENTO DE MENSAGEM (GATILHO)
    # ====================================================
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot: return
        
        async with self.bot.db.execute("SELECT sugg_channel_id FROM config WHERE guild_id = ?", (message.guild.id,)) as cursor:
            res = await cursor.fetchone()
        
        if not res or message.channel.id != res[0]: return

        try: await message.delete()
        except: pass 

        embed = discord.Embed(
            title="📝 Confirmar Sugestão",
            description=f"Olá {message.author.mention}, você deseja enviar a seguinte sugestão?\n\n```txt\n{message.content}\n```",
            color=discord.Color.gold()
        )
        embed.set_footer(text="Esta mensagem sumirá em 60 segundos.")
        
        view = ConfirmSuggestionView(self.bot, message.content, message.author)
        msg = await message.channel.send(embed=embed, view=view, delete_after=60)
        view.message = msg 

    # ====================================================
    # 🗳️ LÓGICA DE VOTOS
    # ====================================================
    async def update_vote(self, interaction, msg_id, vote_type):
        user_id = interaction.user.id
        
        async with self.bot.db.execute("SELECT vote_type FROM suggestion_votes WHERE message_id = ? AND user_id = ?", (msg_id, user_id)) as cursor:
            existing = await cursor.fetchone()

        if existing:
            if existing[0] == vote_type:
                await self.bot.db.execute("DELETE FROM suggestion_votes WHERE message_id = ? AND user_id = ?", (msg_id, user_id))
            else:
                await self.bot.db.execute("UPDATE suggestion_votes SET vote_type = ? WHERE message_id = ? AND user_id = ?", (vote_type, msg_id, user_id))
        else:
            await self.bot.db.execute("INSERT INTO suggestion_votes (message_id, user_id, vote_type) VALUES (?, ?, ?)", (msg_id, user_id, vote_type))
        
        await self.bot.db.commit()
        await self.refresh_buttons(interaction, msg_id)

    async def refresh_buttons(self, interaction, msg_id):
        async with self.bot.db.execute("SELECT vote_type, COUNT(*) FROM suggestion_votes WHERE message_id = ? GROUP BY vote_type", (msg_id,)) as cursor:
            rows = await cursor.fetchall()
            
        votes = {'up': 0, 'down': 0}
        for r in rows: votes[r[0]] = r[1]
        
        total = votes['up'] + votes['down']
        perc_up = (votes['up'] / total * 100) if total > 0 else 0
        perc_down = (votes['down'] / total * 100) if total > 0 else 0

        async with self.bot.db.execute("SELECT sugg_up_emoji, sugg_down_emoji, sugg_color FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            res = await cursor.fetchone()
        
        up_emj = res[0] or "✅"
        down_emj = res[1] or "❌"
        base_color = res[2] or config.EMBED_COLOR

        if total == 0: new_color = base_color
        elif perc_up >= 60: new_color = 0x2ecc71 
        elif perc_down >= 60: new_color = 0xe74c3c 
        else: new_color = 0xf1c40f 

        try:
            msg = await interaction.channel.fetch_message(msg_id)
            embed = msg.embeds[0]
            embed.color = new_color
            
            view = VotingView(self.bot, self, up_emj, down_emj, votes['up'], votes['down'], perc_up, perc_down)
            
            try:
                await msg.edit(embed=embed, view=view)
            except discord.HTTPException as e:
                if e.code == 50035 and "Invalid emoji" in str(e):
                    view = VotingView(self.bot, self, "✅", "❌", votes['up'], votes['down'], perc_up, perc_down)
                    await msg.edit(embed=embed, view=view)
                else:
                    raise e
            if not interaction.response.is_done(): await interaction.response.defer()
        except Exception as e:
            print(f"Erro ao atualizar: {e}")

# ====================================================
# VIEWS
# ====================================================

class VotingView(ui.View):
    def __init__(self, bot, cog, up_emj, down_emj, count_up, count_down, perc_up, perc_down):
        super().__init__(timeout=None)
        self.bot = bot
        self.cog = cog

        self.add_item(ui.Button(
            style=discord.ButtonStyle.secondary,
            emoji=parse_emoji(up_emj),
            label=f"{count_up} Votos | ({int(perc_up)}%)",
            custom_id="vote_up"
        ))
        
        self.add_item(ui.Button(
            style=discord.ButtonStyle.secondary,
            emoji=parse_emoji(down_emj),
            label=f"{count_down} Votos | ({int(perc_down)}%)",
            custom_id="vote_down"
        ))

    async def interaction_check(self, interaction: discord.Interaction):
        if self.cog is None: self.cog = self.bot.get_cog("Suggestions")
        if not self.cog: return False

        cid = interaction.data['custom_id']
        if cid == "vote_up": await self.cog.update_vote(interaction, interaction.message.id, "up")
        elif cid == "vote_down": await self.cog.update_vote(interaction, interaction.message.id, "down")
        return False

# --- CLASSE ATUALIZADA COM VISUAL DE CAMPO E WIDE ---
class ConfirmSuggestionView(ui.View):
    def __init__(self, bot, content, author):
        super().__init__(timeout=60)
        self.bot = bot
        self.content = content
        self.author = author
        self.message = None

    @ui.button(label="✅ Confirmar Envio", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user != self.author:
            return await interaction.response.send_message("❌ Apenas o autor pode confirmar.", ephemeral=True)
        
        # Defer immediately
        await interaction.response.defer(ephemeral=True)

        try:
            async with self.bot.db.execute("SELECT sugg_count, sugg_color, sugg_up_emoji, sugg_down_emoji FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
                res = await cursor.fetchone()
                count = (res[0] or 0) + 1
                color = res[1] or config.EMBED_COLOR
                up_emj = res[2] or "✅"
                down_emj = res[3] or "❌"

            await self.bot.db.execute("UPDATE config SET sugg_count = ? WHERE guild_id = ?", (count, interaction.guild.id))
            await self.bot.db.commit()

            # Construct Embed
            embed = discord.Embed(title=f"💡 Sugestão #{count:03d}", color=color)
            embed.description = f"👤 **Autor:** {self.author.mention} • 🆔 `{self.author.id}`"
            embed.set_thumbnail(url=self.author.display_avatar.url)
            embed.add_field(name="📄 Conteúdo", value=f"```txt\n{self.content}\n```", inline=False)
            embed.set_footer(text="📊 Vote usando os botões abaixo", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
            embed.timestamp = datetime.datetime.now()
            embed.set_image(url=INVISIBLE_WIDE_URL)

            cog_instance = self.bot.get_cog("Suggestions")
            
            # Helper to create view
            def create_view(up, down):
                return VotingView(self.bot, cog_instance, up, down, 0, 0, 0, 0)

            msg = None
            sent_success = False

            # --- TENTATIVA 1: Enviando com Embed e Emojis Customizados ---
            try:
                view = create_view(up_emj, down_emj)
                msg = await interaction.channel.send(embed=embed, view=view)
                sent_success = True
            except discord.HTTPException as e:
                # Se for erro de Emoji Inválido (50035), tenta com emojis padrão
                if e.code == 50035 and "Invalid emoji" in str(e):
                    try:
                        view = create_view("✅", "❌")
                        msg = await interaction.channel.send(embed=embed, view=view)
                        sent_success = True
                    except Exception:
                        pass # Vai para o fallback de texto
                else:
                    pass # Erro genérico (ex: Embed Links forbidden), vai para fallback
            except discord.Forbidden:
                pass # Erro de permissão, vai para fallback
            except Exception as e:
                print(f"Erro inesperado no envio de embed: {e}")
            
            # --- TENTATIVA 2: FALLBACK PARA TEXTO PURO (MODO DE SEGURANÇA) ---
            if not sent_success:
                text_content = (
                    f"**💡 SUGESTÃO #{count:03d}**\n"
                    f"👤 **Autor:** {self.author.mention}\n\n"
                    f"📄 **Conteúdo:**\n"
                    f"```txt\n{self.content}\n```\n"
                    f"⚠️ _(Exibição simplificada devido a restrições de permissão ou erro de visual)_"
                )
                try:
                    view = create_view("✅", "❌") # Garante emojis seguros
                    msg = await interaction.channel.send(content=text_content, view=view)
                except Exception as e:
                    # Se falhar aqui, é porque o bot não pode enviar NADA no canal
                    return await interaction.followup.send(f"❌ **ERRO FATAL:** O bot não consegue enviar mensagens neste canal (`{interaction.channel.name}`). Verifique as permissões de 'Enviar Mensagens'.\nErro Técnico: `{e}`", ephemeral=True)

            # Thread creation (Safe)
            if msg:
                try: await msg.create_thread(name=f"Debate: Sugestão #{count:03d}", auto_archive_duration=1440)
                except: pass

            # Delete prompt
            try: await interaction.message.delete()
            except: pass
            
            await interaction.followup.send(f"✅ Sugestão `#{count:03d}` enviada com sucesso!", ephemeral=True)

        except Exception as e:
            print(f"ERRO CRÍTICO AO CONFIRMAR SUGESTÃO: {e}")
            await interaction.followup.send(f"❌ Ocorreu um erro interno ao processar: {e}", ephemeral=True)

    @ui.button(label="🗑️ Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user != self.author: return
        try: await interaction.message.delete()
        except: pass

# ====================================================
# PAINEL ADMIN
# ====================================================

class ConfigSuggModal(ui.Modal, title="🎨 Visual Sugestões"):
    def __init__(self, bot, cog, origin, cur_color, cur_up, cur_down):
        super().__init__()
        self.bot = bot
        self.cog = cog
        self.origin = origin
        
        hex_val = f"#{cur_color:06X}" if cur_color else "#000000"
        self.color = ui.TextInput(label="Cor HEX", default=hex_val, min_length=7, max_length=7)
        self.up = ui.TextInput(label="Emoji Aprovar", default=cur_up)
        self.down = ui.TextInput(label="Emoji Reprovar", default=cur_down)
        self.add_item(self.color)
        self.add_item(self.up)
        self.add_item(self.down)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try: col = int(self.color.value.replace("#", ""), 16)
        except: return await interaction.followup.send("Cor inválida!")

        await self.bot.db.execute("""
            UPDATE config SET sugg_color = ?, sugg_up_emoji = ?, sugg_down_emoji = ? 
            WHERE guild_id = ?
        """, (col, self.up.value, self.down.value, interaction.guild.id))
        await self.bot.db.commit()
        await interaction.followup.send("✅ Configuração salva!")
        await self.cog.send_panel(self.origin, is_edit=True)

class AdminSuggView(ui.View):
    def __init__(self, bot, cog):
        super().__init__(timeout=None)
        self.bot = bot
        self.cog = cog

    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Selecione o Canal de Sugestões...", channel_types=[discord.ChannelType.text])
    async def sel_chan(self, interaction: discord.Interaction, select: ui.ChannelSelect):
        await interaction.response.defer()
        await self.bot.db.execute("UPDATE config SET sugg_channel_id = ? WHERE guild_id = ?", (select.values[0].id, interaction.guild.id))
        await self.bot.db.commit()
        await self.cog.send_panel(interaction, is_edit=True)

    @ui.button(label="Editar Visual (Emojis/Cor)", style=discord.ButtonStyle.secondary, emoji="🎨")
    async def edit_vis(self, interaction: discord.Interaction, button: ui.Button):
        async with self.bot.db.execute("SELECT sugg_color, sugg_up_emoji, sugg_down_emoji FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            res = await cursor.fetchone()
        
        col = res[0] or config.EMBED_COLOR
        up = res[1] or "✅"
        down = res[2] or "❌"
        await interaction.response.send_modal(ConfigSuggModal(self.bot, self.cog, interaction, col, up, down))

async def setup(bot):
    await bot.add_cog(Suggestions(bot))