import os
from typing import Optional, List

from app.intelligence.models import DatabaseInfo


DB_SIGNATURES = {
    "postgresql": ["postgresql", "postgres", "psycopg", "asyncpg", "pg"],
    "mysql": ["mysql", "pymysql", "mysqlclient", "mysql2"],
    "sqlite": ["sqlite", "aiosqlite"],
    "mongodb": ["mongodb", "pymongo", "motor", "mongoose"],
    "redis": ["redis", "aioredis", "redis-py"],
    "mssql": ["mssql", "pyodbc", "sqlserver"],
    "oracle": ["oracle", "cx_oracle", "oracledb"],
}

ORM_SIGNATURES = {
    "sqlalchemy": ["sqlalchemy", "SQLAlchemy"],
    "prisma": ["prisma", "@prisma/client"],
    "typeorm": ["typeorm", "TypeORM"],
    "drizzle": ["drizzle-orm", "drizzle"],
    "mongoose": ["mongoose", "Mongoose"],
    "sequelize": ["sequelize", "Sequelize"],
    "peewee": ["peewee"],
    "tortoise": ["tortoise-orm", "tortoise"],
    "djang ORM": ["django.db.models"],
    "alembic": ["alembic"],
}

CONFIG_INDICATORS = {
    "postgresql": ["DATABASE_URL", "POSTGRES", "postgres"],
    "mysql": ["MYSQL", "mysql"],
    "sqlite": [".sqlite", "sqlite3"],
    "mongodb": ["MONGODB", "MONGO"],
    "redis": ["REDIS"],
}


def detect_database(repo_path: str) -> Optional[DatabaseInfo]:
    indicators: list[str] = []
    db_type: Optional[str] = None
    orm: Optional[str] = None

    files_to_check = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv", "__pycache__"}]
        for f in files:
            if f.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml", ".yml", ".env", ".cfg", ".ini")):
                files_to_check.append(os.path.join(root, f))
        if len(files_to_check) > 200:
            break

    all_content = ""
    for fp in files_to_check[:200]:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                all_content += f.read()[:5000] + "\n"
        except (OSError, IOError):
            continue

    for db_name, keywords in DB_SIGNATURES.items():
        for kw in keywords:
            if kw in all_content:
                db_type = db_name
                indicators.append(f"Found {kw} reference")
                break
        if db_type:
            break

    for orm_name, keywords in ORM_SIGNATURES.items():
        for kw in keywords:
            if kw in all_content:
                orm = orm_name
                indicators.append(f"Found {orm_name} usage")
                break
        if orm:
            break

    if not db_type:
        env_file = os.path.join(repo_path, ".env")
        if os.path.exists(env_file):
            try:
                with open(env_file, "r") as f:
                    env_content = f.read()
                for db_name, keywords in CONFIG_INDICATORS.items():
                    for kw in keywords:
                        if kw in env_content:
                            db_type = db_name
                            indicators.append(f"Found {db_name} in .env")
                            break
                    if db_type:
                        break
            except OSError:
                pass

    if not db_type and not orm:
        return None

    return DatabaseInfo(type=db_type, orm=orm, indicators=indicators)
