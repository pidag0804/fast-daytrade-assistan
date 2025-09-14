# core/ai_client/gemini_client.py
import logging
import json
import asyncio
from typing import List
import PIL.Image

import google.generativeai as genai
from google.generativeai.types import GenerationConfig
from google.api_core import exceptions as google_exceptions

from core.ai_client.base import AIClientBase, SYSTEM_PROMPT

logger = logging.getLogger(__name__)

class GeminiClient(AIClientBase):
    """Handles Google Gemini API interactions."""
    def __init__(self):
        super().__init__("Gemini")

    # --- Implementation of Abstract Methods ---

    def _init_client_sdk(self, api_key: str):
        # Configure the genai library (it manages the client internally)
        genai.configure(api_key=api_key)
        # We don't hold a single client instance like OpenAI, but we confirm configuration worked.
        self.client = True 

    async def _call_api(self, model_name: str, image_paths: List[str], user_text: str) -> str:
        
        # 1. Prepare Content Parts
        content = []
        
        # Add images (Gemini SDK accepts PIL images directly)
        for path in image_paths[:self.max_images]:
            try:
                img = PIL.Image.open(path)
                content.append(img)
            except IOError as e:
                logger.error(f"Error reading image file {path}: {e}")
                raise
        
        if user_text:
            content.append(user_text)
        
        if not content:
             content.append("請分析。")

        # 2. Configure Generation (Force JSON output)
        # Gemini 1.5 models require response_mime_type for strict JSON
        generation_config = GenerationConfig(
            temperature=0.2,
            response_mime_type="application/json"
        )

        # 3. Initialize Model with System Prompt
        # Gemini 1.5 models support system instructions directly
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=SYSTEM_PROMPT,
            generation_config=generation_config
        )

        # 4. Call API Asynchronously with Timeout
        try:
            # Use asyncio.wait_for to enforce application-level timeout robustly
            response = await asyncio.wait_for(
                model.generate_content_async(content),
                timeout=self.timeout
            )
            
            # Handle potential blocking/empty response
            if not response.text:
                 if response.prompt_feedback and response.prompt_feedback.block_reason:
                      raise ValueError(f"Gemini blocked the request. Reason: {response.prompt_feedback.block_reason}")
                 # If text is empty but not blocked, return empty string to be handled by base parser
                 return ""
                 
            return self._clean_gemini_json(response.text)

        except (asyncio.TimeoutError, google_exceptions.DeadlineExceeded):
            # Raise a generic TimeoutError which is_timeout_error will catch
            raise TimeoutError("Gemini API request timed out.")

    def is_timeout_error(self, error: Exception) -> bool:
        # Check for Python's TimeoutError (from asyncio.wait_for or raised manually) 
        # or Google's Deadline Exceeded
        return isinstance(error, (TimeoutError, asyncio.TimeoutError, google_exceptions.DeadlineExceeded))

    def _clean_gemini_json(self, content: str) -> str:
        """Cleans up specific formatting issues sometimes seen in Gemini JSON responses."""
        # Defensive coding: Gemini sometimes returns a list containing the JSON object
        try:
            data = json.loads(content)
            if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
                # If it's a list containing one dict, extract the dict
                return json.dumps(data[0])
        except json.JSONDecodeError:
            pass # If it fails, return original content and let Pydantic handle it
        return content