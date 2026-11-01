import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect("postgresql://postgres:518518Erkan@localhost:5432/scalper_global")
    indices = await conn.fetch("""
        SELECT indexname, indexdef 
        FROM pg_indexes 
        WHERE tablename = 'historical_candles'
    """)
    for idx in indices:
        print(f"Index: {idx['indexname']}\n  {idx['indexdef']}")
        
    symbols = await conn.fetch("SELECT symbol, timeframe, count(*), min(open_time), max(open_time) FROM historical_candles GROUP BY symbol, timeframe ORDER BY symbol, timeframe")
    print(f"\nExisting symbol & timeframe breakdown ({len(symbols)} pairs):")
    for s in symbols[:20]:
        print(f" - {s['symbol']} {s['timeframe']}: {s['count']} rows")
    if len(symbols) > 20:
        print(f" ... ve {len(symbols)-20} diger cift.")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
