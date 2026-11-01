import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect("postgresql://postgres:518518Erkan@localhost:5432/scalper_global")
    rows = await conn.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
    print("Tables in scalper_global:")
    for r in rows:
        print(" -", r["table_name"])
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
