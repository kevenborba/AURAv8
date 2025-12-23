import discord
from discord import app_commands
from discord.ext import commands
import random
import string
import io
from PIL import Image, ImageDraw, ImageFont
import asyncio
import os
import matplotlib.font_manager as fm # ✅ Solução "Fora da Caixa": Usar fontes do Matplotlib (já instalado)

class VerificationChallengeView(discord.ui.View):
    def __init__(self, correct_code, role, user_id):
        super().__init__(timeout=120)
        self.correct_code = correct_code
        self.role = role
        self.user_id = user_id
        self.add_item(VerificationDropdown(correct_code))

class VerificationDropdown(discord.ui.Select):
    def __init__(self, correct_code):
        options = []
        codes = [correct_code]
        while len(codes) < 5:
            fake = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            if fake not in codes:
                codes.append(fake)
        
        random.shuffle(codes)
        
        for code in codes:
            options.append(discord.SelectOption(label=code, value=code))

        super().__init__(placeholder="Selecione o código da imagem...", min_values=1, max_values=1, options=options)
        self.correct_code = correct_code

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == self.correct_code:
            view = self.view
            guild = interaction.guild
            member = guild.get_member(view.user_id)
            
            if member:
                try:
                    await member.add_roles(view.role, reason="Verificação concluída via CAPTCHA")
                    await interaction.response.send_message(f"✅ Verificado com sucesso! O cargo {view.role.mention} foi adicionado.", ephemeral=True)
                except discord.Forbidden:
                    await interaction.response.send_message("❌ Erro: Não tenho permissão para adicionar esse cargo.", ephemeral=True)
                except Exception as e:
                    await interaction.response.send_message(f"❌ Erro desconhecido: {e}", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Erro: Usuário não encontrado.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Código incorreto. Tente novamente clicando no botão de verificação.", ephemeral=True)

class VerificationStartView(discord.ui.View):
    def __init__(self, bot, emoji=None):
        super().__init__(timeout=None)
        self.bot = bot
        if emoji:
            self.verify_button.emoji = emoji

    def get_font(self, size):
        """
        Anti-Falha V3: Usa o gerenciador de fontes do Matplotlib.
        Como o matplotlib está no requirements.txt, ele SEMPRE terá fontes disponíveis.
        """
        try:
            # Pede pro Matplotlib achar uma fonte Sans-Serif (sem serifa) e Negrito (Bold)
            # Ele vai varrer o sistema e as próprias fontes internas dele e retornar um CAMINHO VÁLIDO.
            font_path = fm.findfont(fm.FontProperties(family='sans-serif', weight='bold'))
            print(f"[Verification] Matplotlib resolveu a fonte: {font_path}")
            
            return ImageFont.truetype(font_path, size)
        except Exception as e:
            print(f"[Verification] Erro crítico no Matplotlib font manager: {e}")
            # Se até o matplotlib falhar (impossível), usa o padrão
            return ImageFont.load_default()

    @discord.ui.button(label="Iniciar Verificação", style=discord.ButtonStyle.secondary, custom_id="verification:start_button", emoji="🛡️")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Fetch role_id from DB
        async with self.bot.db.execute("SELECT verification_role_id FROM config WHERE guild_id = ?", (interaction.guild.id,)) as cursor:
            res = await cursor.fetchone()
        
        if not res or not res[0]:
            await interaction.response.send_message("❌ O sistema de verificação não está configurado corretamente (Cargo não definido).", ephemeral=True)
            return

        role_id = res[0]
        role = interaction.guild.get_role(role_id)
        
        if not role:
             await interaction.response.send_message("❌ Erro: O cargo de verificação configurado não existe mais.", ephemeral=True)
             return

        if role in interaction.user.roles:
            await interaction.response.send_message("✅ Você já está verificado!", ephemeral=True)
            return

        # Generate code
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        
        # Generate Image (Larger 5x)
        img = Image.new('RGB', (2000, 1000), color=(0, 0, 0))
        d = ImageDraw.Draw(img)
        
        # Carrega Fonte via Matplotlib
        font = self.get_font(600)

        # Center text roughly
        bbox = d.textbbox((0, 0), code, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        
        d.text(((2000-w)/2, (1000-h)/2), code, fill=(255, 255, 255), font=font)

        # Noise (More points for larger image)
        for _ in range(1000):
            x = random.randint(0, 2000)
            y = random.randint(0, 1000)
            d.point((x, y), fill=(200, 200, 200))

        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        file = discord.File(buf, filename="captcha.png")

        view = VerificationChallengeView(code, role, interaction.user.id)
        await interaction.response.send_message("Selecione o código que aparece na imagem abaixo:", file=file, view=view, ephemeral=True)

class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(VerificationStartView(self.bot))

    @app_commands.command(name="setup_verificacao", description="Envia o painel de verificação")
    @app_commands.describe(role="O cargo que será dado após a verificação", emoji="Emoji personalizado para o botão (Opcional)")
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_verificacao(self, interaction: discord.Interaction, role: discord.Role, emoji: str = None):
        # Save role to DB
        await self.bot.db.execute("UPDATE config SET verification_role_id = ?, verification_emoji = ? WHERE guild_id = ?", (role.id, emoji, interaction.guild.id))
        await self.bot.db.commit()

        embed = discord.Embed(
            title="🛡️ Verificação Obrigatória",
            description="Para ter acesso aos canais do servidor, você precisa passar por uma verificação rápida.\n\nClique no botão abaixo e selecione o código correto.",
            color=0x000000
        )
        embed.set_footer(text="Sistema de Segurança")
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
        
        view = VerificationStartView(self.bot, emoji=emoji)
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("✅ Painel de verificação enviado e configurado!", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Verification(bot))
