import os
import aiofiles
from typing import Dict, Any, Optional

MAX_FILE_READ_BYTES = 1024 * 1024  # 1MB limit

class EvidenceEngine:
    """Generates evidence for verified findings."""
    def _find_actual_file(self, repo_path: str, file_path: str) -> str:
        full_path = os.path.join(repo_path, file_path)
        if os.path.exists(full_path):
            return file_path
        
        basename = os.path.basename(file_path)
        for root, dirs, files in os.walk(repo_path):
            if basename in files:
                return os.path.relpath(os.path.join(root, basename), repo_path)
        return file_path

    async def generate(self, finding: Dict[str, Any], repo_path: str) -> Optional[Dict[str, Any]]:
        file_path = finding.get("file_path", "")
        line_number = finding.get("line_number")
        
        if not file_path:
            return None
            
        file_path = self._find_actual_file(repo_path, file_path)
        full_path = os.path.join(repo_path, file_path)
        if not os.path.exists(full_path):
            return None
            
        if not line_number:
            return {
                "evidence_type": "FILE_EXISTS",
                "content": f"File {file_path} exists.",
                "metadata": {}
            }
            
        try:
            # Prevent reading massive files which would cause OOM and latency
            file_size = os.path.getsize(full_path)
            if file_size > MAX_FILE_READ_BYTES:
                return {
                    "evidence_type": "FILE_EXISTS",
                    "content": f"File {file_path} exists but is too large (>{MAX_FILE_READ_BYTES} bytes) to extract snippets.",
                    "metadata": {"file_size": file_size}
                }
                
            # Extract snippet around the line number (e.g., +/- 2 lines)
            # Python lists are 0-indexed, so line_number 87 is lines[86].
            async with aiofiles.open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = await f.readlines()
                
            zero_based_line = line_number - 1
            if zero_based_line < 0 or zero_based_line >= len(lines):
                return None
                
            start = max(0, zero_based_line - 2)
            end = min(len(lines), zero_based_line + 3)
            
            snippet = "".join(lines[start:end])
            
            return {
                "evidence_type": "SNIPPET",
                "content": f"{file_path}:{line_number}\n\n{snippet}",
                "metadata": {
                    "start_line": start + 1,
                    "end_line": end
                }
            }
        except Exception:
            return None
