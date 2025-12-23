import asyncio
from database.bot_db import create_db, get_db_connection

async def main():
    print("Updating Database Schema...")
    await create_db()
    
    print("Verifying Tables...")
    db = await get_db_connection()
    tables = ["licenses", "audit_logs", "global_bans"]
    all_ok = True
    
    for t in tables:
        async with db.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{t}'") as cursor:
            if await cursor.fetchone():
                print(f"Table '{t}' exists.")
            else:
                print(f"Table '{t}' NOT FOUND.")
                all_ok = False
                
    await db.close()
    
    if all_ok:
        print("\nDatabase update successful!")
    else:
        print("\nSome tables were not created.")

if __name__ == "__main__":
    asyncio.run(main())
