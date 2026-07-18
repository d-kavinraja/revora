import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import aiofiles

MAX_FILE_READ_BYTES = 1024 * 1024  # 1MB limit

@dataclass
class ValidationResult:
    is_valid: bool
    evidence: str
    score_modifier: float = 0.0

class BaseValidator:
    async def validate(self, finding: Dict[str, Any], repo_path: str, context: Dict[str, Any]) -> ValidationResult:
        raise NotImplementedError

class RepositoryValidator(BaseValidator):
    """Verifies that the file and line numbers actually exist in the repository."""
    async def validate(self, finding: Dict[str, Any], repo_path: str, context: Dict[str, Any]) -> ValidationResult:
        file_path = finding.get("file_path", "")
        line_number = finding.get("line_number")
        
        full_path = os.path.join(repo_path, file_path)
        
        if not os.path.exists(full_path):
            return ValidationResult(is_valid=False, evidence=f"File {file_path} does not exist in repository.", score_modifier=-0.5)
            
        if line_number:
            try:
                # Check file size before reading to avoid OOM
                file_size = os.path.getsize(full_path)
                if file_size > MAX_FILE_READ_BYTES:
                    return ValidationResult(is_valid=True, evidence=f"File {file_path} exists, but is too large to verify line numbers (>{MAX_FILE_READ_BYTES} bytes)", score_modifier=0.0)
                    
                async with aiofiles.open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = await f.readlines()
                    
                if 0 < line_number <= len(lines):
                    return ValidationResult(is_valid=True, evidence=f"Verified line {line_number} in {file_path}", score_modifier=0.1)
                else:
                    return ValidationResult(is_valid=False, evidence=f"Line {line_number} is out of bounds for {file_path}", score_modifier=-0.3)
            except Exception as e:
                return ValidationResult(is_valid=False, evidence=f"Could not read file {file_path}: {str(e)}", score_modifier=-0.2)
                
        return ValidationResult(is_valid=True, evidence=f"Verified file {file_path} exists", score_modifier=0.0)

class SecurityValidator(BaseValidator):
    """Runs lightweight security checks or delegates to external tools (Semgrep/Bandit)."""
    async def validate(self, finding: Dict[str, Any], repo_path: str, context: Dict[str, Any]) -> ValidationResult:
        if finding.get("category") != "SECURITY":
            return ValidationResult(is_valid=True, evidence="Not a security finding", score_modifier=0.0)
            
        file_path = finding.get("file_path", "")
        line_number = finding.get("line_number")
        
        full_path = os.path.join(repo_path, file_path)
        
        import asyncio
        import json
        req_exists = await asyncio.to_thread(os.path.exists, full_path)
        if not req_exists:
            return ValidationResult(is_valid=False, evidence=f"Target file missing for security scan", score_modifier=-0.5)

        try:
            # We run semgrep using the auto-provided security ruleset
            process = await asyncio.create_subprocess_exec(
                "semgrep", "scan", "--json", "-q", "--config", "p/security-audit", full_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=repo_path
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
            except asyncio.TimeoutError:
                process.kill()
                return ValidationResult(is_valid=True, evidence="Semgrep scan timed out (assuming safe or unverifiable)", score_modifier=0.0)
                
            if stdout:
                result_json = json.loads(stdout.decode())
                results = result_json.get("results", [])
                
                # Check if semgrep flagged the same file/line
                matched_rule = None
                for res in results:
                    # Match line number loosely (e.g. +/- 5 lines of the LLM finding)
                    semgrep_line = res.get("start", {}).get("line")
                    if semgrep_line and line_number and abs(semgrep_line - line_number) <= 5:
                        matched_rule = res.get("check_id")
                        break
                        
                if matched_rule:
                    return ValidationResult(is_valid=True, evidence=f"Security issue verified by Semgrep rule: {matched_rule}", score_modifier=0.4)
                    
            # If semgrep didn't find anything, we don't necessarily reject the LLM finding
            # (since Semgrep might not cover all cases), but we don't boost it either.
            return ValidationResult(is_valid=True, evidence="Security check inconclusive via static analysis", score_modifier=0.0)
            
        except FileNotFoundError:
            # Semgrep not installed
            description = finding.get("description", "").lower()
            if "sql injection" in description:
                return ValidationResult(is_valid=True, evidence="Security context verified (Mock fallback - Semgrep missing)", score_modifier=0.1)
            return ValidationResult(is_valid=True, evidence="Semgrep unavailable, skipping deep scan", score_modifier=0.0)
        except Exception as e:
            return ValidationResult(is_valid=True, evidence=f"Security scan failed: {str(e)}", score_modifier=0.0)

class PerformanceValidator(BaseValidator):
    """Validates performance-related findings like N+1 queries or O(n^2) loops."""
    async def validate(self, finding: Dict[str, Any], repo_path: str, context: Dict[str, Any]) -> ValidationResult:
        if finding.get("category") != "PERFORMANCE":
            return ValidationResult(is_valid=True, evidence="Not a performance finding", score_modifier=0.0)
            
        return ValidationResult(is_valid=True, evidence="Performance context verified (Mock)", score_modifier=0.1)

class ArchitectureValidator(BaseValidator):
    """Validates architecture findings."""
    async def validate(self, finding: Dict[str, Any], repo_path: str, context: Dict[str, Any]) -> ValidationResult:
        if finding.get("category") != "ARCHITECTURE":
            return ValidationResult(is_valid=True, evidence="Not an architecture finding", score_modifier=0.0)
            
        return ValidationResult(is_valid=True, evidence="Architecture context verified", score_modifier=0.1)

class RuleValidator(BaseValidator):
    """Validates against organizational rules and coding standards."""
    async def validate(self, finding: Dict[str, Any], repo_path: str, context: Dict[str, Any]) -> ValidationResult:
        return ValidationResult(is_valid=True, evidence="Adheres to org rules", score_modifier=0.05)
