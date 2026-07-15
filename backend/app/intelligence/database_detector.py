"""Database detection engine.

Detects database types and ORMs by analyzing file content.
Uses the shared RepoWalker for efficient filesystem access.
"""

from typing import List, Optional, Set

from app.intelligence.models import DatabaseInfo
from app.intelligence.base_detector import BaseDetector, DetectorResult
from app.core.constants import MAX_FILES_PER_DETECTOR, MAX_FILE_READ_CHARS


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
    "django_orm": ["django.db.models"],
    "alembic": ["alembic"],
}

CONFIG_INDICATORS = {
    "postgresql": ["DATABASE_URL", "POSTGRES", "postgres"],
    "mysql": ["MYSQL", "mysql"],
    "sqlite": [".sqlite", "sqlite3"],
    "mongodb": ["MONGODB", "MONGO"],
    "redis": ["REDIS"],
}

CHECK_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".json",
    ".toml", ".yaml", ".yml", ".env", ".cfg", ".ini",
}


class DatabaseDetector(BaseDetector):
    """Detects database types and ORMs."""

    @property
    def name(self) -> str:
        return "database_detector"

    @property
    def version(self) -> str:
        return "1.0.0"

    async def detect(self, walker: 'RepoWalker') -> DetectorResult:
        """Detect databases using the RepoWalker cache.

        Args:
            walker: Initialized RepoWalker.

        Returns:
            DetectorResult with database info.
        """
        indicators: List[str] = []
        db_type: Optional[str] = None
        orm: Optional[str] = None

        # Collect files to check
        files_to_check = []
        for fp in walker.file_paths:
            if any(fp.endswith(ext) for ext in CHECK_EXTENSIONS):
                files_to_check.append(fp)
            if len(files_to_check) >= MAX_FILES_PER_DETECTOR:
                break

        # Read and concatenate file content
        all_content = ""
        for fp in files_to_check:
            content = await walker.get_content(fp, max_chars=MAX_FILE_READ_CHARS)
            if content:
                all_content += content + "\n"

        # Detect database type
        for db_name, keywords in DB_SIGNATURES.items():
            for kw in keywords:
                if kw in all_content:
                    db_type = db_name
                    indicators.append(f"Found {kw} reference")
                    break
            if db_type:
                break

        # Detect ORM
        for orm_name, keywords in ORM_SIGNATURES.items():
            for kw in keywords:
                if kw in all_content:
                    orm = orm_name
                    indicators.append(f"Found {orm_name} usage")
                    break
            if orm:
                break

        # Check .env files if no database found
        if not db_type:
            env_files = [fp for fp in walker.file_paths if fp.endswith(".env")]
            for env_file in env_files:
                content = await walker.get_content(env_file)
                if content:
                    for db_name, keywords in CONFIG_INDICATORS.items():
                        for kw in keywords:
                            if kw in content:
                                db_type = db_name
                                indicators.append(f"Found {db_name} in .env")
                                break
                        if db_type:
                            break
                if db_type:
                    break

        return DetectorResult(
            success=True,
            data={
                "databases": [db_type] if db_type else [],
                "orms": [orm] if orm else [],
                "drivers": [],
                "indicators": indicators,
            },
            confidence=0.8 if db_type or orm else 0.0,
        )


# Legacy function interface for backward compatibility
def detect_database(repo_path: str) -> Optional[DatabaseInfo]:
    """Detect databases in a repository (legacy interface)."""
    import asyncio
    from app.intelligence.repo_walker import RepoWalker

    async def _detect():
        walker = RepoWalker(repo_path)
        await walker.walk()
        detector = DatabaseDetector()
        result = await detector.detect(walker)
        data = result.data
        if not data.get("databases") and not data.get("orms"):
            return None
        return DatabaseInfo(
            type=data["databases"][0] if data.get("databases") else None,
            orm=data["orms"][0] if data.get("orms") else None,
            indicators=data.get("indicators", []),
        )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _detect()).result()
        else:
            return loop.run_until_complete(_detect())
    except RuntimeError:
        return asyncio.run(_detect())
