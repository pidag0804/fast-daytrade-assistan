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
from typing import List, Optional, Tuple

from pydantic import ValidationError
from core.config import settings_manager
from core.models import AnalysisResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
你是一位嚴謹的台股分析助手。依據走勢圖（可能包含日K、30/60分、量能、均線、VWAP、五檔、BBand）與使用者提供的數字，產出**可執行**的計畫。

【通用步驟】
1) 讀圖：當前價、VWAP、AVWAP、均線、高低點、量能、BBand。
2) 判斷：
    - **多時間框架(MTF)**：結合長線（如 5/15分K）判斷趨勢與結構，短線（如 1分K）找精準進場點。
    - **結構**：趨勢、箱體、型態、位置關係。
    - **動能**：放量/縮量、延續/鈍化。
3) 計畫：
    - **入場觸發**：明確的觸發條件。
    - **停損**：**明確停損價**（數字），優先採技術停損（如關鍵高低點外緣），或以 ATR/布林帶寬度自適應調整。若無明確參考，才預設 2% 為上限。
    - **停利**：可設 2~3 段目標（如 1R, 2R）。

【當沖方案（必填、請放在輸出重心）】
- 一律視為「當日內平倉」，`hold_overnight=false`。
- 請以 1~5 分K、VWAP/開盤AVWAP、當日高低/開盤區間(OR)/分時箱體、BBand 為核心依據。
- **在 `trade_plan` 的第一行，明確寫：`當沖方向：多|偏多|空|偏空`（四選一）**，並附一句理由。
- 同時提供 `long` 與 `short`：
  - 每個都要有 `entry_price`、`stop_loss`、`targets`。
- 比較兩方案後，設定頂層 `bias`：
  - 若方向為「偏多」→ `bias="多"`；「偏空」→ `bias="空"`；其餘依字義。
  - 若 `bias` 為多或空，請把該方向的 `entry/stop` 同步到頂層 `entry_price/stop_loss`。
- `key_levels` 盡量給出具體價位（VWAP、AVWAP、當日高低、開盤區間高低(OR)、箱體上下緣、昨高、昨低、整數關卡）。

【BBand（布林軌道）專項 — 務必提供】
- **參數調整**：預設 `period=20, dev=2`。但請依波動與分K動態評估，如：1分K 可用 20~30 週期；5分K 或高波動股可用 10~20 週期。若判讀不同，請註明。
- 請填 `bband` 物件，- 至少包含：
  - `ma`（中軌估值）、`upper`、`lower`
  - `width`：帶寬（(upper-lower)/ma，以小數表示）
  - `%b`（0~1，若超出可 <0 或 >1）
  - `squeeze`：是否為狹縮，並附 `bandwidth_rank_session`（日內帶寬分位數 0~1）。
  - **擠壓量化**：`squeeze=true` 的條件為 `width` 處於近期低點（如 `bandwidth_rank_session < 0.2`）且 MA20 走平。
  - `note`：用 1~2 句說明「走帶/擠壓/均值回歸/突破」型態與交易含義。
- **判讀與出場指引**：
  - **走帶（walking the band）**：標準為「**連續3根K棒**收盤貼近上/下軌（如 %B > 0.8 或 < 0.2），且**量能同步驗證**」。**出場規則**：順勢分段出場，直到價格**明確收盤跌破/站上中軌**為止。
  - **擠壓（squeeze）**：帶寬壓縮，預備突破。**策略切換**：在計畫中註明，一旦擠壓後出現**帶量突破**，策略應從**均值回歸（反轉）切換為順勢追蹤**。
  - **均值回歸（mean reversion）**：%B 觸及 0 或 1 且量能鈍化。**出場規則**：以**中軌/MVWAP** 為主要回歸目標。
  - **假突破**：標準為「價格衝出軌道但**收盤回帶內**，且**量能背離**（未顯著放大），**隔根K棒未延續**方向」。可反向短打，停損設於影線外緣。

【倉位控管（務必填寫）】
- 依據 `risk_score`、帶寬狀態、波動性，在 `position_size_rule` 中提供倉位建議。例如：「高風險/帶寬放大 → 輕倉」、「低風險/擠壓突破 → 標準倉位」。

【籌碼分析（若有圖）】
- 你會收到近 5/10/20/60 日的籌碼流向圖。
- 必須分析「外資」、「投信」、「散戶」的買賣超趨勢。
- **識別模式**：明確判斷並描述屬於以下哪種情境，或其他你觀察到的模式：
  1. 外資賣，投信買（土洋對作）
  2. 投信賣，外資買（土洋對作）
  3. 外資、投信同買（雙買）
  4. 外資、投信同賣（雙賣）
  5. 散戶賣，法人（任一）買（籌碼集中）
  6. 法人（任一）賣，散戶買（籌碼渙散）
- **輸出**：
  - 在 `chips` 陣列中，為每個週期（5日、10日...）新增一個物件。
  - `pattern` 欄位需簡潔描述上述模式。
  - `comment` 欄位提供你的分析洞見。
  - `score` 欄位針對該週期的籌碼健康度評分 (1-5分，5分最佳)。
  - 最後，在 `chip_score` 欄位給出一個綜合總評分 (1-5分)。

【加分訊號（務必填寫 bonus_signals）】
- 補充說明，例如：**跳空缺口**、**重大新聞**、**接近漲跌停（風險保護）**，或圖中可見的**分時籌碼/委託流向**（大單、內外盤比）等輔助信號。

【股票識別規範（極重要）】
- 使用者訊息開頭的 meta `代號`、`名稱`，**視為權威且覆蓋模型推斷**。

【位階判斷（務必填寫 position）】
- 盡量填滿數值。

【低位階買入評估（必做）】
- 若判定為低位階，產出 `entry_candidates` 與 `buy_reason`；否則 `buy_suitable=false`。

【五段重點（務必填寫）】
- `structure`、`momentum`、`key_levels`、`trade_plan`、`bonus_signals`
- 並填 `plan_breakdown` 與 `operation_cycle`

【容錯】
- 圖/數據不足時，允許數值為 `null`，`confidence` 保守；於 `notes` 說明不確定性。

【輸出（只輸出 JSON）】
{
  "symbol": string | null,
  "name": string | null,
  "bias": "多" | "空" | "觀望",
  "entry_price": number | null,
  "stop_loss": number | null,
  "hold_overnight": false,
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
  "position_size_rule": string,
  "buy_suitable": true | false | null,
  "buy_reason": string,
  "entry_candidates": [
    {"label": string, "entry_price": number | null, "stop_loss": number | null, "note": string}
  ],
  "long": {"entry_price": number | null, "stop_loss": null, "targets": number[], "plan": string} | null,
  "short": {"entry_price": number | null, "stop_loss": null, "targets": number[], "plan": string} | null,
  "bband": {
    "period": number | null,
    "dev": number | null,
    "ma": number | null,
    "upper": number | null,
    "lower": number | null,
    "width": number | null,
    "%b": number | null,
    "squeeze": true | false | null,
    "bandwidth_rank_session": number | null,
    "note": string
  },
  "rationale": string,
  "risk_score": 1 | 2 | 3 | 4 | 5,
  "confidence": number,
  "notes": string,
  "chips": [
    {
      "period": "5日",
      "foreign": -5000,
      "investment": 8000,
      "retail": -3000,
      "pattern": "外資賣，投信買",
      "comment": "投信積極承接外資賣壓，短線有支撐。",
      "score": 4
    }
  ],
  "chip_score": 4,
  "symbol_guess_candidates": [],
  "name_guess_candidates": []
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

        # 擷取 meta（代號/名稱），供後處理補齊/覆蓋
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

            # 後處理：symbol/name 覆蓋、當沖預設、欄位正規化（含 long/short.plan）
            content = self._finalize_json(content, meta_symbol, meta_name, image_paths)

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
                    content = self._finalize_json(content, meta_symbol, meta_name, image_paths)
                    result = self._parse_and_validate(content)
                    result.model_used = f"{self.provider_name}/{self.model_fast}"
                    result.response_time = dur
                    return result
                raise RuntimeError(f"API 請求超時（{model}）。請檢查網路或增加等待時間。")
            raise RuntimeError(f"分析失敗 ({self.provider_name}): {e}")

    # ---------- helpers ----------
    def _augment_user_text(self, image_paths: List[str], user_text: str) -> str:
        # 直接使用使用者文字；不再插入「分析模式」
        return (user_text or "").strip()

    def _extract_symbol_name_meta(self, text: str) -> Tuple[Optional[str], Optional[str]]:
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
        sym = None
        name = None
        for p in image_paths:
            fname = os.path.basename(p)
            base, _ = os.path.splitext(fname)
            m = re.search(r'(?<!\d)(\d{4})(?!\d)', base)
            if m and not sym:
                sym = m.group(1)
            tmp = re.sub(r'[\d_@()\-\[\]{}]+', ' ', base)
            tmp = re.sub(r'\s+', ' ', tmp).strip()
            m2 = re.search(r'([A-Za-z]{2,}|[\u4e00-\u9fa5]{2,})', tmp)
            if m2 and not name:
                name = m2.group(1)
            if sym and name:
                break
        return sym, name

    def _finalize_json(
        self,
        content: str,
        meta_symbol: Optional[str],
        meta_name: Optional[str],
        image_paths: List[str],
    ) -> str:
        """
        後處理：
        - **使用者輸入優先**：若 meta 帶入代號/名稱，直接覆蓋模型值；否則才用模型→檔名猜測補齊
        - 一律 daytrade：hold_overnight=False
        - 若 `trade_plan` 未含「當沖方向：...」，自動補一行（依 bias 推定）
        - long/short/top-level 停損缺失 → 預設 2% 停損；targets 缺失 → 補 1%、2% 兩段
        - long/short.plan 為 None → 自動生成一行摘要
        - confidence 標準化到 [0,1]；risk_score 夾到 [1,5]
        - 若 bias 回「偏多/偏空」→ 映射為「多/空」
        """
        if not content:
            return content

        txt = content.strip()
        if txt.startswith("```json"):
            txt = txt.removeprefix("```json").removesuffix("```").strip()

        try:
            data = json.loads(txt)
            if not isinstance(data, dict):
                return content
        except Exception:
            return content

        # ---- symbol/name：使用者輸入優先覆蓋 ----
        symbol = meta_symbol if meta_symbol is not None else data.get("symbol")
        name = meta_name if meta_name is not None else data.get("name")
        if not symbol or not name:
            guess_sym, guess_name = self._guess_from_paths(image_paths)
            if not symbol and guess_sym:
                symbol = guess_sym
            if not name and guess_name:
                name = guess_name
        data["symbol"] = symbol if symbol else None
        data["name"] = name if name else None

        # ---- 一律當沖 ----
        data["hold_overnight"] = False

        # ---- bias 正規化（偏多/偏空 → 多/空）----
        bias = (data.get("bias") or "").strip()
        if bias in ("偏多", "多偏", "看多偏多"):
            bias = "多"
        elif bias in ("偏空", "空偏", "看空偏空"):
            bias = "空"
        elif bias not in ("多", "空", "觀望", ""):
            tp = (data.get("trade_plan") or "")
            m = re.search(r"當沖方向：\s*(多|偏多|空|偏空)", tp)
            if m:
                bias = "多" if m.group(1) in ("多", "偏多") else "空"
        data["bias"] = bias or "觀望"

        # ---- trade_plan 首行加入方向 ----
        direction = None
        tp = (data.get("trade_plan") or "")
        m = re.search(r"當沖方向：\s*(多|偏多|空|偏空)", tp)
        if m:
            direction = m.group(1)
        else:
            if data["bias"] == "多":
                direction = "偏多"
            elif data["bias"] == "空":
                direction = "偏空"
        if direction:
            header = f"當沖方向：{direction}"
            tp = (tp or "").strip()
            data["trade_plan"] = header + ("\n" + tp if tp else "（綜合結構與動能，預設 2% 停損）")

        # ---- helpers ----
        def _to_float(x) -> Optional[float]:
            if x is None:
                return None
            try:
                return float(x)
            except Exception:
                return None

        def _norm_targets(tgts, entry: Optional[float], is_long: bool) -> list:
            arr: list[float] = []
            if isinstance(tgts, list):
                for t in tgts:
                    v = _to_float(t)
                    if v is not None:
                        arr.append(round(v, 2))
            if not arr and entry is not None:
                e = float(entry)
                arr = ([round(e * 1.01, 2), round(e * 1.02, 2)] if is_long
                       else [round(e * 0.99, 2), round(e * 0.98, 2)])
            return arr

        def _mk_plan_sentence(is_long: bool, entry: Optional[float], stop: Optional[float], tgts: list[float]) -> str:
            side_txt = "做多計畫" if is_long else "做空計畫"
            parts = []
            if entry is not None:
                parts.append(f"入場 {entry:.2f}")
            if stop is not None:
                if entry:
                    pct = abs(stop / entry - 1.0) * 100.0
                    parts.append(f"停損 {stop:.2f}（約{pct:.1f}%）")
                else:
                    parts.append(f"停損 {stop:.2f}")
            if tgts:
                tg = "、".join(f"{x:.2f}" for x in tgts)
                parts.append(f"目標 {tg}")
            if not parts:
                return f"{side_txt}：依 VWAP、當日高低與箱體關鍵價動態調整。"
            return f"{side_txt}：" + "，".join(parts) + "。"

        # ---- 預設 2% 停損 & targets & plan 文字 ----
        def _ensure_side(side: dict | None, is_long: bool) -> dict | None:
            if not isinstance(side, dict):
                return side
            entry = _to_float(side.get("entry_price"))
            stop = _to_float(side.get("stop_loss"))
            if entry is not None and stop is None:
                stop = entry * (0.98 if is_long else 1.02)
                side["stop_loss"] = round(stop, 2)
            tgts = _norm_targets(side.get("targets"), entry, is_long)
            side["targets"] = tgts
            plan = side.get("plan")
            if not isinstance(plan, str) or not plan.strip():
                side["plan"] = _mk_plan_sentence(is_long, entry, stop, tgts)
            return side

        data["long"] = _ensure_side(data.get("long"), True)
        data["short"] = _ensure_side(data.get("short"), False)

        # ---- 同步頂層 entry/stop ----
        if data["bias"] == "多" and isinstance(data.get("long"), dict):
            if data.get("entry_price") is None:
                data["entry_price"] = data["long"].get("entry_price")
            if data.get("stop_loss") is None:
                data["stop_loss"] = data["long"].get("stop_loss")
        elif data["bias"] == "空" and isinstance(data.get("short"), dict):
            if data.get("entry_price") is None:
                data["entry_price"] = data["short"].get("entry_price")
            if data.get("stop_loss") is None:
                data["stop_loss"] = data["short"].get("stop_loss")

        # ---- confidence → [0,1] ----
        conf = data.get("confidence")
        if conf is not None:
            try:
                v = float(conf)
                if v > 1.0: v /= 100.0
                if v < 0.0: v = 0.0
                if v > 1.0: v = 1.0
                data["confidence"] = v
            except Exception:
                data["confidence"] = None

        # ---- risk_score → 1..5 ----
        rs = data.get("risk_score")
        if rs is not None:
            try:
                rsv = int(rs)
                if rsv < 1: rsv = 1
                if rsv > 5: rsv = 5
                data["risk_score"] = rsv
            except Exception:
                data["risk_score"] = None

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