"""
Database module for Media Server Bot
Supports both SQLite (local) and PostgreSQL (Railway/Production)
"""

import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

# Check if we're using PostgreSQL (Railway) or SQLite (local)
DATABASE_URL = os.getenv("DATABASE_URL")  # Railway provides this automatically
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot_database.db")

USE_POSTGRES = DATABASE_URL is not None

if USE_POSTGRES:
    import psycopg2
    from psycopg2.extras import RealDictCursor
else:
    import sqlite3


@contextmanager
def get_connection():
    """Context manager for database connections"""
    if USE_POSTGRES:
        # Railway PostgreSQL
        conn = psycopg2.connect(DATABASE_URL)
        try:
            yield conn
        finally:
            conn.close()
    else:
        # Local SQLite
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


def get_cursor(conn):
    """Get appropriate cursor based on database type"""
    if USE_POSTGRES:
        return conn.cursor(cursor_factory=RealDictCursor)
    return conn.cursor()


def get_placeholder():
    """Return the correct placeholder for the database type"""
    return "%s" if USE_POSTGRES else "?"


def init_database():
    """Initialize the database with all required tables"""
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
        if USE_POSTGRES:
            # PostgreSQL syntax
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    discord_id BIGINT UNIQUE NOT NULL,
                    discord_username TEXT,
                    jellyfin_id TEXT,
                    jellyfin_username TEXT,
                    emby_id TEXT,
                    emby_username TEXT,
                    plex_id TEXT,
                    plex_username TEXT,
                    plex_email TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS watchtime (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    server_type TEXT NOT NULL,
                    watch_date DATE NOT NULL,
                    watch_seconds BIGINT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, server_type, watch_date)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    plan_type TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    payment_id TEXT,
                    amount REAL,
                    currency TEXT DEFAULT 'USD',
                    start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_date TIMESTAMP,
                    auto_renew BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS library_access (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    server_type TEXT NOT NULL,
                    library_name TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, server_type, library_name)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS invite_codes (
                    id SERIAL PRIMARY KEY,
                    code TEXT UNIQUE NOT NULL,
                    created_by INTEGER REFERENCES users(id),
                    used_by INTEGER REFERENCES users(id),
                    max_uses INTEGER DEFAULT 1,
                    current_uses INTEGER DEFAULT 0,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    action TEXT NOT NULL,
                    details TEXT,
                    ip_address TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # PostgreSQL indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchtime_user_date ON watchtime(user_id, watch_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)")
            
        else:
            # SQLite syntax
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    discord_id INTEGER UNIQUE NOT NULL,
                    discord_username TEXT,
                    jellyfin_id TEXT,
                    jellyfin_username TEXT,
                    emby_id TEXT,
                    emby_username TEXT,
                    plex_id TEXT,
                    plex_username TEXT,
                    plex_email TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS watchtime (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    server_type TEXT NOT NULL,
                    watch_date DATE NOT NULL,
                    watch_seconds INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(user_id, server_type, watch_date)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    plan_type TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    payment_id TEXT,
                    amount REAL,
                    currency TEXT DEFAULT 'USD',
                    start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_date TIMESTAMP,
                    auto_renew BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS library_access (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    server_type TEXT NOT NULL,
                    library_name TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    UNIQUE(user_id, server_type, library_name)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS invite_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    created_by INTEGER,
                    used_by INTEGER,
                    max_uses INTEGER DEFAULT 1,
                    current_uses INTEGER DEFAULT 0,
                    expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (created_by) REFERENCES users(id),
                    FOREIGN KEY (used_by) REFERENCES users(id)
                )
            """)
            
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    details TEXT,
                    ip_address TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id)
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_discord_id ON users(discord_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchtime_user_date ON watchtime(user_id, watch_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)")
        
        conn.commit()
        db_type = "PostgreSQL" if USE_POSTGRES else "SQLite"
        print(f"Database initialized successfully! (Using {db_type})")
        
        # Run migrations for existing databases
        if USE_POSTGRES:
            run_migrations(conn)


def run_migrations(conn):
    """Run database migrations for PostgreSQL"""
    cursor = get_cursor(conn)
    
    try:
        # Migration: Ensure discord_id is BIGINT (fixes NumericValueOutOfRange error)
        cursor.execute("""
            DO $$
            BEGIN
                -- Check if discord_id column is INTEGER and alter to BIGINT
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'users' 
                    AND column_name = 'discord_id' 
                    AND data_type = 'integer'
                ) THEN
                    ALTER TABLE users ALTER COLUMN discord_id TYPE BIGINT;
                    RAISE NOTICE 'Migrated discord_id to BIGINT';
                END IF;
            END $$;
        """)
        conn.commit()
        print("Database migrations completed.")
    except Exception as e:
        print(f"Migration warning: {e}")
        conn.rollback()


# ============== USER FUNCTIONS ==============

def get_user_by_discord_id(discord_id: int) -> Optional[Dict[str, Any]]:
    """Get user by Discord ID"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute(f"SELECT * FROM users WHERE discord_id = {ph}", (discord_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def create_user(discord_id: int, discord_username: str = None) -> int:
    """Create a new user and return their ID"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute(
                f"INSERT INTO users (discord_id, discord_username) VALUES ({ph}, {ph}) RETURNING id",
                (discord_id, discord_username)
            )
            result = cursor.fetchone()
            conn.commit()
            return result['id'] if isinstance(result, dict) else result[0]
        else:
            cursor.execute(
                f"INSERT INTO users (discord_id, discord_username) VALUES ({ph}, {ph})",
                (discord_id, discord_username)
            )
            conn.commit()
            return cursor.lastrowid


def get_or_create_user(discord_id: int, discord_username: str = None) -> Dict[str, Any]:
    """Get existing user or create new one"""
    user = get_user_by_discord_id(discord_id)
    if not user:
        user_id = create_user(discord_id, discord_username)
        user = {"id": user_id, "discord_id": discord_id, "discord_username": discord_username}
    return user


def link_jellyfin_account(discord_id: int, jellyfin_id: str, jellyfin_username: str) -> bool:
    """Link a Jellyfin account to a Discord user"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute(
            f"""UPDATE users 
               SET jellyfin_id = {ph}, jellyfin_username = {ph}, updated_at = CURRENT_TIMESTAMP 
               WHERE discord_id = {ph}""",
            (jellyfin_id, jellyfin_username, discord_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def link_emby_account(discord_id: int, emby_id: str, emby_username: str) -> bool:
    """Link an Emby account to a Discord user"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute(
            f"""UPDATE users 
               SET emby_id = {ph}, emby_username = {ph}, updated_at = CURRENT_TIMESTAMP 
               WHERE discord_id = {ph}""",
            (emby_id, emby_username, discord_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def link_plex_account(discord_id: int, plex_id: str, plex_username: str, plex_email: str = None) -> bool:
    """Link a Plex account to a Discord user"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute(
            f"""UPDATE users 
               SET plex_id = {ph}, plex_username = {ph}, plex_email = {ph}, updated_at = CURRENT_TIMESTAMP 
               WHERE discord_id = {ph}""",
            (plex_id, plex_username, plex_email, discord_id)
        )
        conn.commit()
        return cursor.rowcount > 0


def unlink_account(discord_id: int, server_type: str) -> bool:
    """Unlink a media server account"""
    ph = get_placeholder()
    field_map = {
        "jellyfin": ("jellyfin_id", "jellyfin_username"),
        "emby": ("emby_id", "emby_username"),
        "plex": ("plex_id", "plex_username", "plex_email")
    }
    
    if server_type not in field_map:
        return False
    
    fields = field_map[server_type]
    set_clause = ", ".join([f"{f} = NULL" for f in fields])
    
    with get_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute(
            f"UPDATE users SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE discord_id = {ph}",
            (discord_id,)
        )
        conn.commit()
        return cursor.rowcount > 0


# ============== WATCHTIME FUNCTIONS ==============

def add_watchtime(user_id: int, server_type: str, seconds: int, date: str = None) -> bool:
    """Add watchtime for a user"""
    ph = get_placeholder()
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    
    with get_connection() as conn:
        cursor = get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute(
                f"""INSERT INTO watchtime (user_id, server_type, watch_date, watch_seconds)
                   VALUES ({ph}, {ph}, {ph}, {ph})
                   ON CONFLICT(user_id, server_type, watch_date) 
                   DO UPDATE SET watch_seconds = watchtime.watch_seconds + {ph}""",
                (user_id, server_type, date, seconds, seconds)
            )
        else:
            cursor.execute(
                f"""INSERT INTO watchtime (user_id, server_type, watch_date, watch_seconds)
                   VALUES ({ph}, {ph}, {ph}, {ph})
                   ON CONFLICT(user_id, server_type, watch_date) 
                   DO UPDATE SET watch_seconds = watch_seconds + {ph}""",
                (user_id, server_type, date, seconds, seconds)
            )
        conn.commit()
        return cursor.rowcount > 0


def get_watchtime(user_id: int, server_type: str = None, days: int = 7) -> int:
    """Get total watchtime in seconds for the past N days"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
        if USE_POSTGRES:
            query = f"""
                SELECT COALESCE(SUM(watch_seconds), 0) as total
                FROM watchtime 
                WHERE user_id = {ph} 
                AND watch_date >= CURRENT_DATE - INTERVAL '{days} days'
            """
            params = [user_id]
        else:
            query = f"""
                SELECT COALESCE(SUM(watch_seconds), 0) as total
                FROM watchtime 
                WHERE user_id = {ph} 
                AND watch_date >= date('now', {ph})
            """
            params = [user_id, f'-{days} days']
        
        if server_type:
            query += f" AND server_type = {ph}"
            params.append(server_type)
        
        cursor.execute(query, params)
        result = cursor.fetchone()
        if result:
            return result['total'] if isinstance(result, dict) else result[0]
        return 0


def get_total_watchtime(user_id: int, server_type: str = None) -> int:
    """Get all-time total watchtime in seconds"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
        query = f"SELECT COALESCE(SUM(watch_seconds), 0) as total FROM watchtime WHERE user_id = {ph}"
        params = [user_id]
        
        if server_type:
            query += f" AND server_type = {ph}"
            params.append(server_type)
        
        cursor.execute(query, params)
        result = cursor.fetchone()
        if result:
            return result['total'] if isinstance(result, dict) else result[0]
        return 0


def get_watchtime_leaderboard(server_type: str = None, days: int = 7, limit: int = 10) -> List[Dict]:
    """Get watchtime leaderboard"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
        if USE_POSTGRES:
            query = f"""
                SELECT u.discord_id, u.discord_username, SUM(w.watch_seconds) as total_seconds
                FROM watchtime w
                JOIN users u ON w.user_id = u.id
                WHERE w.watch_date >= CURRENT_DATE - INTERVAL '{days} days'
            """
            params = []
        else:
            query = f"""
                SELECT u.discord_id, u.discord_username, SUM(w.watch_seconds) as total_seconds
                FROM watchtime w
                JOIN users u ON w.user_id = u.id
                WHERE w.watch_date >= date('now', {ph})
            """
            params = [f'-{days} days']
        
        if server_type:
            query += f" AND w.server_type = {ph}"
            params.append(server_type)
        
        query += f" GROUP BY u.id, u.discord_id, u.discord_username ORDER BY total_seconds DESC LIMIT {ph}"
        params.append(limit)
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


# ============== SUBSCRIPTION FUNCTIONS ==============

def create_subscription(user_id: int, plan_type: str, payment_id: str = None, 
                       amount: float = None, days: int = 30) -> int:
    """Create a new subscription"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute(
                f"""INSERT INTO subscriptions (user_id, plan_type, payment_id, amount, end_date)
                   VALUES ({ph}, {ph}, {ph}, {ph}, CURRENT_TIMESTAMP + INTERVAL '{days} days')
                   RETURNING id""",
                (user_id, plan_type, payment_id, amount)
            )
            result = cursor.fetchone()
            conn.commit()
            return result['id'] if isinstance(result, dict) else result[0]
        else:
            cursor.execute(
                f"""INSERT INTO subscriptions (user_id, plan_type, payment_id, amount, end_date)
                   VALUES ({ph}, {ph}, {ph}, {ph}, datetime('now', '+{days} days'))""",
                (user_id, plan_type, payment_id, amount)
            )
            conn.commit()
            return cursor.lastrowid


def get_active_subscription(user_id: int) -> Optional[Dict[str, Any]]:
    """Get active subscription for a user"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute(
                f"""SELECT * FROM subscriptions 
                   WHERE user_id = {ph} AND status = 'active' AND end_date > CURRENT_TIMESTAMP
                   ORDER BY end_date DESC LIMIT 1""",
                (user_id,)
            )
        else:
            cursor.execute(
                f"""SELECT * FROM subscriptions 
                   WHERE user_id = {ph} AND status = 'active' AND end_date > datetime('now')
                   ORDER BY end_date DESC LIMIT 1""",
                (user_id,)
            )
        row = cursor.fetchone()
        return dict(row) if row else None


def cancel_subscription(user_id: int) -> bool:
    """Cancel active subscription"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute(
            f"""UPDATE subscriptions 
               SET status = 'cancelled', auto_renew = FALSE, updated_at = CURRENT_TIMESTAMP
               WHERE user_id = {ph} AND status = 'active'""",
            (user_id,)
        )
        conn.commit()
        return cursor.rowcount > 0


def has_active_subscription(user_id: int) -> bool:
    """Check if user has active subscription"""
    return get_active_subscription(user_id) is not None


# ============== LIBRARY ACCESS FUNCTIONS ==============

def set_library_access(user_id: int, server_type: str, library_name: str, enabled: bool) -> bool:
    """Set library access for a user"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute(
                f"""INSERT INTO library_access (user_id, server_type, library_name, enabled)
                   VALUES ({ph}, {ph}, {ph}, {ph})
                   ON CONFLICT(user_id, server_type, library_name) 
                   DO UPDATE SET enabled = {ph}, updated_at = CURRENT_TIMESTAMP""",
                (user_id, server_type, library_name, enabled, enabled)
            )
        else:
            cursor.execute(
                f"""INSERT INTO library_access (user_id, server_type, library_name, enabled)
                   VALUES ({ph}, {ph}, {ph}, {ph})
                   ON CONFLICT(user_id, server_type, library_name) 
                   DO UPDATE SET enabled = {ph}, updated_at = CURRENT_TIMESTAMP""",
                (user_id, server_type, library_name, enabled, enabled)
            )
        conn.commit()
        return cursor.rowcount > 0


def get_library_access(user_id: int, server_type: str = None) -> List[Dict]:
    """Get library access settings for a user"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
        query = f"SELECT * FROM library_access WHERE user_id = {ph}"
        params = [user_id]
        
        if server_type:
            query += f" AND server_type = {ph}"
            params.append(server_type)
        
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def is_library_enabled(user_id: int, server_type: str, library_name: str) -> bool:
    """Check if a specific library is enabled for a user"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute(
            f"""SELECT enabled FROM library_access 
               WHERE user_id = {ph} AND server_type = {ph} AND library_name = {ph}""",
            (user_id, server_type, library_name)
        )
        row = cursor.fetchone()
        if row:
            val = row['enabled'] if isinstance(row, dict) else row[0]
            return bool(val)
        return False


# ============== INVITE CODE FUNCTIONS ==============

def create_invite_code(code: str, created_by: int = None, max_uses: int = 1, 
                       expires_days: int = 7) -> bool:
    """Create a new invite code"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        try:
            if USE_POSTGRES:
                cursor.execute(
                    f"""INSERT INTO invite_codes (code, created_by, max_uses, expires_at)
                       VALUES ({ph}, {ph}, {ph}, CURRENT_TIMESTAMP + INTERVAL '{expires_days} days')""",
                    (code, created_by, max_uses)
                )
            else:
                cursor.execute(
                    f"""INSERT INTO invite_codes (code, created_by, max_uses, expires_at)
                       VALUES ({ph}, {ph}, {ph}, datetime('now', '+{expires_days} days'))""",
                    (code, created_by, max_uses)
                )
            conn.commit()
            return True
        except Exception:
            return False


def use_invite_code(code: str, used_by: int) -> bool:
    """Use an invite code"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
        # Check if code is valid
        if USE_POSTGRES:
            cursor.execute(
                f"""SELECT * FROM invite_codes 
                   WHERE code = {ph} AND current_uses < max_uses 
                   AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)""",
                (code,)
            )
        else:
            cursor.execute(
                f"""SELECT * FROM invite_codes 
                   WHERE code = {ph} AND current_uses < max_uses 
                   AND (expires_at IS NULL OR expires_at > datetime('now'))""",
                (code,)
            )
        invite = cursor.fetchone()
        
        if not invite:
            return False
        
        # Update usage
        cursor.execute(
            f"""UPDATE invite_codes 
               SET current_uses = current_uses + 1, used_by = {ph}
               WHERE code = {ph}""",
            (used_by, code)
        )
        conn.commit()
        return True


def is_valid_invite_code(code: str) -> bool:
    """Check if an invite code is valid"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        if USE_POSTGRES:
            cursor.execute(
                f"""SELECT 1 FROM invite_codes 
                   WHERE code = {ph} AND current_uses < max_uses 
                   AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)""",
                (code,)
            )
        else:
            cursor.execute(
                f"""SELECT 1 FROM invite_codes 
                   WHERE code = {ph} AND current_uses < max_uses 
                   AND (expires_at IS NULL OR expires_at > datetime('now'))""",
                (code,)
            )
        return cursor.fetchone() is not None


# ============== AUDIT LOG FUNCTIONS ==============

def log_action(user_id: int, action: str, details: str = None, ip_address: str = None):
    """Log an action to the audit log"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute(
            f"INSERT INTO audit_log (user_id, action, details, ip_address) VALUES ({ph}, {ph}, {ph}, {ph})",
            (user_id, action, details, ip_address)
        )
        conn.commit()


def get_audit_log(user_id: int = None, limit: int = 100) -> List[Dict]:
    """Get audit log entries"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
        if user_id:
            cursor.execute(
                f"SELECT * FROM audit_log WHERE user_id = {ph} ORDER BY created_at DESC LIMIT {ph}",
                (user_id, limit)
            )
        else:
            cursor.execute(
                f"SELECT * FROM audit_log ORDER BY created_at DESC LIMIT {ph}",
                (limit,)
            )
        
        return [dict(row) for row in cursor.fetchall()]


# ============== UTILITY FUNCTIONS ==============

def seconds_to_hours(seconds: int) -> float:
    """Convert seconds to hours"""
    return round(seconds / 3600, 2)


def get_all_users() -> List[Dict]:
    """Get all users"""
    with get_connection() as conn:
        cursor = get_cursor(conn)
        cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def get_users_at_risk(threshold_hours: int = 168, days: int = 30) -> List[Dict]:
    """Get users who are at risk of purge (below watchtime threshold)"""
    ph = get_placeholder()
    threshold_seconds = threshold_hours * 3600
    
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
        if USE_POSTGRES:
            cursor.execute(
                f"""SELECT u.*, COALESCE(SUM(w.watch_seconds), 0) as total_watchtime
                   FROM users u
                   LEFT JOIN watchtime w ON u.id = w.user_id 
                       AND w.watch_date >= CURRENT_DATE - INTERVAL '{days} days'
                   GROUP BY u.id
                   HAVING COALESCE(SUM(w.watch_seconds), 0) < {ph}
                   ORDER BY total_watchtime ASC""",
                (threshold_seconds,)
            )
        else:
            cursor.execute(
                f"""SELECT u.*, COALESCE(SUM(w.watch_seconds), 0) as total_watchtime
                   FROM users u
                   LEFT JOIN watchtime w ON u.id = w.user_id 
                       AND w.watch_date >= date('now', {ph})
                   GROUP BY u.id
                   HAVING total_watchtime < {ph}
                   ORDER BY total_watchtime ASC""",
                (f'-{days} days', threshold_seconds)
            )
        return [dict(row) for row in cursor.fetchall()]


def delete_user(discord_id: int) -> bool:
    """Delete a user and all their related data"""
    ph = get_placeholder()
    with get_connection() as conn:
        cursor = get_cursor(conn)
        
        # Get user ID first
        cursor.execute(f"SELECT id FROM users WHERE discord_id = {ph}", (discord_id,))
        user = cursor.fetchone()
        
        if not user:
            return False
        
        user_id = user['id'] if isinstance(user, dict) else user[0]
        
        # Delete related data
        cursor.execute(f"DELETE FROM watchtime WHERE user_id = {ph}", (user_id,))
        cursor.execute(f"DELETE FROM subscriptions WHERE user_id = {ph}", (user_id,))
        cursor.execute(f"DELETE FROM library_access WHERE user_id = {ph}", (user_id,))
        cursor.execute(f"DELETE FROM audit_log WHERE user_id = {ph}", (user_id,))
        cursor.execute(f"DELETE FROM users WHERE id = {ph}", (user_id,))
        
        conn.commit()
        return True


# Initialize database when module is imported
if __name__ == "__main__":
    init_database()
    print(f"Database created at: {DATABASE_PATH}")
