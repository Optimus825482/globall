import asyncio
import asyncpg

async def check():
    conn = await asyncpg.connect("postgresql://postgres:518518Erkan@localhost:5432/scalper_global")
    cols = await conn.fetch("""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = 'historical_candles'
        ORDER BY ordinal_position
    """)
    print("Columns in historical_candles:")
    for c in cols:
        print(f" - {c['column_name']}: {c['data_type']}")
        
    cnt = await conn.fetchval("SELECT count(*) FROM historical_candles")
    print("Total rows in historical_candles:", cnt)
    
    if cnt > 0:
        sample = await conn.fetch("SELECT * FROM historical_candles LIMIT 3")
        for s in sample:
            print(dict(s))
            
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check())
