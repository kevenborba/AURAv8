import discord
from discord.ext import commands
from discord import app_commands, ui
import json
import aiohttp
import asyncio
from utils.license_manager import check_license

class EmbedCreator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(EmbedLauncherView(self.bot))

    @app_commands.command(name="painel_embeds", description="Posta o painel de inicialização do Mensageiro.")
    @app_commands.checks.has_permissions(administrator=True)
    @check_license()
    async def panel(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🎨 Gerenciador de Mensagens", color=0x2b2d31)
        embed.description = "Utilize os botões abaixo para criar ou gerenciar seus anúncios.\n\n📝 **Criar Novo**: Abre o editor em branco.\n📂 **Meus Templates**: Carrega um modelo salvo.\n❓ **Ajuda**: Como usar o sistema."
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.set_image(url="https://media.discordapp.net/attachments/1111111111111111111/1111111111111111111/banner_placeholder.png") # Placeholder
        
        await interaction.channel.send(embed=embed, view=EmbedLauncherView(self.bot))
        await interaction.response.send_message("✅ Painel postado!", ephemeral=True)

    @app_commands.command(name="mensageiro", description="Crie, edite e envie embeds profissionais com botões e webhooks.")
    @app_commands.checks.has_permissions(administrator=True)
    @check_license()
    async def messager(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        # Estado Inicial Vazio
        initial_state = {
            "title": "Título do Embed",
            "description": "Edite este texto...",
            "color": 0x2b2d31,
            "fields": [],
            "footer_text": None,
            "footer_icon": None,
            "author_name": None,
            "author_icon": None,
            "thumbnail": None,
            "image": None,
            "buttons": [] # [{label, url, emoji, style}]
        }
        view = EmbedBuilderView(self.bot, interaction, initial_state)
        await interaction.followup.send(embed=view.build_embed(), view=view, ephemeral=True)

class EmbedBuilderView(ui.View):
    def __init__(self, bot, origin, state):
        super().__init__(timeout=None)
        self.bot = bot
        self.origin = origin
        self.state = state
        self.msg_ref = None # Referencia para atualizar a mensagem do editor

    def build_embed(self):
        e = discord.Embed(
            title=self.state.get("title"),
            description=self.state.get("description"),
            color=self.state.get("color") or 0x2b2d31
        )
        if self.state.get("footer_text"):
            e.set_footer(text=self.state["footer_text"], icon_url=self.state.get("footer_icon"))
        if self.state.get("author_name"):
            e.set_author(name=self.state["author_name"], icon_url=self.state.get("author_icon"))
        if self.state.get("thumbnail"):
            e.set_thumbnail(url=self.state["thumbnail"])
        if self.state.get("image"):
            e.set_image(url=self.state["image"])
        
        for f in self.state["fields"]:
            e.add_field(name=f["name"], value=f["value"], inline=f["inline"])
            
        return e

    async def update_view(self, interaction: discord.Interaction):
        try:
            embed = self.build_embed()
            # Mostra preview dos botões (fake) no footer ou description se houver
            if self.state["buttons"]:
                desc_add = "\n\n**🔘 Botões Configurados:**\n"
                for b in self.state["buttons"]:
                    desc_add += f"[`{b['label']}`]({b['url']}) "
                embed.description += desc_add
                
            if interaction.response.is_done():
                await interaction.edit_original_response(embed=embed, view=self)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro visual: {e}", ephemeral=True)

    # === LINHA 1: BÁSICOS ===
    @ui.button(label="Principal", emoji="📝", style=discord.ButtonStyle.secondary, row=0)
    async def edit_main(self, i, b):
        await i.response.send_modal(MainInfoModal(self))

    @ui.button(label="Autor", emoji="👤", style=discord.ButtonStyle.secondary, row=0)
    async def edit_author(self, i, b):
        await i.response.send_modal(AuthorModal(self))
        
    @ui.button(label="Footer", emoji="🔻", style=discord.ButtonStyle.secondary, row=0)
    async def edit_footer(self, i, b):
        await i.response.send_modal(FooterModal(self))

    @ui.button(label="Imagens", emoji="🖼️", style=discord.ButtonStyle.secondary, row=0)
    async def edit_images(self, i, b):
        allow_upload = True # Feature Flag
        view = ImageSelectView(self, allow_upload)
        await i.response.send_message("🖼️ **Gerenciar Imagens**\nEscolha como deseja adicionar:", view=view, ephemeral=True)

    # === LINHA 2: CONTEÚDO ===
    @ui.button(label="Fields", emoji="📑", style=discord.ButtonStyle.secondary, row=1)
    async def edit_fields(self, i, b):
        view = FieldManagerView(self)
        await i.response.send_message("📑 **Gerenciar Fields**", view=view, ephemeral=True)

    @ui.button(label="Botões/Links", emoji="🔗", style=discord.ButtonStyle.secondary, row=1)
    async def edit_buttons_links(self, i, b):
        view = ButtonManagerView(self)
        await i.response.send_message("🔗 **Gerenciar Botões de Link**", view=view, ephemeral=True)

    @ui.button(label="Importar JSON", emoji="📥", style=discord.ButtonStyle.secondary, row=1)
    async def import_json(self, i, b):
        await i.response.send_modal(JSONImportModal(self))

    # === LINHA 3: AÇÕES ===
    @ui.button(label="Salvar Template", emoji="💾", style=discord.ButtonStyle.success, row=2)
    async def save_template(self, i, b):
        await i.response.send_modal(SaveTemplateModal(self))

    @ui.button(label="Carregar", emoji="📂", style=discord.ButtonStyle.primary, row=2)
    async def load_template(self, i, b):
        async with self.bot.db.execute("SELECT name, data FROM embed_templates WHERE guild_id = ?", (i.guild.id,)) as c:
            temps = await c.fetchall()
        if not temps: return await i.response.send_message("❌ Nenhum template salvo.", ephemeral=True)
        await i.response.send_message("📂 **Selecione um Template:**", view=TemplateLoadView(self, temps), ephemeral=True)

    @ui.button(label="ENVIAR MENSAGEM", emoji="🚀", style=discord.ButtonStyle.danger, row=2)
    async def send_menu(self, i, b):
        view = SendOptionsView(self)
        await i.response.send_message("🚀 **Opções de Envio**", view=view, ephemeral=True)

# ================= MODALS DE EDIÇÃO =================

class MainInfoModal(ui.Modal, title="Informações Principais"):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        s = parent.state
        self.t_title = ui.TextInput(label="Título", default=s.get("title"), required=False)
        self.t_desc = ui.TextInput(label="Descrição", style=discord.TextStyle.paragraph, default=s.get("description"), required=False)
        self.t_color = ui.TextInput(label="Cor HEX (Ex: #FF0000)", default=f"#{s.get('color', 0):06X}", min_length=7, max_length=7, required=False)
        self.add_item(self.t_title); self.add_item(self.t_desc); self.add_item(self.t_color)
    async def on_submit(self, i):
        self.parent.state["title"] = self.t_title.value
        self.parent.state["description"] = self.t_desc.value
        try: self.parent.state["color"] = int(self.t_color.value.replace("#",""), 16)
        except: pass
        await self.parent.update_view(i)

class AuthorModal(ui.Modal, title="Configurar Autor"):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        s = parent.state
        self.t_name = ui.TextInput(label="Nome do Autor", default=s.get("author_name"), required=False)
        self.t_icon = ui.TextInput(label="URL do Ícone", default=s.get("author_icon"), required=False)
        self.add_item(self.t_name); self.add_item(self.t_icon)
    async def on_submit(self, i):
        self.parent.state["author_name"] = self.t_name.value
        self.parent.state["author_icon"] = self.t_icon.value
        await self.parent.update_view(i)

class FooterModal(ui.Modal, title="Configurar Rodapé"):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        s = parent.state
        self.t_text = ui.TextInput(label="Texto do Rodapé", default=s.get("footer_text"), required=False)
        self.t_icon = ui.TextInput(label="URL do Ícone", default=s.get("footer_icon"), required=False)
        self.add_item(self.t_text); self.add_item(self.t_icon)
    async def on_submit(self, i):
        self.parent.state["footer_text"] = self.t_text.value
        self.parent.state["footer_icon"] = self.t_icon.value
        await self.parent.update_view(i)

class ManualImageModal(ui.Modal, title="URLs de Imagem"):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        s = parent.state
        self.t_thumb = ui.TextInput(label="Thumbnail (Pequena)", default=s.get("thumbnail"), required=False)
        self.t_image = ui.TextInput(label="Imagem (Grande)", default=s.get("image"), required=False)
        self.add_item(self.t_thumb); self.add_item(self.t_image)
    async def on_submit(self, i):
        self.parent.state["thumbnail"] = self.t_thumb.value
        self.parent.state["image"] = self.t_image.value
        await self.parent.update_view(i)

class JSONImportModal(ui.Modal, title="Importar JSON"):
    json_data = ui.TextInput(label="Cole o JSON aqui", style=discord.TextStyle.paragraph)
    def __init__(self, parent): super().__init__(); self.parent = parent
    async def on_submit(self, i):
        try:
            data = json.loads(self.json_data.value)
            # Tratamento básico para compatibilidade com Discohook/Embeds
            if "embeds" in data and len(data["embeds"]) > 0: e = data["embeds"][0]
            else: e = data
            
            self.parent.state["title"] = e.get("title")
            self.parent.state["description"] = e.get("description")
            self.parent.state["color"] = e.get("color", 0x2b2d31)
            self.parent.state["fields"] = e.get("fields", [])
            if "footer" in e: 
                self.parent.state["footer_text"] = e["footer"].get("text")
                self.parent.state["footer_icon"] = e["footer"].get("icon_url")
            if "author" in e:
                self.parent.state["author_name"] = e["author"].get("name")
                self.parent.state["author_icon"] = e["author"].get("icon_url")
            if "image" in e: self.parent.state["image"] = e["image"].get("url")
            if "thumbnail" in e: self.parent.state["thumbnail"] = e["thumbnail"].get("url")
            
            await self.parent.update_view(i)
        except Exception as e: await i.response.send_message(f"❌ JSON Inválido: {e}", ephemeral=True)

class SaveTemplateModal(ui.Modal, title="Salvar Template"):
    name = ui.TextInput(label="Nome do Template", placeholder="Ex: AnuncioPromo")
    def __init__(self, parent): super().__init__(); self.parent = parent
    async def on_submit(self, i):
        dump = json.dumps(self.parent.state)
        await self.parent.bot.db.execute("INSERT OR REPLACE INTO embed_templates (name, data, guild_id) VALUES (?, ?, ?)", (self.name.value, dump, i.guild.id))
        await self.parent.bot.db.commit()
        await i.response.send_message(f"✅ Template `{self.name.value}` salvo!", ephemeral=True)

class AddFieldModal(ui.Modal, title="Adicionar Field"):
    def __init__(self, parent): super().__init__(); self.parent = parent
    name = ui.TextInput(label="Nome / Título")
    val = ui.TextInput(label="Valor / Texto", style=discord.TextStyle.paragraph)
    inline = ui.TextInput(label="Inline? (s/n)", default="n", max_length=1)
    async def on_submit(self, i):
        self.parent.state["fields"].append({
            "name": self.name.value,
            "value": self.val.value,
            "inline": self.inline.value.lower() == 's'
        })
        await self.parent.update_view(i)

class AddButtonModal(ui.Modal, title="Adicionar Botão"):
    def __init__(self, parent): super().__init__(); self.parent = parent
    label = ui.TextInput(label="Texto do Botão")
    url = ui.TextInput(label="URL de Destino")
    emoji = ui.TextInput(label="Emoji (Opcional)", required=False)
    async def on_submit(self, i):
        if not self.url.value.startswith("http"): return await i.response.send_message("❌ URL inválida.", ephemeral=True)
        self.parent.state["buttons"].append({
            "label": self.label.value,
            "url": self.url.value,
            "emoji": self.emoji.value if self.emoji.value else None,
            "style": 5 # Link Style
        })
        await self.parent.update_view(i)

# ================= VIEWS SECUNDÁRIAS =================

class ImageSelectView(ui.View):
    def __init__(self, parent, allow_upload): super().__init__(timeout=60); self.parent = parent; self.allow_upload = allow_upload
    
    @ui.button(label="Inserir Links", style=discord.ButtonStyle.secondary)
    async def link_mode(self, i, b): await i.response.send_modal(ManualImageModal(self.parent))
    
    @ui.button(label="Fazer Upload", style=discord.ButtonStyle.primary, emoji="📤")
    async def upload_mode(self, i, b):
        if not self.allow_upload: return await i.response.send_message("Upload desativado.", ephemeral=True)
        await i.response.send_message("📸 **Envie a imagem agora no chat!**\n(Você tem 30 segundos)", ephemeral=True)
        
        def check(m): return m.author.id == i.user.id and m.channel.id == i.channel.id and m.attachments
        
        try:
            msg = await self.parent.bot.wait_for('message', timeout=30.0, check=check)
            url = msg.attachments[0].url
            # Pergunta se é Thumbnail ou Imagem Principal
            await msg.delete()
            view = ImageTypSelectView(self.parent, url)
            await i.followup.send("A imagem deve ser usada como?", view=view, ephemeral=True)
        except asyncio.TimeoutError:
            await i.followup.send("❌ Tempo esgotado.", ephemeral=True)

class ImageTypSelectView(ui.View):
    def __init__(self, parent, url): super().__init__(timeout=60); self.parent = parent; self.url = url
    @ui.button(label="Thumbnail (Pequena)", style=discord.ButtonStyle.secondary)
    async def set_thumb(self, i, b): self.parent.state["thumbnail"] = self.url; await self.parent.update_view(i)
    @ui.button(label="Imagem (Grande)", style=discord.ButtonStyle.secondary)
    async def set_image(self, i, b): self.parent.state["image"] = self.url; await self.parent.update_view(i)

class FieldManagerView(ui.View):
    def __init__(self, parent): super().__init__(timeout=60); self.parent = parent
    @ui.button(label="Adicionar Field", style=discord.ButtonStyle.success)
    async def add_f(self, i, b): await i.response.send_modal(AddFieldModal(self.parent))
    @ui.button(label="Limpar Todos", style=discord.ButtonStyle.danger)
    async def clr_f(self, i, b): self.parent.state["fields"] = []; await self.parent.update_view(i)
    @ui.button(label="Remover Último", style=discord.ButtonStyle.secondary)
    async def rem_f(self, i, b): 
        if self.parent.state["fields"]: self.parent.state["fields"].pop(); await self.parent.update_view(i)
        else: await i.response.send_message("Nada para remover.", ephemeral=True)

class ButtonManagerView(ui.View):
    def __init__(self, parent): super().__init__(timeout=60); self.parent = parent
    @ui.button(label="Adicionar Botão Link", style=discord.ButtonStyle.success)
    async def add_b(self, i, b): await i.response.send_modal(AddButtonModal(self.parent))
    @ui.button(label="Limpar Botões", style=discord.ButtonStyle.danger)
    async def clr_b(self, i, b): self.parent.state["buttons"] = []; await self.parent.update_view(i)

class TemplateLoadView(ui.View):
    def __init__(self, parent, templates):
        super().__init__(timeout=60); self.parent = parent
        options = [discord.SelectOption(label=t[0], value=t[1]) for t in templates]
        self.sel = ui.Select(placeholder="Escolha um template...", options=options)
        self.sel.callback = self.cb
        self.add_item(self.sel)
    async def cb(self, i):
        try:
            data = json.loads(self.sel.values[0])
            self.parent.state = data
            await self.parent.update_view(i)
        except: await i.response.send_message("❌ Erro ao carregar template.", ephemeral=True)

class SendOptionsView(ui.View):
    def __init__(self, parent): super().__init__(timeout=60); self.parent = parent
    
    @ui.select(cls=discord.ui.ChannelSelect, placeholder="Selecionar Canal...", channel_types=[discord.ChannelType.text, discord.ChannelType.news])
    async def sel_channel(self, i, select):
        self.channel = select.values[0]
        await i.response.defer()
    
    @ui.button(label="Enviar Normal", style=discord.ButtonStyle.primary)
    async def send_normal(self, i, b):
        if not hasattr(self, 'channel'): return await i.response.send_message("❌ Selecione um canal acima primeiro!", ephemeral=True)
        await i.response.defer(ephemeral=True)
        await self.do_send(i, self.channel, mode="bot")
        
    @ui.button(label="Enviar como Webhook (Premium)", style=discord.ButtonStyle.success, emoji="🤖")
    async def send_webhook(self, i, b):
        if not hasattr(self, 'channel'): return await i.response.send_message("❌ Selecione um canal acima primeiro!", ephemeral=True)
        await i.response.send_modal(WebhookConfigModal(self.parent, self.channel))

    async def do_send(self, interaction, channel, mode="bot", wh_name=None, wh_avatar=None):
        embed = self.parent.build_embed()
        view = None
        
        # Resolve o canal para garantir que temos um objeto com método send
        real_channel = self.parent.bot.get_channel(channel.id)
        if not real_channel:
            try:
                real_channel = await self.parent.bot.fetch_channel(channel.id)
            except:
                return await interaction.followup.send("❌ Canal não encontrado ou sem permissão.", ephemeral=True)
        
        # Constrói View de Botões Reais
        if self.parent.state["buttons"]:
            view = ui.View(timeout=None)
            for btn_data in self.parent.state["buttons"]:
                view.add_item(ui.Button(label=btn_data["label"], url=btn_data["url"], emoji=btn_data["emoji"], style=discord.ButtonStyle.link))
        
        try:
            if mode == "bot":
                await real_channel.send(embed=embed, view=view)
                await interaction.followup.send(f"✅ Enviado em {real_channel.mention}!")
            else:
                # Webhook Mode
                wh = await real_channel.create_webhook(name=wh_name or "Mensageiro")
                kwargs = {
                    "username": wh_name,
                    "avatar_url": wh_avatar,
                    "embed": embed
                }
                if view:
                    kwargs["view"] = view
                    
                await wh.send(**kwargs)
                await wh.delete() # Limpa o webhook depois
                await interaction.followup.send(f"✅ Webhook enviado em {real_channel.mention}!")
        except Exception as e:
            await interaction.followup.send(f"❌ Erro ao enviar: {e}", ephemeral=True)

class WebhookConfigModal(ui.Modal, title="Configurar Webhook"):
    def __init__(self, parent, channel): super().__init__(); self.parent = parent; self.channel = channel
    name = ui.TextInput(label="Nome do Webhook", default="Aviso Importante")
    avatar = ui.TextInput(label="URL do Avatar (Opcional)", required=False)
    async def on_submit(self, i):
        await i.response.defer(ephemeral=True)
        # Gambiarra para chamar o do_send da View anterior não é ideal, mas...
        # Vamos instanciar um sender helper ou mover logica
        sender = SendOptionsView(self.parent)
        await sender.do_send(i, self.channel, mode="webhook", wh_name=self.name.value, wh_avatar=self.avatar.value)

class EmbedLauncherView(ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @ui.button(label="Criar Novo", style=discord.ButtonStyle.success, emoji="📝", custom_id="embed_launcher_new")
    async def new_embed(self, i, b):
        initial_state = {
            "title": "Título do Embed",
            "description": "Edite este texto...",
            "color": 0x2b2d31,
            "fields": [],
            "footer_text": None,
            "footer_icon": None,
            "author_name": None,
            "author_icon": None,
            "thumbnail": None,
            "image": None,
            "buttons": []
        }
        view = EmbedBuilderView(self.bot, i, initial_state)
        await i.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)

    @ui.button(label="Meus Templates", style=discord.ButtonStyle.primary, emoji="📂", custom_id="embed_launcher_load")
    async def load_embed(self, i, b):
        async with self.bot.db.execute("SELECT name, data FROM embed_templates WHERE guild_id = ?", (i.guild.id,)) as c:
            temps = await c.fetchall()
        
        if not temps: return await i.response.send_message("❌ Nenhum template salvo.", ephemeral=True)
        
        # Gambiarra: Criamos um 'fake parent' pq o TemplateLoadView espera um EmbedBuilderView
        # Mas aqui queremos carregar direto. Vamos adaptar:
        # Ao carregar, instanciamos o Builder já com o state carregado.
        
        await i.response.send_message("📂 **Selecione um Template:**", view=LauncherTemplateLoadView(self.bot, temps), ephemeral=True)

    @ui.button(label="Ajuda", style=discord.ButtonStyle.secondary, emoji="❓", custom_id="embed_launcher_help")
    async def help_embed(self, i, b):
        msg = "**Como usar:**\n1. Clique em 'Criar Novo'.\n2. Use os botões para editar título, cor, imagem, etc.\n3. Salve como Template se quiser usar depois.\n4. Clique em 'ENVIAR' para postar no canal oficial."
        await i.response.send_message(msg, ephemeral=True)

class LauncherTemplateLoadView(ui.View):
    def __init__(self, bot, templates):
        super().__init__(timeout=60); self.bot = bot
        options = [discord.SelectOption(label=t[0], value=t[1]) for t in templates]
        self.sel = ui.Select(placeholder="Escolha um template...", options=options)
        self.sel.callback = self.cb
        self.add_item(self.sel)
    async def cb(self, i):
        try:
            data = json.loads(self.sel.values[0])
            view = EmbedBuilderView(self.bot, i, data)
            await i.response.send_message(embed=view.build_embed(), view=view, ephemeral=True)
        except: await i.response.send_message("❌ Erro ao carregar template.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(EmbedCreator(bot))
