import os

def safe_join(base_dir: str, user_path: str) -> str:
    """Safely joins a base directory with a user-provided path.
    
    Prevents path traversal by resolving the real path and ensuring
    it strictly resides within the base directory.
    
    Raises ValueError if the path escapes the base directory.
    """
    # Resolve the absolute path of the base directory
    base_dir = os.path.realpath(base_dir)
    
    # Attempt to join and resolve the final path
    final_path = os.path.realpath(os.path.join(base_dir, user_path))
    
    # Ensure the final path starts with the base directory path + sep
    # (or is exactly the base dir, though usually we want files inside it)
    if not final_path.startswith(base_dir + os.sep) and final_path != base_dir:
        raise ValueError("Path traversal attempt detected")
        
    return final_path
