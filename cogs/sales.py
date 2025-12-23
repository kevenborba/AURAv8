import discord
from discord.ext import commands
from discord import app_commands, ui
import datetime

INVISIBLE_WIDE_URL = "https://raw.githubusercontent.com/bpevs/transparent-textures/master/1000x1.png"

class Sales(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        # Tabela de Vendas
        await self.bot.db.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                seller_id INTEGER,
                item TEXT,
                quantity INTEGER,
                price INTEGER,
                buyer TEXT,
                is_partnership INTEGER,
                timestamp TIMESTAMP
            )
        """)
        
        # Atualiza Config se necessário (existem outras colunas no bot_db.py, aqui só garante as de log se falhar lá)
        # O bot_db.py já cuida das migrações principais.
        await self.bot.db.commit()
        print("✅ [Sales] Tabelas carregadas.")

    @commands.Cog.listener()
    async def on_ready(self):
        # View persistente para escutar interações (o visual não importa aqui, só o custom_id)
        self.bot.add_view(SalesPanelView(self.bot))
        print("✅ [Sales] View persistente carregada.")

    # ====================================================
    # ⚙️ CONFIGURAÇÃO
    # ====================================================
    @app_commands.command(name="config_vendas", description="Configura o sistema de vendas (Logs e Aparência).")
    @app_commands.describe(
        logs="Canal para logs de vendas", 
        hex_color="Cor do Painel (Ex: #2ecc71)", 
        emoji="Emoji do Botão Principal",
        emoji_normal="Emoji para Venda Normal",
        emoji_parceria="Emoji para Venda Parceria"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_sales(self, interaction: discord.Interaction, logs: discord.TextChannel = None, hex_color: str = None, emoji: str = None, emoji_normal: str = None, emoji_parceria: str = None):
        if not any([logs, hex_color, emoji, emoji_normal, emoji_parceria]):
            return await interaction.response.send_message("❌ Defina pelo menos uma opção.", ephemeral=True)

        msg = []
        
        if logs:
            try:
                await self.bot.db.execute("UPDATE config SET sales_log_channel_id = ? WHERE guild_id = ?", (logs.id, interaction.guild.id))
                msg.append(f"✅ Logs definidos para {logs.mention}")
            except Exception as e:
                msg.append(f"❌ Erro ao salvar logs: {e}")
            
        if hex_color:
            try:
                hex_clean = hex_color.replace("#", "")
                new_color = int(hex_clean, 16)
                await self.bot.db.execute("UPDATE config SET sales_panel_color = ? WHERE guild_id = ?", (new_color, interaction.guild.id))
                msg.append(f"🎨 Cor do Painel atualizada para `#{hex_clean}`")
            except:
                msg.append("❌ Cor inválida! Use formato Hex (Ex: #FF0000).")

        if emoji:
            await self.bot.db.execute("UPDATE config SET sales_btn_emoji = ? WHERE guild_id = ?", (emoji, interaction.guild.id))
            msg.append(f"💰 Emoji Painel atualizado para {emoji}")

        if emoji_normal:
            await self.bot.db.execute("UPDATE config SET sales_emoji_normal = ? WHERE guild_id = ?", (emoji_normal, interaction.guild.id))
            msg.append(f"💵 Emoji 'Normal' atualizado para {emoji_normal}")

        if emoji_parceria:
            await self.bot.db.execute("UPDATE config SET sales_emoji_partnership = ? WHERE guild_id = ?", (emoji_parceria, interaction.guild.id))
            msg.append(f"🤝 Emoji 'Parceria' atualizado para {emoji_parceria}")

        await self.bot.db.commit()
        await interaction.response.send_message("\n".join(msg), ephemeral=True)

    # ====================================================
    # 🖥️ PAINEL
    # ====================================================
    @app_commands.command(name="painel_vendas", description="Envia o painel de registro de vendas.")
    @app_commands.checks.has_permissions(administrator=True)
    async def sales_panel(self, interaction: discord.Interaction):
        # Busca config
        async with self.bot.db.execute("SELECT sales_panel_color, sales_btn_emoji FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            data = await cursor.fetchone()
            
        # Defaults
        color = data[0] if data and data[0] else 0x2ecc71
        emoji_btn = data[1] if data and data[1] else "💰"

        embed = discord.Embed(title="💰 Controle de Vendas", description="Clique abaixo para registrar uma nova venda.", color=color)
        
        # Ultrawide + Avatar do Bot
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_image(url=INVISIBLE_WIDE_URL)
        embed.set_footer(text="Sistema de Gestão Financeira")
        
        # View com emoji customizado
        view = SalesPanelView(self.bot, emoji=emoji_btn)
        
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Painel enviado!", ephemeral=True)

    # ====================================================
    # 🏆 RANKING
    # ====================================================
    @app_commands.command(name="ranking_vendas", description="Exibe o ranking de vendas.")
    @app_commands.describe(periodo="Período do ranking (Semanal, Mensal ou Geral)")
    @app_commands.choices(periodo=[
        app_commands.Choice(name="Semanal (7 dias)", value="weekly"),
        app_commands.Choice(name="Mensal (Mês Atual)", value="monthly"),
        app_commands.Choice(name="Geral (Todo o tempo)", value="all")
    ])
    async def sales_ranking(self, interaction: discord.Interaction, periodo: app_commands.Choice[str] = None):
        period_val = periodo.value if periodo else "all"
        guild_id = interaction.guild.id
        
        if period_val == "weekly":
            query = """
                SELECT seller_id, SUM(price) as total 
                FROM sales 
                WHERE guild_id = ? AND timestamp >= datetime('now', '-7 days', 'localtime')
                GROUP BY seller_id 
                ORDER BY total DESC 
                LIMIT 10
            """
            title_text = "🏆 Ranking Semanal de Vendas"
        elif period_val == "monthly":
            query = """
                SELECT seller_id, SUM(price) as total 
                FROM sales 
                WHERE guild_id = ? AND timestamp >= datetime('now', 'start of month', 'localtime')
                GROUP BY seller_id 
                ORDER BY total DESC 
                LIMIT 10
            """
            title_text = "🏆 Ranking Mensal de Vendas"
        else:
            query = """
                SELECT seller_id, SUM(price) as total 
                FROM sales 
                WHERE guild_id = ? 
                GROUP BY seller_id 
                ORDER BY total DESC 
                LIMIT 10
            """
            title_text = "🏆 Ranking Geral de Vendas"
            
        async with self.bot.db.execute(query, (guild_id,)) as cursor:
            rows = await cursor.fetchall()
            
        if not rows:
            return await interaction.response.send_message(f"ℹ️ Nenhum dado de venda encontrado para o período **{title_text}**.", ephemeral=True)
            
        embed = discord.Embed(title=title_text, color=0xf1c40f)
        description = ""
        
        for i, (seller_id, total) in enumerate(rows, 1):
            emoji_rank = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            user = interaction.guild.get_member(seller_id)
            user_mention = user.mention if user else f"User ID: {seller_id}"
            
            description += f"{emoji_rank} **{user_mention}** — $ {total:,}\n"
            
        embed.description = description
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else self.bot.user.display_avatar.url)
        embed.set_footer(text=f"Top 10 Vendedores • {datetime.datetime.now().strftime('%d/%m/%Y')}")
        
        await interaction.response.send_message(embed=embed)

# ====================================================
# 🔘 VIEWS E MODAIS
# ====================================================
class SalesPanelView(ui.View):
    def __init__(self, bot, emoji="💰"):
        super().__init__(timeout=None)
        self.bot = bot
        
        # Botão Cinza (Secondary) com Emoji configurável
        btn = ui.Button(label=f"Registrar Venda", emoji=emoji, style=discord.ButtonStyle.secondary, custom_id="sales_register_btn")
        btn.callback = self.register_btn_callback
        self.add_item(btn)

    async def register_btn_callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(SalesModal(self.bot))

class SalesModal(ui.Modal, title="Registrar Venda"):
    item = ui.TextInput(label="Item", placeholder="Ex: Munição G3, AK-47...", style=discord.TextStyle.short)
    quantity = ui.TextInput(label="Quantidade", placeholder="Ex: 500", style=discord.TextStyle.short)
    price = ui.TextInput(label="Valor Total ($)", placeholder="Ex: 50000", style=discord.TextStyle.short)
    buyer = ui.TextInput(label="Comprador", placeholder="Ex: Vagos, @Cliente...", style=discord.TextStyle.short)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = int(self.quantity.value)
            val = int(self.price.value)
        except:
             return await interaction.response.send_message("❌ Quantidade e Valor devem ser números.", ephemeral=True)
             
        # Pergunta se é Parceria
        data = {
            'item': self.item.value,
            'qty': qty,
            'price': val,
            'buyer': self.buyer.value
        }
        
        # Busca config para os emojis dos botões
        async with self.bot.db.execute("SELECT sales_emoji_normal, sales_emoji_partnership FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            res = await cursor.fetchone()
            
        e_normal = res[0] if res and res[0] else "💵"
        e_partnership = res[1] if res and res[1] else "🤝"

        # Removemos o texto de ajuda conforme solicitado
        await interaction.response.send_message(
            "Essa venda foi preço de parceria?", 
            view=SalesTypeView(self.bot, data, e_normal, e_partnership), 
            ephemeral=True
        )

class SalesTypeView(ui.View):
    def __init__(self, bot, data, e_normal="💵", e_partnership="🤝"):
        super().__init__(timeout=60)
        self.bot = bot
        self.data = data
        
        # Cria botões dinamicamente para usar os emojis passados e estilo cinza
        btn_normal = ui.Button(label="Venda Normal", style=discord.ButtonStyle.secondary, emoji=e_normal)
        btn_normal.callback = self.normal_sale
        self.add_item(btn_normal)
        
        btn_part = ui.Button(label="Parceria", style=discord.ButtonStyle.secondary, emoji=e_partnership)
        btn_part.callback = self.partnership_sale
        self.add_item(btn_part)

    async def _finish(self, interaction, is_partnership):
        # Salva no DB
        await self.bot.db.execute("""
            INSERT INTO sales (guild_id, seller_id, item, quantity, price, buyer, is_partnership, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (interaction.guild.id, interaction.user.id, self.data['item'], self.data['qty'], self.data['price'], self.data['buyer'], 1 if is_partnership else 0, datetime.datetime.now()))
        await self.bot.db.commit()
        
        # Log
        async with self.bot.db.execute("SELECT sales_log_channel_id FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            res = await cursor.fetchone()
            
        if res and res[0]:
            channel = interaction.guild.get_channel(res[0])
            if channel:
                unit_price = self.data['price'] / self.data['qty'] if self.data['qty'] > 0 else 0
                type_str = "🤝 Parceria" if is_partnership else "💵 Normal"
                color = 0x3498db if is_partnership else 0x2ecc71
                
                embed = discord.Embed(title="💰 Nova Venda Registrada", color=color)
                embed.add_field(name="Vendedor", value=interaction.user.mention, inline=True)
                embed.add_field(name="Comprador", value=self.data['buyer'], inline=True)
                embed.add_field(name="Tipo", value=type_str, inline=True)
                
                embed.add_field(name="Item", value=self.data['item'], inline=True)
                embed.add_field(name="Quantidade", value=f"{self.data['qty']}", inline=True)
                embed.add_field(name="Valor Total", value=f"$ {self.data['price']:,}", inline=True)
                
                embed.set_footer(text=f"Valor Unitário: $ {unit_price:.2f}")
                embed.timestamp = datetime.datetime.now()
                
                # Customizações: Avatar e UltraWide
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
                embed.set_image(url=INVISIBLE_WIDE_URL)
                
                await channel.send(embed=embed)

        await interaction.response.edit_message(content="✅ Venda registrada com sucesso!", view=None)

    # Callbacks bindados na criação do botão
    async def normal_sale(self, interaction: discord.Interaction):
        await self._finish(interaction, False)

    async def partnership_sale(self, interaction: discord.Interaction):
        await self._finish(interaction, True)



async def setup(bot):
    await bot.add_cog(Sales(bot))
