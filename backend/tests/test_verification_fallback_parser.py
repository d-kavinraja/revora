from app.verification.engine import VerificationEngine


def test_fallback_parser_extracts_markdown_findings_without_backtracking_regexes():
    response = """### Security
- **Path traversal**: `src/api.ts` line: 42
  User-controlled path reaches a filesystem operation.
- **Unsafe file access**: backend/app.py:8
  A second issue has a separate line reference.
"""

    findings = VerificationEngine()._parse_findings(response)

    assert len(findings) == 2
    assert findings[0]["title"] == "Path traversal"
    assert findings[0]["file_path"] == "src/api.ts"
    assert findings[0]["line_number"] == 42
    assert findings[0]["category"] == "SECURITY"
    assert findings[1]["file_path"] == "backend/app.py"
    assert findings[1]["line_number"] == 8
