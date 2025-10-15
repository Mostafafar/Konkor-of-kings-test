import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

def setup_database():
    """راه‌اندازی اولیه دیتابیس"""
    
    # اتصال به دیتابیس پیش‌فرض
    conn = psycopg2.connect(
        dbname='postgres',
        user='postgres',
        password='f13821382',
        host='localhost',
        port='5432'
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    
    try:
        cursor.execute("CREATE DATABASE quiz_bot_db;")
        print("✅ Database created successfully")
    except Exception as e:
        print(f"⚠️ Database might already exist: {e}")
    
    cursor.close()
    conn.close()

if __name__ == "__main__":
    setup_database()
