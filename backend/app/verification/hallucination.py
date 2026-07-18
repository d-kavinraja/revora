from typing import Dict, Any, Optional

class HallucinationDetector:
    """Detects hallucinations in AI findings."""
    
    def detect(self, finding: Dict[str, Any], repo_path: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Returns a dict with hallucination details if detected, else None.
        """
        # A finding is a hallucination if it fails repository validation (e.g. file doesn't exist)
        # or if it mentions an API/library not present in the project.
        
        # We rely on the RepositoryValidator for file/line checks, but we can do semantic checks here.
        description = finding.get("description", "").lower()
        
        # Example semantic hallucination check:
        # If the description mentions a library that doesn't exist in dependencies
        # (This requires parsing package.json, requirements.txt, etc., passed in `context`)
        import re
        dependencies = context.get("dependencies", [])
        
        # Use word boundaries to avoid aggressive substring matches
        if re.search(r'\b(uses|using|import|require|depends on)\s+redis\b', description) and "redis" not in dependencies:
            return {
                "type": "FAKE_DEPENDENCY",
                "details": "The finding implies the usage of Redis, but Redis is not a dependency in this repository."
            }
            
        if re.search(r'\b(sql injection|execute sql)\b', description) and not any(db in dependencies for db in ["sqlalchemy", "psycopg2", "mysql", "pg", "sqlite", "sqlite3"]):
            if context.get("is_database_repo") is False:
                return {
                    "type": "FAKE_DATABASE",
                    "details": "The finding mentions SQL vulnerabilities, but this repository does not seem to use a database."
                }
                
        return None
