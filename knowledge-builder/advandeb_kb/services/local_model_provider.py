"""
Custom model provider that routes OpenAI Agents SDK calls to local Ollama instances.
This ensures no external API calls are made to OpenAI servers.
"""
import httpx
import json
import asyncio
from typing import Dict, Any, List, Optional, Iterator, AsyncIterator
from advandeb_kb.config.settings import settings
import logging

logger = logging.getLogger(__name__)


class OllamaModelProvider:
    """
    Custom model provider that implements OpenAI-compatible interface
    but routes all calls to local Ollama instances.
    """
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.client = httpx.AsyncClient(timeout=60.0)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
    
    async def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        OpenAI-compatible chat completion that routes to Ollama
        """
        try:
            if stream:
                return await self._stream_chat_completion(model, messages, temperature, max_tokens)
            else:
                return await self._non_stream_chat_completion(model, messages, temperature, max_tokens)
        except Exception as e:
            logger.error(f"Ollama chat completion error: {e}")
            raise
    
    async def _non_stream_chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """Non-streaming chat completion"""
        request_payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature
            }
        }
        
        if max_tokens:
            request_payload["options"]["num_predict"] = max_tokens
        
        response = await self.client.post(
            f"{self.base_url}/api/chat",
            json=request_payload
        )
        response.raise_for_status()
        
        ollama_response = response.json()
        
        # Convert Ollama response to OpenAI format
        return {
            "id": f"chatcmpl-{hash(str(messages))}"[:28],
            "object": "chat.completion",
            "created": int(asyncio.get_event_loop().time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": ollama_response["message"]["content"]
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": ollama_response.get("prompt_eval_count", 0),
                "completion_tokens": ollama_response.get("eval_count", 0),
                "total_tokens": ollama_response.get("prompt_eval_count", 0) + ollama_response.get("eval_count", 0)
            }
        }
    
    async def _stream_chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """Streaming chat completion"""
        request_payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature
            }
        }
        
        if max_tokens:
            request_payload["options"]["num_predict"] = max_tokens
        
        async with self.client.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json=request_payload
        ) as response:
            response.raise_for_status()
            
            async for line in response.aiter_lines():
                if line:
                    try:
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            # Convert Ollama streaming format to OpenAI format
                            yield {
                                "id": f"chatcmpl-{hash(str(messages))}"[:28],
                                "object": "chat.completion.chunk",
                                "created": int(asyncio.get_event_loop().time()),
                                "model": model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "content": data["message"]["content"]
                                    },
                                    "finish_reason": "stop" if data.get("done", False) else None
                                }]
                            }
                    except json.JSONDecodeError:
                        continue
    
    async def list_models(self) -> List[str]:
        """List available models from Ollama"""
        try:
            response = await self.client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        except Exception as e:
            logger.error(f"Error listing Ollama models: {e}")
            return ["llama2", "mistral", "codellama"]  # Default models
    
    async def health_check(self) -> bool:
        """Check if Ollama service is available"""
        try:
            response = await self.client.get(f"{self.base_url}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            return False
    
    async def pull_model(self, model_name: str) -> bool:
        """Pull a model if not available"""
        try:
            response = await self.client.post(
                f"{self.base_url}/api/pull",
                json={"name": model_name},
                timeout=300.0  # Model pulling can take time
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error pulling model {model_name}: {e}")
            return False


class LocalModelClient:
    """
    Drop-in replacement for OpenAI client that routes to local models
    """
    
    def __init__(self, base_url: str = None):
        self.provider = OllamaModelProvider(base_url)
    
    async def __aenter__(self):
        await self.provider.__aenter__()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.provider.__aexit__(exc_type, exc_val, exc_tb)
    
    @property
    def chat(self):
        """Chat completions interface"""
        return ChatCompletions(self.provider)
    
    async def list_models(self):
        """List available models"""
        models = await self.provider.list_models()
        return {"data": [{"id": model, "object": "model"} for model in models]}


class ChatCompletions:
    """Chat completions interface"""
    
    def __init__(self, provider: OllamaModelProvider):
        self.provider = provider
    
    async def create(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream: bool = False,
        **kwargs
    ):
        """Create chat completion"""
        return await self.provider.chat_completion(
            model=model,
            messages=messages,
            stream=stream,
            **kwargs
        )