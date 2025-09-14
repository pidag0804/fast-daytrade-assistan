# core/ai_client/manager.py
import logging
from typing import List
from core.config import settings_manager
from core.ai_client.openai_client import OpenAIClient
from core.ai_client.gemini_client import GeminiClient
from core.models import AnalysisResult
from core.ai_client.base import AIClientBase

logger = logging.getLogger(__name__)

class AIManager:
    """
    Manages different AI providers and routes requests to the active one.
    """
    def __init__(self):
        # Initialize all supported clients. They manage their own state based on settings.
        self.clients: dict[str, AIClientBase] = {
            "OpenAI": OpenAIClient(),
            "Gemini": GeminiClient(),
        }
        self.active_provider = settings_manager.get("AI/Provider")
        settings_manager.settings_changed.connect(self.load_settings)
        
    def load_settings(self):
        new_provider = settings_manager.get("AI/Provider")
        if new_provider != self.active_provider:
            self.active_provider = new_provider
            logger.info(f"Active AI Provider changed to: {self.active_provider}")
        # Note: Individual clients also listen to settings_changed and update themselves.

    def get_active_client(self) -> AIClientBase:
        """Returns the currently selected AI client."""
        client = self.clients.get(self.active_provider)
        if not client:
            # Fallback or error if the configured provider doesn't exist
            logger.warning(f"Configured provider {self.active_provider} not found. Falling back to OpenAI.")
            return self.clients.get("OpenAI", next(iter(self.clients.values())))
        return client

    async def analyze(self, image_paths: List[str], user_text: str) -> AnalysisResult:
        """Delegates the analysis task to the active client."""
        client = self.get_active_client()
        # The client's analyze method handles initialization, strategy, and retries.
        return await client.analyze(image_paths, user_text)

# Global instance (replaces the old gpt_client global instance)
ai_manager = AIManager()