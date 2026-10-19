import aiosqlite

DB_PATH = "azs_bot.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                osm_id TEXT UNIQUE,
                name TEXT,
                lat REAL,
                lon REAL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id INTEGER,
                status TEXT,
                user_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (station_id) REFERENCES stations(id)
            )
        """)
        await db.commit()

async def save_station(osm_id, name, lat, lon):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO stations (osm_id, name, lat, lon) VALUES (?, ?, ?, ?)",
            (osm_id, name, lat, lon)
        )
        await db.commit()
        cursor = await db.execute("SELECT id FROM stations WHERE osm_id = ?", (osm_id,))
        row = await cursor.fetchone()
        return row[0] if row else None

async def save_report(station_id, status, user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reports (station_id, status, user_id) VALUES (?, ?, ?)",
            (station_id, status, user_id)
        )
        await db.commit()

async def get_latest_status(station_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT status, created_at FROM reports WHERE station_id = ? ORDER BY created_at DESC LIMIT 1",
            (station_id,)
        )
        return await cursor.fetchone()
