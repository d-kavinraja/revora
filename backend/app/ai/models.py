from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class LanguageInfo:
    name: str
    file_count: int
    percentage: float

@dataclass
class FrameworkInfo:
    name: str
    version: Optional[str] = None
    config_file: Optional[str] = None

@dataclass
class ChangedFileInfo:
    filename: str
    status: str
    additions: int
    deletions: int
    patch: str
    context_lines: Optional[str] = None

@dataclass
class RepositoryContext:
    languages: List[LanguageInfo] = field(default_factory=list)
    frameworks: List[FrameworkInfo] = field(default_factory=list)
    dependencies: Dict[str, str] = field(default_factory=dict)
    configs: Dict[str, str] = field(default_factory=dict)
    architecture: Dict[str, str] = field(default_factory=dict)
    code_style: Dict[str, str] = field(default_factory=dict)
    documentation: Dict[str, str] = field(default_factory=dict)
    changed_files: List[ChangedFileInfo] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "languages": [vars(l) for l in self.languages],
            "frameworks": [vars(f) for f in self.frameworks],
            "dependencies": self.dependencies,
            "architecture": self.architecture,
            "code_style": self.code_style,
            "changed_files": [vars(c) for c in self.changed_files]
        }
