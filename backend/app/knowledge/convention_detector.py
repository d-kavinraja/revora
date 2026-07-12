import os
import re
from collections import Counter
from typing import Dict, List


def detect_conventions(repo_path: str) -> str:
    sections = []

    indent_style = _detect_indentation(repo_path)
    if indent_style:
        sections.append(f"Indentation: {indent_style}")

    naming = _detect_naming_conventions(repo_path)
    if naming:
        sections.append(f"Naming conventions: {naming}")

    import_style = _detect_import_style(repo_path)
    if import_style:
        sections.append(f"Import style: {import_style}")

    quote_style = _detect_quote_style(repo_path)
    if quote_style:
        sections.append(f"String quotes: {quote_style}")

    return "\n".join(sections) if sections else "No conventions detected."


def _detect_indentation(repo_path: str) -> str:
    tabs = 0
    spaces_2 = 0
    spaces_4 = 0
    count = 0

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv"}]
        for f in files:
            if not f.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java")):
                continue
            try:
                with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        stripped = line.lstrip()
                        if stripped and line != stripped:
                            leading = line[:len(line) - len(stripped)]
                            if leading.startswith("\t"):
                                tabs += 1
                            elif leading.startswith("    "):
                                spaces_4 += 1
                            elif leading.startswith("  "):
                                spaces_2 += 1
                            count += 1
                            if count > 500:
                                break
            except OSError:
                continue
            if count > 500:
                break
        if count > 500:
            break

    if count == 0:
        return ""
    if tabs > spaces_2 and tabs > spaces_4:
        return "tabs"
    if spaces_4 > spaces_2:
        return "4 spaces"
    if spaces_2 > 0:
        return "2 spaces"
    return ""


def _detect_naming_conventions(repo_path: str) -> str:
    snake_count = 0
    camel_count = 0
    pascal_count = 0
    count = 0

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv"}]
        for f in files:
            if not f.endswith((".py", ".js", ".ts", ".tsx", ".jsx")):
                continue
            try:
                with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fh:
                    for line in fh:
                        for match in re.finditer(r"\b(def|function|const|let|var|class)\s+(\w+)", line):
                            name = match.group(2)
                            if "_" in name and not name.startswith("_"):
                                snake_count += 1
                            elif name[0].isupper() and not name.isupper():
                                pascal_count += 1
                            elif re.match(r"^[a-z]+[A-Z]", name):
                                camel_count += 1
                            count += 1
                            if count > 200:
                                break
            except OSError:
                continue
            if count > 200:
                break
        if count > 200:
            break

    conventions = []
    if snake_count > camel_count and snake_count > pascal_count:
        conventions.append("snake_case for functions/variables")
    if camel_count > snake_count:
        conventions.append("camelCase for functions/variables")
    if pascal_count > snake_count:
        conventions.append("PascalCase for classes")

    return ", ".join(conventions) if conventions else ""


def _detect_import_style(repo_path: str) -> str:
    stdlib_first = 0
    third_first = 0

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv"}]
        for f in files:
            if not f.endswith(".py"):
                continue
            try:
                with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fh:
                    in_imports = False
                    has_stdlib = False
                    has_third = False
                    for line in fh:
                        stripped = line.strip()
                        if stripped.startswith("import ") or stripped.startswith("from "):
                            in_imports = True
                            if stripped.startswith(("import os", "import sys", "import json", "from os", "from sys")):
                                has_stdlib = True
                            elif not stripped.startswith(("import os", "import sys")):
                                has_third = True
                        elif in_imports and stripped:
                            if has_stdlib and has_third:
                                stdlib_first += 1
                            elif has_third and not has_stdlib:
                                third_first += 1
                            break
            except OSError:
                continue

    if stdlib_first > third_first:
        return "stdlib-first (PEP 8 style)"
    return ""


def _detect_quote_style(repo_path: str) -> str:
    single = 0
    double = 0

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv"}]
        for f in files:
            if not f.endswith((".py", ".js", ".ts")):
                continue
            try:
                with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read(10000)
                    single += content.count("'")
                    double += content.count('"')
            except OSError:
                continue

    if single > double * 1.5:
        return "single quotes"
    if double > single * 1.5:
        return "double quotes"
    return ""
