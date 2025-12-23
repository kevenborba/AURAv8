import sys
import traceback
import os

# Adiciona o diretório atual ao path para permitir imports
sys.path.append(os.getcwd())

print("[diag] Diagnostico de Cogs Iniciado...")
print(f"[file] Diretorio Atual: {os.getcwd()}")

target_cog = "cogs.faction_actions"

try:
    print(f"[wait] Tentando importar {target_cog}...")
    __import__(target_cog)
    print(f"[ok] SUCESSO! O modulo '{target_cog}' nao tem erros de sintaxe.")
except Exception as e:
    print(f"[erro] ERRO CRITICO ao importar '{target_cog}':")
    print("-" * 40)
    traceback.print_exc()
    print("-" * 40)
    print("DESCRICAO DO ERRO:", e)

# input("\nPresione ENTER para fechar...") # Removido para nao travar automacao
