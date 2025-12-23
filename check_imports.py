import os
import importlib
import traceback
import sys

# Adiciona o diretório atual ao path para permitir imports
sys.path.append(os.getcwd())

print("[DEBUG] Verificando imports dos Cogs...")

cogs_dir = 'cogs'
if not os.path.exists(cogs_dir):
    print("[ERRO] Diretorio 'cogs' nao encontrado.")
    sys.exit(1)

for filename in os.listdir(cogs_dir):
    if filename.endswith('.py'):
        module_name = f"{cogs_dir}.{filename[:-3]}"
        try:
            importlib.import_module(module_name)
            print(f"[OK] {filename}: Importado com sucesso.")
        except Exception:
            print(f"[FALHA] {filename}: FALHA AO IMPORTAR.")
            traceback.print_exc()
            print("-" * 30)

print("[FIM] Verificacao concluida.")
