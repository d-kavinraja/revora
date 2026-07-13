from dataclasses import dataclass, field
from typing import Dict


@dataclass
class PromptSection:
    name: str
    content: str
    token_count: int = 0
    version: str = "1.0"


@dataclass
class CompiledPrompt:
    version: str = "1.0"
    sections: Dict[str, PromptSection] = field(default_factory=dict)
    system_prompt: str = ""
    user_prompt: str = ""
    total_tokens: int = 0
    cache_key: str = ""

    def get_user_messages(self) -> list[dict]:
        messages = [{"role": "system", "content": self.system_prompt}]
        if self.user_prompt:
            messages.append({"role": "user", "content": self.user_prompt})
        return messages
