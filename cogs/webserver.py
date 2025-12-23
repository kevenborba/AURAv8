import discord
from discord.ext import commands
from aiohttp import web
import os
import asyncio

class WebServer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.site = None
        # Garante que a pasta existe para não dar erro ao iniciar o site
        if not os.path.exists('transcripts'):
            os.makedirs('transcripts')

    async def cog_load(self):
        """Inicia o servidor web assim que a Cog é carregada"""
        self.bot.loop.create_task(self.start_server())

    async def start_server(self):
        # DESATIVADO: O servidor web principal agora é gerido pelo Dashboard (Quart) em dashboard/app.py
        # Isso evita conflito de portas (Address already in use).
        # A funcionalidade de servir transcripts foi movida para lá.
        pass

        # app = web.Application()
        # app.router.add_static('/transcripts/', path='./transcripts', name='transcripts')
        # ... (restante comentado)

    async def handle_root(self, request):
        return web.Response(text="🤖 CityBot Transcript Server está Online!")

    async def cog_unload(self):
        """Desliga o site se o bot for desligado/reiniciado"""
        if self.site:
            await self.site.stop()

async def setup(bot):
    await bot.add_cog(WebServer(bot))