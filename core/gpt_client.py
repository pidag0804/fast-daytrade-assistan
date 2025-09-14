import base64
import time
import json
import logging
import mimetypes
from typing import List, Dict, Any, Tuple
# Use AsyncOpenAI for non-blocking network I/O
from openai import AsyncOpenAI, OpenAIError, APITimeoutError
from pydantic import ValidationError
from core.config import settings_manager
from core.models import AnalysisResult

logger = logging.getLogger(__name__)

# --- System Prompt ---
SYSTEM_PROMPT = """
你是一位嚴謹的台股當沖分析助手。你會根據使用者提供的「當下分K走勢截圖、成交量、委買委賣/五檔（若有）、均線/MACD/KD 等提示（若能看見）」來判斷：
1) 今日此標的適合做「多 / 空 / 觀望」何者。
2) 建議入場價位（明確數字）。
3) 明確停損價位（明確數字，並簡述邏輯）。
4) 是否適合留倉做短波（是/否，必要時列出條件，如量能、均線排列、關鍵價位）。

請務必：
- 優先參考影像中的最近 30~60 分鐘變化與關鍵價。
- 簡明扼要，避免贅述；所有關鍵價位皆需有依據（前高/前低、均線、缺口、趨勢線、VWAP 等）。
- 產出 **嚴格 JSON**（UTF-8，不要有多餘文字），符合下述 schema。
- 若影像無法判讀數據，請以 `"confidence": 0.0` 回報並於 `"notes"` 說明需要的補充資訊。

JSON Schema:
{
  "bias": "多" | "空" | "觀望",
  "entry_price": number | null,
  "stop_loss": number | null,
  "hold_overnight": true | false | null,
  "rationale": string,          
  "risk_score": 1 | 2 | 3 | 4 | 5,  
  "confidence": number,          
  "notes": string                
}
"""

# --- GPT Client Logic ---
class GPTClient:
    """Handles OpenAI API interactions using AsyncOpenAI."""
    def __init__(self):
        self.client = None
        self.api_key = None
        self.load_settings()
        settings_manager.settings_changed.connect(self.load_settings)

    def initialize_client(self):
        api_key = settings_manager.get_api_key()
        if not api_key:
            self.client = None
            self.api_key = None
            return False
        
        if api_key != self.api_key:
            try:
                # Initialize AsyncOpenAI client
                self.client = AsyncOpenAI(api_key=api_key, timeout=self.timeout + 2)
                self.api_key = api_key
                return True
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                self.client = None
                self.api_key = None
                return False
        return bool(self.client)

    def load_settings(self):
        self.model_fast = settings_manager.get("OpenAI/ModelFast")
        self.model_deep = settings_manager.get("OpenAI/ModelDeep")
        self.strategy = settings_manager.get("OpenAI/Strategy")
        self.timeout = settings_manager.get("OpenAI/Timeout")
        self.max_images = settings_manager.get("OpenAI/MaxImages")
        # Re-initialize if key changed or client doesn't exist
        self.initialize_client()
        if self.client:
            self.client.timeout = self.timeout + 2

    def determine_model(self, image_count: int, user_text: str) -> str:
        """Auto Speed Strategy implementation."""
        if self.strategy == "Fast":
            return self.model_fast
        if self.strategy == "Deep":
            return self.model_deep

        # Auto Strategy
        # Rule 1: Many images (>3) or short timeout (<4s) -> Fast
        if image_count > 3 or self.timeout < 4:
            return self.model_fast
        
        # Rule 2: Single image + text -> Deep
        if image_count == 1 and user_text.strip():
            return self.model_deep
            
        # Default Auto: Deep (Standard)
        return self.model_deep

    async def analyze(self, image_paths: List[str], user_text: str) -> AnalysisResult:
        if not self.client:
            if not self.initialize_client():
                raise RuntimeError("OpenAI Client not initialized (check API key).")

        # Settings might have changed since last run, ensure they are up-to-date for this request
        self.load_settings() 
        
        model = self.determine_model(len(image_paths), user_text)
        logger.info(f"Starting analysis. Strategy: {self.strategy}. Selected Model: {model}")

        try:
            # Await the async API call
            return await self._attempt_analysis(model, image_paths, user_text)
        
        except APITimeoutError as e:
            # Timeout Fallback: If not already fast, retry with fast model
            if model != self.model_fast:
                logger.warning(f"Timeout occurred with {model}. Retrying with Fast Model.")
                return await self._attempt_analysis(self.model_fast, image_paths, user_text)
            else:
                raise RuntimeError(f"API 請求超時 (使用快速模型依然失敗)。請檢查網路或增加等待時間。")
        except (OpenAIError, ValidationError, ValueError) as e:
             raise RuntimeError(f"分析失敗: {e}")

    async def _attempt_analysis(self, model: str, image_paths: List[str], user_text: str) -> AnalysisResult:
        start_time = time.time()
        payload = self._prepare_payload(image_paths, user_text, model)
        
        # Await the async API call
        response = await self.client.chat.completions.create(**payload)
        
        end_time = time.time()
        response_time = end_time - start_time
        logger.info(f"API call completed in {response_time:.2f} seconds. Model: {model}")
        
        result = self._parse_response(response)
        result.model_used = model
        result.response_time = response_time
        return result

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
        
        return {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content}
            ],
            "max_tokens": 1000,
            "temperature": 0.2 # Low temperature for analytical tasks
        }

    def _encode_image(self, path: str) -> Tuple[str, str]:
        mime_type = mimetypes.guess_type(path)[0] or 'image/webp'
        with open(path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8'), mime_type

    def _parse_response(self, response) -> AnalysisResult:
        try:
            content = response.choices[0].message.content
            if not content:
                raise ValueError("API returned an empty response.")
            # Pydantic v2+ can validate JSON strings directly
            return AnalysisResult.model_validate_json(content)
        except ValidationError as e:
            # Catch JSON decode errors and validation errors
            raise ValueError(f"API response parsing/validation failed: {e}. Response: {content[:200] if content else 'Empty'}...")

# Global instance
gpt_client = GPTClient()