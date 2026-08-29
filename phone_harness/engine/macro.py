"""
Macro Recorder and Deterministic Replay Engine.
Allows agents to record and replay high-speed action sequences without LLM turn latency.
"""

from typing import Dict, List, Optional
import json
from phone_harness.core.models import Macro, MacroStep, ActionRequest


class MacroManager:
    """Stores, serializes, and replays action macros."""

    def __init__(self):
        self._macros: Dict[str, Macro] = {}

    def register_macro(self, macro: Macro) -> None:
        self._macros[macro.name] = macro

    def get_macro(self, name: str) -> Optional[Macro]:
        return self._macros.get(name)

    def list_macros(self) -> List[str]:
        return list(self._macros.keys())

    def export_json(self, name: str) -> str:
        macro = self._macros.get(name)
        if not macro:
            raise KeyError(f"Macro '{name}' does not exist.")
        return macro.model_dump_json(indent=2)

    def import_json(self, json_str: str) -> Macro:
        data = json.loads(json_str)
        macro = Macro.model_validate(data)
        self.register_macro(macro)
        return macro
