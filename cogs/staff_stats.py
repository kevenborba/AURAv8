import discord
from discord.ext import commands
from discord import app_commands
import sys
import os
import io
import csv
import datetime

# Tenta importar as configurações
try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import config
except ImportError:
    class config:
        EMBED_COLOR = 0x992d22

# URL Mágica para esticar o Embed
INVISIBLE_WIDE_URL = "https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png"

class StaffStats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def render_stars(self, rating):
        full_stars = int(rating)
        return "⭐" * full_stars

    # ====================================================
    # 🏆 RANKING (AGORA ESTICADO E COM FILTRO)
    # ====================================================
    @app_commands.command(name="ranking_staff", description="🏆 Top 10 melhores atendentes")
    @app_commands.describe(periodo="Filtrar por período (Padrão: Geral)")
    @app_commands.choices(periodo=[
        app_commands.Choice(name="📅 Deste Mês (Staff do Mês)", value="mes"),
        app_commands.Choice(name="♾️ Geral (Desde sempre)", value="geral")
    ])
    @app_commands.checks.has_permissions(administrator=True)
    async def ranking_staff(self, interaction: discord.Interaction, periodo: app_commands.Choice[str] = None):
        await interaction.response.defer()

        mode = periodo.value if periodo else "geral"
        
        sql = "SELECT staff_id, COUNT(*) as total, AVG(stars) as media FROM staff_ratings WHERE guild_id = ?"
        params = [interaction.guild.id]

        if mode == "mes":
            current_month = datetime.datetime.now().strftime('%Y-%m-01')
            sql += " AND date >= ?"
            params.append(current_month)
            title_text = f"🏆 Staff do Mês ({datetime.datetime.now().strftime('%m/%Y')})"
        else:
            title_text = "🏆 Ranking Geral de Atendimento"

        sql += " GROUP BY staff_id ORDER BY media DESC, total DESC LIMIT 10"

        async with self.bot.db.execute(sql, tuple(params)) as cursor:
            rank_data = await cursor.fetchall()

        if not rank_data:
            return await interaction.followup.send(f"❌ Nenhuma avaliação encontrada para o período: **{mode.upper()}**.")

        embed = discord.Embed(title=title_text, color=0xf1c40f)
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        
        # AQUI ESTÁ O SEGREDO DO EMBED LARGO
        embed.set_image(url=INVISIBLE_WIDE_URL)
        
        medals = ["🥇", "🥈", "🥉"]
        
        description = ""
        for idx, row in enumerate(rank_data):
            staff_id, total_votos, media_nota = row
            
            medalha = medals[idx] if idx < 3 else f"`{idx+1}.`"
            staff_member = interaction.guild.get_member(staff_id)
            staff_name = staff_member.mention if staff_member else f"Ex-Staff ({staff_id})"
            
            description += (
                f"{medalha} {staff_name}\n"
                f"└─ **{media_nota:.1f}** {self.render_stars(media_nota)} • ({total_votos} votos)\n\n"
            )

        embed.description = description
        embed.set_footer(text=f"Solicitado por {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
        await interaction.followup.send(embed=embed)

    # ====================================================
    # 📑 RELATÓRIO EXCEL
    # ====================================================
    @app_commands.command(name="relatorio_staff", description="📂 Baixa planilha com TODAS as avaliações (Auditoria)")
    @app_commands.checks.has_permissions(administrator=True)
    async def export_csv(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        async with self.bot.db.execute("SELECT staff_id, user_id, stars, date FROM staff_ratings WHERE guild_id = ? ORDER BY date DESC", (interaction.guild.id,)) as cursor:
            rows = await cursor.fetchall()

        if not rows:
            return await interaction.followup.send("❌ Banco de dados vazio.")

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Data", "Nome Staff", "ID Staff", "Nome Cliente", "ID Cliente", "Nota"])

        for row in rows:
            staff_id, user_id, stars, date_str = row
            try: dt = datetime.datetime.fromisoformat(date_str).strftime("%d/%m/%Y %H:%M")
            except: dt = date_str

            s_member = interaction.guild.get_member(staff_id)
            u_member = interaction.guild.get_member(user_id)
            
            s_name = s_member.name if s_member else "Desconhecido"
            u_name = u_member.name if u_member else "Desconhecido"

            writer.writerow([dt, s_name, str(staff_id), u_name, str(user_id), str(stars)])

        output.seek(0)
        file = discord.File(fp=io.BytesIO(output.getvalue().encode('utf-8')), filename=f"relatorio_staff_{datetime.date.today()}.csv")
        
        await interaction.followup.send(
            content=f"✅ **Relatório Gerado!**\nForam encontradas `{len(rows)}` avaliações.", 
            file=file
        )

    # ====================================================
    # 👤 MEUS STATS (ESTICADO TAMBÉM)
    # ====================================================
    @app_commands.command(name="meus_stats", description="📊 Suas estatísticas pessoais")
    async def my_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        query = "SELECT COUNT(*) as total, AVG(stars) as media FROM staff_ratings WHERE guild_id = ? AND staff_id = ?"
        async with self.bot.db.execute(query, (interaction.guild.id, interaction.user.id)) as cursor:
            data = await cursor.fetchone()

        total, media = data if data else (0, 0)
        if not total: return await interaction.followup.send("❌ Sem dados.", ephemeral=True)
        media = media or 0

        embed = discord.Embed(title=f"📊 Stats: {interaction.user.name}", color=config.EMBED_COLOR)
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        
        # AQUI TAMBÉM ESTICA
        embed.set_image(url=INVISIBLE_WIDE_URL)
        
        embed.add_field(name="Atendimentos", value=str(total), inline=True)
        embed.add_field(name="Nota Média", value=f"{media:.2f} ⭐", inline=True)
        
        pct = int((media/5)*100)
        bar = '🟩' * int(pct/10) + '⬛' * (10 - int(pct/10))
        embed.add_field(name="Performance", value=f"{bar} {pct}%", inline=False)
        
        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(StaffStats(bot))