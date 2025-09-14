# core/ai_client/base.py
import time
import logging
import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from pydantic import ValidationError
from core.config import settings_manager
from core.models import AnalysisResult

logger = logging.getLogger(__name__)

# --- System Prompt (Updated for decisiveness and concrete values) ---
SYSTEM_PROMPT = """
你是一位嚴謹且果斷的台股當沖 (Day Trading) 分析助手。你的任務是根據提供的截圖（包含分K走勢、成交量、技術指標、五檔委買賣）產出具體的交易計畫。

請嚴格遵守以下分析步驟與輸出要求：
1. **數據解讀**：精確識別圖中的關鍵數據（當前價格、VWAP、均線、高低點、成交量趨勢）。
2. **趨勢判斷**：基於最近 30~60 分鐘的變化，判斷當下最可能的方向（多/空/觀望）。
3. **計畫制定**：制定入場與停損策略。

**輸出要求（極重要）**：
- **具體價位（必須提供）**：`entry_price` 和 `stop_loss` 原則上**必須是具體的數字 (`number`)**。
    - 如果 `bias` 為 "多" 或 "空"：填寫建議的立即入場價與停損價。
    - 如果 `bias` 為 "觀望"：填寫「條件觸發」的入場價與停損價（例如：等待突破的價位）。並在 `rationale` 中明確說明觸發條件（如：「等待價格突破 [X 價位] 且帶量」）。
- **必須提供依據**：所有關鍵價位皆需說明理由（例如：基於前高、VWAP 支撐、均線壓力等）。
- **留倉判斷**：評估是否適合留倉做短波（`hold_overnight`）。
- **嚴格 JSON**：只產出符合 Schema 的 JSON，不要有任何多餘文字或 Markdown 格式。

只有在影像品質差到完全無法判讀任何數據時，才允許 `entry_price`/`stop_loss` 為 `null`，並設定 `"confidence": 0.0` 且於 `"notes"` 說明。

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

class AIClientBase(ABC):
    """Abstract base class for AI model clients (OpenAI, Gemini, etc.)."""
    
    def __init__(self, provider_name: str):
        self.provider_name = provider_name
        self.client = None
        self.api_key = None
        # Load settings specific to this provider
        self.load_settings()
        settings_manager.settings_changed.connect(self.load_settings)

    # --- Configuration Management ---

    def get_api_key(self) -> str | None:
        """Retrieves the API key for this specific provider."""
        return settings_manager.get_api_key(self.provider_name)

    def initialize_client(self):
        """Initializes the client if the API key is available and changed."""
        api_key = self.get_api_key()
        if not api_key:
            self.client = None
            self.api_key = None
            return False
        
        if api_key != self.api_key:
            try:
                self._init_client_sdk(api_key)
                self.api_key = api_key
                return True
            except Exception as e:
                logger.error(f"Failed to initialize {self.provider_name} client: {e}")
                self.client = None
                self.api_key = None
                return False
        # If key hasn't changed, ensure client settings (like timeout) are updated
        if self.client:
             self._update_client_settings()
        return bool(self.client)

    @abstractmethod
    def _init_client_sdk(self, api_key: str):
        """Provider-specific SDK initialization."""
        pass

    def _update_client_settings(self):
        """Updates runtime settings (like timeout) on an existing client instance."""
        pass

    def load_settings(self):
        """Loads general settings and provider-specific model names."""
        # General Settings (Common)
        self.strategy = settings_manager.get("AI/Strategy")
        self.timeout = settings_manager.get("AI/Timeout")
        self.max_images = settings_manager.get("AI/MaxImages")
        
        # Provider Specific Models
        self.model_fast = settings_manager.get(f"{self.provider_name}/ModelFast")
        self.model_deep = settings_manager.get(f"{self.provider_name}/ModelDeep")

        # Re-initialize or update client
        self.initialize_client()

    # --- Strategy Logic (Common) ---

    def determine_model(self, image_count: int, user_text: str) -> str:
        """Auto Speed Strategy implementation."""
        if self.strategy == "Fast":
            return self.model_fast or self.model_deep
        if self.strategy == "Deep":
            return self.model_deep or self.model_fast

        # Auto Strategy
        # Rule 1: Many images (>3) or short timeout (<6s) -> Fast
        if (image_count > 3 or self.timeout < 6) and self.model_fast:
            return self.model_fast
        
        # Rule 2: Single image + text -> Deep
        if image_count == 1 and user_text.strip() and self.model_deep:
            return self.model_deep
            
        # Default Auto: Deep (Standard), fallback to Fast
        return self.model_deep or self.model_fast

    # --- Main Analysis Logic ---

    async def analyze(self, image_paths: List[str], user_text: str) -> AnalysisResult:
        """Main entry point for analysis, handling strategy and retries."""
        if not self.client:
            if not self.initialize_client():
                raise RuntimeError(f"{self.provider_name} Client not initialized (check API key).")

        # Ensure settings are up-to-date for this request (e.g., strategy might have changed)
        self.load_settings() 
        
        model = self.determine_model(len(image_paths), user_text)
        if not model:
             raise RuntimeError(f"{self.provider_name} models are not configured in settings.")

        logger.info(f"Starting analysis with {self.provider_name}. Strategy: {self.strategy}. Selected Model: {model}")

        try:
            return await self._attempt_analysis(model, image_paths, user_text)
        
        except Exception as e:
            # Check if the exception indicates a timeout (implementation specific)
            if self.is_timeout_error(e):
                # Timeout Fallback: If not already fast, and a distinct fast model exists, retry
                if model != self.model_fast and self.model_fast:
                    logger.warning(f"Timeout occurred with {model}. Retrying with Fast Model ({self.model_fast}).")
                    return await self._attempt_analysis(self.model_fast, image_paths, user_text)
                else:
                    raise RuntimeError(f"API 請求超時 (使用 {model} 依然失敗)。請檢查網路或增加等待時間。")
            else:
                # Handle other errors (API errors, validation errors)
                raise RuntimeError(f"分析失敗 ({self.provider_name}): {e}")

    async def _attempt_analysis(self, model: str, image_paths: List[str], user_text: str) -> AnalysisResult:
        """Performs a single analysis attempt."""
        start_time = time.time()
        
        # Await the provider-specific async API call
        response_content = await self._call_api(model, image_paths, user_text)
        
        end_time = time.time()
        response_time = end_time - start_time
        logger.info(f"API call completed in {response_time:.2f} seconds. Model: {model}")
        
        result = self._parse_and_validate(response_content)
        result.model_used = f"{self.provider_name}/{model}"
        result.response_time = response_time
        return result

    def _parse_and_validate(self, content: str | None) -> AnalysisResult:
        """Common utility to parse and validate the JSON response."""
        try:
            if not content:
                raise ValueError("API returned an empty response.")
            
            # Clean up potential markdown formatting
            if content.strip().startswith("```json"):
                content = content.strip().removeprefix("```json").removesuffix("```").strip()

            return AnalysisResult.model_validate_json(content)
        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"API response parsing/validation failed: {e}. Response: {content[:200] if content else 'Empty'}...")

    # --- Abstract Methods for Implementation ---

    @abstractmethod
    async def _call_api(self, model: str, image_paths: List[str], user_text: str) -> str:
        """Provider-specific asynchronous API call. Must return the response content string."""
        pass
    
    @abstractmethod
    def is_timeout_error(self, error: Exception) -> bool:
        """Checks if the error is a timeout exception specific to the provider."""
        pass