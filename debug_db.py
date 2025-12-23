import aiosqlite
import asyncio
import os
import json

DB_NAME = "database/bot_data.db"
TARGET_GUILD = 1399529747393941716

async def check_db():
    async with aiosqlite.connect(DB_NAME) as db:
        print(f"[OK] Checking Guild {TARGET_GUILD}")
        
        async with db.execute("SELECT participants, status, mvp_id FROM faction_actions WHERE guild_id = ?", (TARGET_GUILD,)) as cursor:
            rows = await cursor.fetchall()
            print(f"[INFO] Rows found: {len(rows)}")
            for i, r in enumerate(rows):
                if i >= 5: break
                print(f"  Row {i}: Status={r[1]}, MVP={r[2]}")
                print(f"       Participants: {r[0]}")

if __name__ == "__main__":
    asyncio.run(check_db())
