# core/ai_client/base.py
from __future__ import annotations
import time
import logging
import json
import base64
import mimetypes
import re
import os
from pathlib import Path
from abc import ABC, abstractmethod
from typing import List, Optional, Any, Tuple

from pydantic import ValidationError
from core.config import settings_manager
from core.models import AnalysisResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
你是一位嚴謹的台股分析助手。依據走勢圖（可能包含日K、30/60分、量能、均線、VWAP、五檔）與使用者提供的數字，產出**可執行**的計畫。

【通用步驟】
1) 讀圖：當前價、VWAP、均線、高低點、量能。
2) 判斷：結構（趨勢/箱體/型態/位置關係）、動能（放量/縮量、延續/鈍化）。
3) 計畫：入場觸發與**明確停損價**（數字），停利目標可多段。

【分析模式】
- 當沖：同時產出 long/short；比較後給出 bias（多/空/觀望）；若為多或空，將該方向的 entry/stop 同步到頂層。
- 短波投資：偏重日K與 30~60分結構、隔日~數日持倉；同樣給出 bias，可同時提供 long/short 與分批目標；可 `hold_overnight = true`。

【股票識別規範（極重要）】
- 你會在使用者訊息開頭看見可能的中繼資料（meta），例如：
  【股票】代號=2330; 名稱=台積電
- 若 meta 中提供 `代號` 或 `名稱`，**視為權威來源**：請將其分別填入輸出 JSON 的 `"symbol"` 與 `"name"`，不可擅改。
- 若 meta 未提供，請嘗試從以下來源辨識：
  1) 圖表標題、頁籤、浮水印、左上角品名（常見：券商看盤軟體標題列）。
  2) 影像檔名（例：`2330_TSMC_5m.png`、`台積電-2330-日K.webp`）。
- 仍無法判斷時，`symbol` 或 `name` 允許為 `null`，但需在 `notes` 簡述原因，並補充：
  - `symbol_guess_candidates`: 可能的代號陣列（如從圖中文字/檔名擷取到的 4 碼），無則給空陣列。
  - `name_guess_candidates`: 可能的名稱陣列，無則給空陣列。

【位階判斷（務必填寫 position）】
- 盡量利用「#numbers」區塊的數字；若無，從圖推定，缺值= null。
- 量化欄位定義：
  - pct_from_52w_high = (price - 52wHigh) / 52wHigh
  - pct_from_52w_low = (price - 52wLow) / 52wLow
  - pct_from_ma200 = (price - MA200) / MA200
  - pct_from_ma60  = (price - MA60)  / MA60
  - avwap_from_pivot = (price - AVWAP) / AVWAP
  - volume_20d_ratio = todayVol / avg20Vol
- **位階等級**（指引，非絕對）：
  - 低位階：位於 52w 區間下 30% 以內，或接近/下穿 MA200（±3%），或 AVWAP 下方但出現收復跡象；RSI14 常 <55。
  - 高位階：位於 52w 區間上 20% 以內，或高於 MA200 超過 ~10%，連續長紅或加速段；RSI14 常 >60。
  - 其餘歸為 中位階。
- 將判斷結果填入 `position.level`，並盡量填滿各數值欄位。

【低位階買入評估（必做）】
- 若 `position.level = 低位階`，請產出：
  - `buy_suitable`: 是否適合買入（結構有無頸線/箱底、是否收復關鍵均線/VWAP、量能是否轉強）。
  - `entry_candidates`: 2~3 個方案（突破、回測、VWAP/AVWAP收復等），每個包含 entry_price、stop_loss、note。
  - `buy_reason`: 精要說明風報、結構、動能與風險。
- 若非低位階，`buy_suitable=false`，簡述理由（例如：高位階風險/乖離過大/量價失衡）。

【五段重點（務必填寫）】
- `structure`、`momentum`、`key_levels`（盡量給**數字**）、`trade_plan`（總結）、`bonus_signals`
- 另外填 `plan_breakdown`（進場/停損/停利）與 `operation_cycle`（動能/成交量/法人籌碼/籌碼集中度）

【容錯】
- 圖/數據不足時，允許數值為 null、confidence 降低並在 notes 說明。

【輸出（只輸出 JSON）】
{
  "symbol": string | null,
  "name": string | null,

  "bias": "多" | "空" | "觀望",
  "entry_price": number | null,
  "stop_loss": number | null,
  "hold_overnight": true | false | null,

  "structure": string,
  "momentum": string,
  "key_levels": string,
  "trade_plan": string,
  "bonus_signals": string,

  "plan_breakdown": {"entry": string, "stop": string, "take_profit": string} | null,
  "operation_cycle": {"momentum": string, "volume": string, "institutions": string, "concentration": string} | null,

  "position": {
    "level": "低位階" | "中位階" | "高位階",
    "pct_from_52w_high": number | null,
    "pct_from_52w_low": number | null,
    "pct_from_ma200": number | null,
    "pct_from_ma60": number | null,
    "avwap_from_pivot": number | null,
    "rsi14": number | null,
    "rsi_rank_1y": number | null,
    "volume_20d_ratio": number | null,
    "near_vpoc": true | false | null
  } | null,

  "buy_suitable": true | false | null,
  "buy_reason": string,
  "entry_candidates": [
    {"label": string, "entry_price": number | null, "stop_loss": number | null, "note": string}
  ],

  "long": {"entry_price": number | null, "stop_loss": number | null, "targets": number[], "plan": string} | null,
  "short": {"entry_price": number | null, "stop_loss": number | null, "targets": number[], "plan": string} | null,

  "rationale": string,
  "risk_score": 1 | 2 | 3 | 4 | 5,
  "confidence": number,
  "notes": string,

  "symbol_guess_candidates": string[],
  "name_guess_candidates": string[]
}
"""

class AIClientBase(ABC):
    def __init__(self, provider_name: str):
        self.provider_name = provider_name
        self.client = None
        self.api_key: Optional[str] = None
        self.load_settings()
        settings_manager.settings_changed.connect(self.load_settings)

    # ---------- settings / init ----------
    def get_api_key(self) -> Optional[str]:
        return settings_manager.get_api_key(self.provider_name)

    def initialize_client(self):
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
        if self.client:
            self._update_client_settings()
        return bool(self.client)

    @abstractmethod
    def _init_client_sdk(self, api_key: str):
        """由子類別建立 self.client（例如 OpenAI.OpenAI(...)）。"""
        pass

    def _update_client_settings(self):
        """子類可覆寫：例如更新 base_url、timeout 等。"""
        pass

    def load_settings(self):
        self.strategy = settings_manager.get("AI/Strategy")
        self.timeout = settings_manager.get_int("AI/Timeout", settings_manager.get_int("AI/TimeoutSec", 60))
        self.max_images = settings_manager.get_int("AI/MaxImages", 5)
        self.model_fast = settings_manager.get(f"{self.provider_name}/ModelFast")
        self.model_deep = settings_manager.get(f"{self.provider_name}/ModelDeep")
        self.initialize_client()

    # ---------- strategy / model ----------
    def determine_model(self, image_count: int, user_text: str) -> str:
        if self.strategy == "Fast":
            return self.model_fast or self.model_deep
        if self.strategy == "Deep":
            return self.model_deep or self.model_fast
        if (image_count > 3 or self.timeout < 6) and self.model_fast:
            return self.model_fast
        if image_count == 1 and user_text.strip() and self.model_deep:
            return self.model_deep
        return self.model_deep or self.model_fast

    # ---------- public entry ----------
    async def analyze(self, image_paths: List[str], user_text: str) -> AnalysisResult:
        if not self.client and not self.initialize_client():
            raise RuntimeError(f"{self.provider_name} Client not initialized (check API key).")

        # 從使用者文字擷取 meta（代號/名稱），留待後處理強制補齊
        meta_symbol, meta_name = self._extract_symbol_name_meta(user_text)

        user_text_aug = self._augment_user_text(image_paths, user_text)
        model = self.determine_model(len(image_paths), user_text_aug)
        if not model:
            raise RuntimeError(f"{self.provider_name} models are not configured in settings.")

        logger.info(f"Starting analysis with {self.provider_name}. Strategy: {self.strategy}. Model: {model}")
        try:
            start = time.time()
            content = await self._call_api(model, image_paths, user_text_aug)
            dur = time.time() - start
            logger.info(f"API done in {dur:.2f}s (model={model})")

            # --- 後處理：確保 symbol/name 存在 ---
            content = self._ensure_symbol_name(content, meta_symbol, meta_name, image_paths)

            result = self._parse_and_validate(content)
            result.model_used = f"{self.provider_name}/{model}"
            result.response_time = dur
            return result
        except Exception as e:
            if self.is_timeout_error(e):
                if model != self.model_fast and self.model_fast:
                    logger.warning(f"Timeout on {model}. Retrying with fast model {self.model_fast}.")
                    start = time.time()
                    content = await self._call_api(self.model_fast, image_paths, user_text_aug)
                    dur = time.time() - start
                    content = self._ensure_symbol_name(content, meta_symbol, meta_name, image_paths)
                    result = self._parse_and_validate(content)
                    result.model_used = f"{self.provider_name}/{self.model_fast}"
                    result.response_time = dur
                    return result
                raise RuntimeError(f"API 請求超時（{model}）。請檢查網路或增加等待時間。")
            raise RuntimeError(f"分析失敗 ({self.provider_name}): {e}")

    # ---------- helpers ----------
    def _augment_user_text(self, image_paths: List[str], user_text: str) -> str:
        # 保留你原有文本，不再自動加入分析模式提示，避免干擾 meta 行的辨識
        return (user_text or "").strip()

    def _extract_symbol_name_meta(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        從使用者文字中擷取：
        形如：【股票】代號=2330; 名稱=台積電
        """
        if not text:
            return None, None
        m = re.search(r"【股票】\s*代號\s*=\s*([^;\\\n]+)\s*;\s*名稱\s*=\s*([^\n]+)", text)
        if not m:
            return None, None
        sym = m.group(1).strip()
        name = m.group(2).strip()
        sym = None if sym.lower() == "null" else sym
        name = None if name.lower() == "null" else name
        return sym, name

    def _guess_from_paths(self, image_paths: List[str]) -> Tuple[Optional[str], Optional[str]]:
        """從影像檔名猜測 4 碼代號與可能名稱片段。"""
        sym = None
        name = None
        for p in image_paths:
            fname = os.path.basename(p)
            base, _ = os.path.splitext(fname)
            # 代號：第一個 4 碼數字
            m = re.search(r'(?<!\d)(\d{4})(?!\d)', base)
            if m and not sym:
                sym = m.group(1)
            # 名稱：去除數字與常見符號後保留中英文片段
            tmp = re.sub(r'[\d_@()\-\[\]{}]+', ' ', base)
            tmp = re.sub(r'\s+', ' ', tmp).strip()
            m2 = re.search(r'([A-Za-z]{2,}|[\u4e00-\u9fa5]{2,})', tmp)
            if m2 and not name:
                name = m2.group(1)
            if sym and name:
                break
        return sym, name

    def _ensure_symbol_name(self, content: str, meta_symbol: Optional[str], meta_name: Optional[str], image_paths: List[str]) -> str:
        """
        解析模型 JSON 字串；若缺 symbol/name 或為空，使用 meta 或檔名猜測補齊，再回寫為 JSON 字串。
        """
        if not content:
            return content

        # 嘗試剝除 ```json 區塊
        txt = content.strip()
        if txt.startswith("```json"):
            txt = txt.removeprefix("```json").removesuffix("```").strip()

        try:
            data = json.loads(txt)
            if not isinstance(data, dict):
                return content
        except Exception:
            # 若非 JSON，就原樣返回（讓 _parse_and_validate 回報錯）
            return content

        # 讀現有值
        symbol = data.get("symbol")
        name = data.get("name")

        # 若缺，先用 meta 補
        if not symbol and meta_symbol:
            symbol = meta_symbol
        if not name and meta_name:
            name = meta_name

        # 還是缺，從檔名猜
        if not symbol or not name:
            guess_sym, guess_name = self._guess_from_paths(image_paths)
            if not symbol and guess_sym:
                symbol = guess_sym
            if not name and guess_name:
                name = guess_name

        # 寫回去（至少要有 key，沒有就填 null）
        data["symbol"] = symbol if symbol else None
        data["name"] = name if name else None

        # 若模型有提供 candidates 欄位則沿用，沒有就可選擇不加；這裡不強制新增
        return json.dumps(data, ensure_ascii=False)

    def _parse_and_validate(self, content: Optional[str]) -> AnalysisResult:
        try:
            if not content:
                raise ValueError("API returned empty response")
            txt = content.strip()
            if txt.startswith("```json"):
                txt = txt.removeprefix("```json").removesuffix("```").strip()
            return AnalysisResult.model_validate_json(txt)
        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"API response parsing/validation failed: {e}. Snippet: {content[:200] if content else 'Empty'}")

    # ---------- OpenAI 呼叫（優先 Responses API；必要時直接 HTTP） ----------
    async def _call_api(self, model: str, image_paths: List[str], user_text: str) -> str:
        def _is_new_series(name: str) -> bool:
            n = (name or "").lower()
            return n.startswith("gpt-5") or n.startswith("o4") or n.startswith("gpt-4.1")

        if _is_new_series(model):
            limit = settings_manager.get_int("AI/MaxOutputTokens", 900) or None
            user_content = [{"type": "input_text", "text": (user_text or "請嚴格依系統指令輸出 JSON。")}]
            for p in image_paths[: self.max_images]:
                data_uri = self._path_to_data_uri(p)
                user_content.append({"type": "input_image", "image_url": data_uri})

            payload = {
                "model": model,
                "instructions": SYSTEM_PROMPT,
                "input": [{"role": "user", "content": user_content}],
            }
            if limit:
                payload["max_output_tokens"] = limit

            if getattr(self.client, "responses", None):
                resp = await self._maybe_async(self.client.responses.create, **payload)
                text = getattr(resp, "output_text", None)
                if text:
                    return text
                if hasattr(resp, "output") and resp.output:
                    try:
                        return resp.output[0].content[0].text
                    except Exception:
                        pass
                try:
                    data = resp.dict() if hasattr(resp, "dict") else None
                    if data:
                        return self._extract_text_from_responses_json(data)
                except Exception:
                    pass
                raise RuntimeError("無法從 Responses API 回傳物件中擷取文字。")

            try:
                import httpx
            except Exception:
                httpx = None
            if httpx is None:
                raise RuntimeError("找不到 responses 介面且無 httpx 可用，無法呼叫 /v1/responses。")

            base_url = getattr(getattr(self.client, "_client", None), "base_url", None)
            base_url = str(base_url).rstrip("/") if base_url else "https://api.openai.com/v1"
            api_key = self.api_key or self.get_api_key()
            if not api_key:
                raise RuntimeError("OpenAI API Key 未設定。")

            url = f"{base_url}/responses"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            timeout = settings_manager.get_int("AI/Timeout", 60) or 60
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code} {r.text}")
                data = r.json()
                text = self._extract_text_from_responses_json(data)
                if not text:
                    raise RuntimeError(f"Responses API 回傳無法解析：{data}")
                return text

        # 回退：Chat Completions（不帶 *tokens）
        user_parts = [{"type": "text", "text": (user_text or "請嚴格依系統指令輸出 JSON。")}]
        for p in image_paths[: self.max_images]:
            data_uri = self._path_to_data_uri(p)
            user_parts.append({"type": "image_url", "image_url": {"url": data_uri}})

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_parts},
        ]
        kwargs = dict(model=model, messages=messages, temperature=0.2)
        resp = await self._maybe_async(self.client.chat.completions.create, **kwargs)
        return resp.choices[0].message.content

    def _extract_text_from_responses_json(self, data: dict) -> Optional[str]:
        if "output_text" in data and isinstance(data["output_text"], str):
            return data["output_text"]
        try:
            output = data.get("output") or data.get("response", {}).get("output")
            if isinstance(output, list) and output:
                content = output[0].get("content")
                if isinstance(content, list) and content:
                    txt = content[0].get("text")
                    if isinstance(txt, str):
                        return txt
        except Exception:
            pass
        if "content" in data and isinstance(data["content"], str):
            return data["content"]
        return None

    # ---------- timeout 判斷 ----------
    def is_timeout_error(self, error: Exception) -> bool:
        txt = str(error).lower()
        if "timeout" in txt or "timed out" in txt:
            return True
        try:
            import httpx
            if isinstance(error, (httpx.ReadTimeout, httpx.ConnectTimeout)):
                return True
        except Exception:
            pass
        return False

    # ---------- utilities ----------
    def _path_to_data_uri(self, path: str) -> str:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        mime, _ = mimetypes.guess_type(str(p))
        mime = mime or "image/png"
        b = p.read_bytes()
        b64 = base64.b64encode(b).decode("ascii")
        return f"data:{mime};base64,{b64}"

    async def _maybe_async(self, fn, **kw):
        ret = fn(**kw)
        if hasattr(ret, "__await__"):
            return await ret
        return ret
