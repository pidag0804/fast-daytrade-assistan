# core/gpt_client.py
from __future__ import annotations
import os
import logging
from dataclasses import dataclass
from typing import List, Tuple

from .prompts import SYSTEM_PROMPT  # 若你的路徑不同，請調整
from utils.image_utils import file_to_png_data_uri

# .env 支援（可省略）
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

log = logging.getLogger(__name__)

@dataclass
class SpeedConfig:
    mode: str                 # "Auto" / "Fast" / "Balanced" / "Deep"
    models: dict              # {"Fast": "...", "Balanced": "...", "Deep": "..."}

class GPTClient:
    """
    對 OpenAI / 相容 API 的薄封裝：
    - GPT-5: Chat Completions → 使用 max_completion_tokens
             Responses       → 使用 max_output_tokens
    - 其他舊模型：優先 max_tokens（若被拒，再自動切換）
    - 自動處理多張圖（image_url / input_image），並回傳 (model, text)
    """
    def __init__(self, speed_cfg: SpeedConfig, timeout: float = 40.0):
        self.speed_cfg = speed_cfg
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("缺少 OPENAI_API_KEY，請於環境變數或 .env 設定。")

        # OpenAI SDK ≥ 1.x
        from openai import OpenAI
        # 可在此調 base_url = os.getenv("OPENAI_BASE_URL", None)
        self.client = OpenAI(api_key=api_key, timeout=timeout)

    # ---------- public ----------
    def analyze(self, image_paths: List[str]) -> Tuple[str, str]:
        if not image_paths:
            raise ValueError("未提供任何圖片。")

        model = self._select_model(image_paths)
        log.info("Starting analysis. Strategy: %s. Selected Model: %s", self.speed_cfg.mode, model)

        # 先嘗試 Chat Completions（支援 vision）
        try:
            text = self._chat_completions(model, image_paths)
            return model, text
        except Exception as e1:
            log.warning("Chat Completions 失敗，嘗試 Responses API。原因：%s", e1)

        # 再嘗試 Responses API（multimodal）
        text = self._responses_api(model, image_paths)
        return model, text

    # ---------- internal ----------
    def _select_model(self, image_paths: List[str]) -> str:
        # 你若已有 Auto 規則，可保留；這裡簡化以 Deep 為 GPT-5、Fast 為更省的模型
        mode = (self.speed_cfg.mode or "Auto").strip()
        m = self.speed_cfg.models or {}
        if mode == "Fast":
            return m.get("Fast") or "gpt-4o-mini"
        elif mode == "Balanced":
            return m.get("Balanced") or "gpt-4o"
        elif mode == "Deep":
            return m.get("Deep") or "gpt-5"
        else:
            # Auto：簡化若圖多就 Deep，否則 Balanced
            if len(image_paths) >= 3:
                return m.get("Deep") or "gpt-5"
            return m.get("Balanced") or "gpt-4o"

    def _build_chat_messages(self, image_paths: List[str]) -> list:
        # Chat Completions 用法：type=image_url
        content = [{"type": "text", "text": "以下是多張技術圖（含日K與5分K）。請依系統提示輸出五段落結論。"}]
        for p in image_paths:
            data_uri = file_to_png_data_uri(p)  # 無論原始格式，統一轉 png data URI
            content.append({"type": "image_url", "image_url": {"url": data_uri}})
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]

    def _build_responses_input(self, image_paths: List[str]) -> list:
        # Responses API 用法：type=input_image
        parts = [{"type": "text", "text": "以下是多張技術圖（含日K與5分K）。請依系統提示輸出五段落結論。"}]
        for p in image_paths:
            data_uri = file_to_png_data_uri(p)
            parts.append({"type": "input_image", "image_url": {"url": data_uri}})
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": parts},
        ]

    def _chat_completions(self, model: str, image_paths: List[str]) -> str:
        msgs = self._build_chat_messages(image_paths)
        prefer_new_name = model.startswith("gpt-5")
        # 先用新的參數名（GPT-5）
        kwargs = dict(model=model, messages=msgs, temperature=0.2)
        if prefer_new_name:
            kwargs["max_completion_tokens"] = 700
        else:
            kwargs["max_tokens"] = 700

        try:
            resp = self.client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content
        except Exception as e:
            s = str(e)
            # 若伺服器回 unsupported_parameter，改用另一個名稱重試一次
            if "unsupported_parameter" in s or "max_tokens" in s or "max_completion_tokens" in s:
                if "max_tokens" in kwargs:
                    kwargs.pop("max_tokens", None)
                    kwargs["max_completion_tokens"] = 700
                else:
                    kwargs.pop("max_completion_tokens", None)
                    kwargs["max_tokens"] = 700
                resp = self.client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content
            raise

    def _responses_api(self, model: str, image_paths: List[str]) -> str:
        inp = self._build_responses_input(image_paths)
        try:
            resp = self.client.responses.create(
                model=model,
                input=inp,
                max_output_tokens=700,     # Responses 的參數名
            )
        except Exception as e:
            # 某些代理/相容服務用 "max_tokens"；自動退回一次
            s = str(e)
            if "max_output_tokens" in s and "unsupported" in s.lower():
                resp = self.client.responses.create(
                    model=model,
                    input=inp,
                    max_tokens=700,
                )
            else:
                raise

        # 取文字（兼容不同 SDK 版本）
        text = getattr(resp, "output_text", "") or ""
        if text:
            return text
        out = getattr(resp, "output", None)
        if out:
            chunks = []
            for it in out:
                if getattr(it, "type", "") == "output_text":
                    chunks.append(it.text)
            if chunks:
                return "".join(chunks)
        # 最後保底
        return str(resp)
