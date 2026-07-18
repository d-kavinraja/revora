import os
import shutil
import tempfile
import asyncio
from git import Repo

class GitService:
    """Utility class for cloning and analyzing repositories."""
    
    @staticmethod
    async def clone_repository(clone_url: str, token: str) -> str:
        """
        Clones a repository securely into a temporary directory.
        Uses the provided installation token.
        """
        # Inject token into URL for auth
        if "://" in clone_url:
            parts = clone_url.split("://")
            auth_url = f"{parts[0]}://x-access-token:{token}@{parts[1]}" if token else clone_url
        else:
            auth_url = clone_url

        temp_dir = tempfile.mkdtemp(prefix="revora_repo_")
        
        # Shallow clone to save time and bandwidth
        def _clone():
            Repo.clone_from(auth_url, temp_dir, depth=1)
            
        await asyncio.to_thread(_clone)
        
        return temp_dir
        
    @staticmethod
    async def cleanup_repository(repo_path: str):
        """Removes the temporary cloned repository."""
        def _cleanup():
            if os.path.exists(repo_path) and repo_path.startswith(tempfile.gettempdir()):
                shutil.rmtree(repo_path, ignore_errors=True)
                
        await asyncio.to_thread(_cleanup)
