# core/ai_client/openai_client.py
import base64
import mimetypes
import logging
from typing import List, Dict, Any, Tuple

# Use AsyncOpenAI for non-blocking network I/O
from openai import AsyncOpenAI, OpenAIError, APITimeoutError

# Import the new base class and SYSTEM_PROMPT
from core.ai_client.base import AIClientBase, SYSTEM_PROMPT

logger = logging.getLogger(__name__)

class OpenAIClient(AIClientBase):
    """Handles OpenAI API interactions using AsyncOpenAI."""
    def __init__(self):
        # Initialize the base class with the provider name
        super().__init__("OpenAI")

    # --- Implementation of Abstract Methods ---

    def _init_client_sdk(self, api_key: str):
        # Initialize AsyncOpenAI client
        # Add a slight buffer to the SDK timeout beyond our application timeout
        self.client = AsyncOpenAI(api_key=api_key, timeout=self.timeout + 2)

    def _update_client_settings(self):
        # Update timeout if client exists
        if self.client:
            self.client.timeout = self.timeout + 2

    async def _call_api(self, model: str, image_paths: List[str], user_text: str) -> str:
        payload = self._prepare_payload(image_paths, user_text, model)
        # Await the async API call
        response = await self.client.chat.completions.create(**payload)
        
        content = response.choices[0].message.content
        return content

    def is_timeout_error(self, error: Exception) -> bool:
        return isinstance(error, APITimeoutError)

    # --- OpenAI Specific Payload Preparation ---

    def _prepare_payload(self, image_paths: List[str], user_text: str, model: str) -> Dict[str, Any]:
        content = []
        if user_text:
            content.append({"type": "text", "text": user_text})

        for path in image_paths[:self.max_images]:
            try:
                encoded_string, mime_type = self._encode_image(path)
                
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{encoded_string}",
                        "detail": "high" # High detail for charts
                    }
                })
            except IOError as e:
                logger.error(f"Error reading image file {path}: {e}")
                raise
        
        payload = {
            "model": model,
            "response_format": {"type": "json_object"}, # OpenAI specific JSON enforcement
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content}
            ],
            "temperature": 0.2 # Low temperature for analytical tasks
        }
        
        # FIX: Handle different token parameter names for newer models
        if "gpt-4o" in model or "gpt-5" in model:
            payload["max_tokens"] = 4096 # Newer models often use this name and have higher limits
        else:
            payload["max_tokens"] = 1000
            
        return payload

    def _encode_image(self, path: str) -> Tuple[str, str]:
        mime_type = mimetypes.guess_type(path)[0] or 'image/webp'
        with open(path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8'), mime_type