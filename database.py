import aiosqlite

async def init_db():
    async with aiosqlite.connect('rhymes.db') as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS rhymes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT NOT NULL,
                rhyme TEXT NOT NULL
            )
        ''')
        await db.commit()
