"""Unified local CLI agent adapter for agy, claude, codex, and deterministic demo mode."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from ..config import BinaryOverrides, EffortLevel, ProviderName, StageRoute
from ..models import AgentCLIStatus


@dataclass
class AgentInvocationResult:
    text: str
    structured: Optional[Dict[str, Any]] = None
    conversation_id: Optional[str] = None
    provider: ProviderName = "demo"
    model: str = "demo"
    effort: EffortLevel = "medium"
    raw_command: List[str] = field(default_factory=list)


PROVIDER_METADATA: Dict[str, Dict[str, Any]] = {
    "agy": {
        "display_name": "Antigravity CLI (agy)",
        "setup_hint": "Install Antigravity CLI and verify `agy --version` is on your PATH, or set an explicit binary path below.",
        "recommended_models": ["gemini-4-neon", "gemini-3-pro", "gemini-3-flash"],
        "supported_efforts": ["low", "medium", "high"],
    },
    "claude": {
        "display_name": "Claude Code (claude)",
        "setup_hint": "Install Claude Code (`npm i -g @anthropic-ai/claude-code` or native installer) and sign in via `claude`.",
        "recommended_models": ["opus", "sonnet", "haiku"],
        "supported_efforts": ["low", "medium", "high", "max"],
    },
    "codex": {
        "display_name": "OpenAI Codex CLI (codex)",
        "setup_hint": "Install Codex CLI (`npm i -g @openai/codex`) and authenticate with `codex login`.",
        "recommended_models": ["gpt-5.4", "gpt-5.3-codex", "o3"],
        "supported_efforts": ["low", "medium", "high"],
    },
    "demo": {
        "display_name": "Deterministic Studio Engine (demo)",
        "setup_hint": "Built-in offline pedagogical engine for deterministic evaluation and local testing without CLI quota.",
        "recommended_models": ["scholia-demo-v1"],
        "supported_efforts": ["low", "medium", "high"],
    },
}


class AgentRunner:
    """Executes headless coding-agent CLI commands and streams output."""

    def __init__(self, overrides: Optional[BinaryOverrides] = None):
        self.overrides = overrides or BinaryOverrides()

    def resolve_binary(self, provider: ProviderName) -> Optional[str]:
        if provider == "demo":
            return "builtin://demo"
        override = getattr(self.overrides, provider, None)
        if override and Path(override).expanduser().exists():
            return str(Path(override).expanduser())
        return shutil.which(provider)

    def detect_agents(self) -> List[AgentCLIStatus]:
        statuses: List[AgentCLIStatus] = []
        for provider in ("agy", "claude", "codex", "demo"):
            meta = PROVIDER_METADATA[provider]
            binary = self.resolve_binary(provider)  # type: ignore[arg-type]
            version: Optional[str] = None
            available = False
            if provider == "demo":
                available = True
                version = "scholia-demo 0.1.0 (offline)"
            elif binary:
                available = True
                try:
                    proc = subprocess.run(
                        [binary, "--version"],
                        capture_output=True,
                        text=True,
                        timeout=3,
                        check=False,
                    )
                    raw_out = (proc.stdout or proc.stderr or "").strip()
                    version = raw_out.splitlines()[0].strip() if raw_out else "installed"
                except Exception:
                    version = "installed"
            statuses.append(
                AgentCLIStatus(
                    provider=provider,  # type: ignore[arg-type]
                    display_name=meta["display_name"],
                    available=available,
                    binary_path=binary,
                    version=version,
                    setup_hint=meta["setup_hint"],
                    recommended_models=meta["recommended_models"],
                    supported_efforts=meta["supported_efforts"],
                )
            )
        return statuses

    def build_command(
        self,
        route: StageRoute,
        prompt: str,
        chapter_dir: Optional[Path] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        schema_file_path: Optional[Path] = None,
        conversation_id: Optional[str] = None,
        image_paths: Optional[List[Path]] = None,
    ) -> List[str]:
        """Construct verified headless CLI argv for agy, claude, or codex."""
        provider = route.provider
        binary = self.resolve_binary(provider) or provider

        if provider == "agy":
            cmd = [
                binary,
                "-p",
                prompt,
                "--output-format",
                "stream-json",
                "--model",
                route.model,
                "--effort",
                route.effort,
            ]
            if schema_file_path:
                cmd.extend(["--json-schema", str(schema_file_path)])
            if conversation_id:
                cmd.extend(["--conversation", conversation_id])
            if chapter_dir:
                cmd.extend(["--add-dir", str(chapter_dir)])
            return cmd

        if provider == "claude":
            # Verified against locally installed `claude --help` (2.1.283):
            # -p, --output-format stream-json --verbose, --model, --effort, --json-schema <json>, --resume <id>, --add-dir
            cmd = [
                binary,
                "-p",
                prompt,
                "--output-format",
                "stream-json",
                "--verbose",
                "--permission-mode",
                "dontAsk",
            ]
            if route.model:
                cmd.extend(["--model", route.model])
            if route.effort:
                cmd.extend(["--effort", route.effort])
            if json_schema is not None:
                cmd.extend(["--json-schema", json.dumps(json_schema)])
            if conversation_id:
                cmd.extend(["--resume", conversation_id])
            if chapter_dir:
                cmd.extend(["--add-dir", str(chapter_dir)])
            return cmd

        if provider == "codex":
            # Verified against locally installed `codex exec --help` (0.144.4):
            # codex exec --json --skip-git-repo-check --sandbox read-only -m <model> -c model_reasoning_effort=<effort> --output-schema <file> -C <dir> -i <img...> <prompt>
            cmd = [
                binary,
                "exec",
                "--json",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
            ]
            if route.model:
                cmd.extend(["-m", route.model])
            if route.effort:
                cmd.extend(["-c", f"model_reasoning_effort={route.effort}"])
            if schema_file_path:
                cmd.extend(["--output-schema", str(schema_file_path)])
            if chapter_dir:
                cmd.extend(["-C", str(chapter_dir)])
            for img in image_paths or []:
                cmd.extend(["-i", str(img)])
            cmd.append(prompt)
            return cmd

        return ["demo", route.model, route.effort]

    async def stream_text(
        self,
        route: StageRoute,
        prompt: str,
        chapter_dir: Optional[Path] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        image_paths: Optional[List[Path]] = None,
        demo_fallback_text: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream events `{type: 'delta'|'done'|'meta', text: ...}` from the selected CLI or demo driver."""
        if route.provider == "demo" or not self.resolve_binary(route.provider):
            reply = demo_fallback_text or self._synthesize_generic_demo_text(prompt)
            tokens = re.findall(r"\S+\s*", reply)
            for chunk in tokens:
                yield {"type": "delta", "text": chunk}
                await asyncio.sleep(0.008)
            yield {
                "type": "done",
                "text": reply,
                "conversation_id": conversation_id or "demo-conv",
                "provider": "demo" if route.provider == "demo" else route.provider,
                "fallback": route.provider != "demo",
            }
            return

        schema_tmp: Optional[Path] = None
        try:
            if json_schema is not None and route.provider in ("agy", "codex"):
                fd, tmp_path = tempfile.mkstemp(prefix="scholia-schema-", suffix=".json")
                Path(tmp_path).write_text(json.dumps(json_schema), encoding="utf-8")
                schema_tmp = Path(tmp_path)

            cmd = self.build_command(
                route=route,
                prompt=prompt,
                chapter_dir=chapter_dir,
                json_schema=json_schema,
                schema_file_path=schema_tmp,
                conversation_id=conversation_id,
                image_paths=image_paths,
            )

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(chapter_dir) if chapter_dir else None,
            )
            collected_parts: List[str] = []
            seen_conv_id = conversation_id

            assert proc.stdout is not None
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                delta, conv_id = self._parse_stream_json_line(route.provider, line)
                if conv_id:
                    seen_conv_id = conv_id
                if delta:
                    collected_parts.append(delta)
                    yield {"type": "delta", "text": delta}

            await proc.wait()
            stderr_text = ""
            if proc.stderr:
                stderr_text = (await proc.stderr.read()).decode("utf-8", errors="replace").strip()

            full_text = "".join(collected_parts).strip()
            if proc.returncode != 0 and not full_text:
                if demo_fallback_text:
                    for chunk in re.findall(r"\S+\s*", demo_fallback_text):
                        yield {"type": "delta", "text": chunk}
                        await asyncio.sleep(0.005)
                    yield {
                        "type": "done",
                        "text": demo_fallback_text,
                        "conversation_id": seen_conv_id,
                        "warning": f"{route.provider} exited with code {proc.returncode}: {stderr_text[:240]}",
                    }
                    return
                raise RuntimeError(f"{route.provider} CLI failed (exit {proc.returncode}): {stderr_text[:400]}")

            yield {"type": "done", "text": full_text, "conversation_id": seen_conv_id}
        finally:
            if schema_tmp and schema_tmp.exists():
                schema_tmp.unlink(missing_ok=True)

    async def run_complete(
        self,
        route: StageRoute,
        prompt: str,
        chapter_dir: Optional[Path] = None,
        json_schema: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        image_paths: Optional[List[Path]] = None,
        demo_fallback_text: Optional[str] = None,
    ) -> AgentInvocationResult:
        final_text = ""
        final_conv = conversation_id
        async for ev in self.stream_text(
            route=route,
            prompt=prompt,
            chapter_dir=chapter_dir,
            json_schema=json_schema,
            conversation_id=conversation_id,
            image_paths=image_paths,
            demo_fallback_text=demo_fallback_text,
        ):
            if ev["type"] == "done":
                final_text = ev["text"]
                final_conv = ev.get("conversation_id")

        structured = self._try_extract_json(final_text) if json_schema else None
        return AgentInvocationResult(
            text=final_text,
            structured=structured,
            conversation_id=final_conv,
            provider=route.provider,
            model=route.model,
            effort=route.effort,
        )

    @staticmethod
    def _parse_stream_json_line(provider: ProviderName, line: str) -> tuple[str, Optional[str]]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return line + "\n", None

        conv_id = payload.get("session_id") or payload.get("conversation_id") or payload.get("thread_id")

        # Claude stream-json format
        if payload.get("type") == "assistant" and isinstance(payload.get("message"), dict):
            blocks = payload["message"].get("content", [])
            texts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
            return "".join(texts), conv_id
        if payload.get("type") == "content_block_delta":
            delta = payload.get("delta", {})
            return delta.get("text", ""), conv_id
        if payload.get("type") == "result" and isinstance(payload.get("result"), str):
            return "", conv_id  # already emitted via assistant message

        # Codex --json format
        if payload.get("type") == "item.completed" and isinstance(payload.get("item"), dict):
            item = payload["item"]
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                return item["text"], conv_id

        # Antigravity / generic delta format
        if isinstance(payload.get("delta"), str):
            return payload["delta"], conv_id
        if isinstance(payload.get("text"), str) and payload.get("type") not in ("system", "init"):
            return payload["text"], conv_id

        return "", conv_id

    @staticmethod
    def _try_extract_json(text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    return None
            return None

    @staticmethod
    def _synthesize_generic_demo_text(prompt: str) -> str:
        return (
            "The mechanism depends on identifying the minimal state sufficient to separate past decisions from future constraints. "
            "Which invariant breaks first when that state omits a boundary variable?"
        )
