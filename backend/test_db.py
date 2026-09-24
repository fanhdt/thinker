import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect("postgresql://thinker:thinker@localhost:5432/thinker")
    print(await conn.fetchval("select 1"))
    await conn.close()

asyncio.run(main())