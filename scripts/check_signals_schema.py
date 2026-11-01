import asyncio, asyncpg
async def run():
    conn = await asyncpg.connect('postgresql://postgres:518518Erkan@localhost:5432/scalper_global')
    cols = await conn.fetch("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'spot_monitor_signals'
    """)
    for c in cols:
        print(f"{c['column_name']}: {c['data_type']}")
    await conn.close()
asyncio.run(run())
