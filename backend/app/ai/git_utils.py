import os
import shutil
import tempfile
from git import Repo

class GitService:
    """Utility class for cloning and analyzing repositories."""
    
    @staticmethod
    def clone_repository(clone_url: str, token: str) -> str:
        """
        Clones a repository securely into a temporary directory.
        Uses the provided installation token.
        """
        # Inject token into URL for auth
        if "://" in clone_url:
            parts = clone_url.split("://")
            auth_url = f"{parts[0]}://x-access-token:{token}@{parts[1]}"
        else:
            auth_url = clone_url

        temp_dir = tempfile.mkdtemp(prefix="revora_repo_")
        
        # Shallow clone to save time and bandwidth
        Repo.clone_from(auth_url, temp_dir, depth=1)
        
        return temp_dir
        
    @staticmethod
    def cleanup_repository(repo_path: str):
        """Removes the temporary cloned repository."""
        if os.path.exists(repo_path) and repo_path.startswith(tempfile.gettempdir()):
            shutil.rmtree(repo_path, ignore_errors=True)
