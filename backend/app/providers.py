from __future__ import annotations

import os
import httpx


class LLMProvider:
    async def generate(self, prompt: str) -> str:
        raise NotImplementedError


class OllamaProvider(LLMProvider):
    def __init__(self) -> None:
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self.model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

    async def generate(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(f"{self.base_url}/api/generate", json={"model": self.model, "prompt": prompt, "stream": False})
            response.raise_for_status()
            return response.json().get("response", "")


def get_provider() -> LLMProvider:
    # Provider boundary is stable for future local/hosted implementations.
    return OllamaProvider()
