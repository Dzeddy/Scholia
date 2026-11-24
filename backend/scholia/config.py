"""Configuration and persistent vault settings for Scholia."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field

ProviderName = Literal["agy", "claude", "codex", "demo"]
EffortLevel = Literal["low", "medium", "high", "max"]
StageKey = Literal[
    "extraction_planning",
    "socratic_dialogue",
    "oral_exam_grading",
    "note_enrichment",
]


class StageRoute(BaseModel):
    provider: ProviderName = "claude"
    model: str = "opus"
    effort: EffortLevel = "high"


class BinaryOverrides(BaseModel):
    agy: Optional[str] = None
    claude: Optional[str] = None
    codex: Optional[str] = None


def default_stage_routing() -> Dict[str, StageRoute]:
    return {
        "extraction_planning": StageRoute(provider="agy", model="gemini-4-neon", effort="high"),
        "socratic_dialogue": StageRoute(provider="agy", model="gemini-4-neon", effort="low"),
        "oral_exam_grading": StageRoute(provider="claude", model="opus", effort="high"),
        "note_enrichment": StageRoute(provider="claude", model="sonnet", effort="medium"),
    }


class ScholiaConfig(BaseModel):
    vault_dir: str = Field(default_factory=lambda: str(get_vault_dir()))
    routing: Dict[str, StageRoute] = Field(default_factory=default_stage_routing)
    binary_overrides: BinaryOverrides = Field(default_factory=BinaryOverrides)
    max_pdf_pages_per_slice: int = 20
    socratic_max_sentences: int = 4
    voice_rules_enabled: bool = True


def get_vault_dir() -> Path:
    env_dir = os.environ.get("SCHOLIA_VAULT_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return (Path.home() / "scholia-vault").resolve()


def ensure_vault_dirs(vault_dir: Optional[Path] = None) -> Path:
    root = (vault_dir or get_vault_dir()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "books").mkdir(parents=True, exist_ok=True)
    (root / "workspaces").mkdir(parents=True, exist_ok=True)
    return root


def load_config(vault_dir: Optional[Path] = None) -> ScholiaConfig:
    root = ensure_vault_dirs(vault_dir)
    cfg_path = root / "config.json"
    if cfg_path.exists():
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
            cfg = ScholiaConfig.model_validate(raw)
            cfg.vault_dir = str(root)
            for k, v in default_stage_routing().items():
                cfg.routing.setdefault(k, v)
            return cfg
        except Exception:
            pass
    cfg = ScholiaConfig(vault_dir=str(root))
    save_config(cfg, root)
    return cfg


def save_config(cfg: ScholiaConfig, vault_dir: Optional[Path] = None) -> ScholiaConfig:
    root = ensure_vault_dirs(vault_dir or Path(cfg.vault_dir))
    cfg.vault_dir = str(root)
    cfg_path = root / "config.json"
    cfg_path.write_text(
        json.dumps(cfg.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    return cfg
