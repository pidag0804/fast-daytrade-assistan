from __future__ import annotations
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict

Bias = Literal["多", "空", "觀望"]
Level = Literal["低位階", "中位階", "高位階"]

class SidePlan(BaseModel):
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    targets: List[float] = Field(default_factory=list)
    plan: str = ""
    model_config = ConfigDict(extra="ignore")

class PlanBreakdown(BaseModel):
    entry: str
    stop: str
    take_profit: str
    model_config = ConfigDict(extra="ignore")

class OperationCycle(BaseModel):
    momentum: str
    volume: str
    institutions: str
    concentration: str
    model_config = ConfigDict(extra="ignore")

class PositionInfo(BaseModel):
    level: Level
    pct_from_52w_high: Optional[float] = None
    pct_from_52w_low: Optional[float] = None
    pct_from_ma200: Optional[float] = None
    pct_from_ma60: Optional[float] = None
    avwap_from_pivot: Optional[float] = None
    rsi14: Optional[float] = None
    rsi_rank_1y: Optional[float] = None
    volume_20d_ratio: Optional[float] = None
    near_vpoc: Optional[bool] = None
    model_config = ConfigDict(extra="ignore")

class BbandInfo(BaseModel):
    period: Optional[int] = None
    dev: Optional[float] = None
    ma: Optional[float] = None
    upper: Optional[float] = None
    lower: Optional[float] = None
    width: Optional[float] = None
    percent_b: Optional[float] = Field(default=None, alias="%b")
    squeeze: Optional[bool] = None
    squeeze_rank_1y: Optional[float] = None
    bandwidth_rank_session: Optional[float] = None
    note: str = ""
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

# 🔹 籌碼分析結構
class ChipAnalysis(BaseModel):
    period: str                      # 例如 "5日/10日/20日/60日"
    foreign: int                     # 外資買賣超
    investment: int                  # 投信買賣超
    retail: Optional[int] = None     # 散戶買賣推估
    pattern: str                     # 外資賣投信買、雙買、雙賣、散戶反向等
    comment: str                     # 分析評論
    score: int                       # 該情境評分 (1~5)
    model_config = ConfigDict(extra="ignore")

class AnalysisResult(BaseModel):
    # ---- 基本 ----
    symbol: Optional[str] = None
    name: Optional[str] = None

    bias: Bias
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    hold_overnight: Optional[bool] = None

    structure: str
    momentum: str
    key_levels: str
    trade_plan: str
    bonus_signals: str

    plan_breakdown: Optional[PlanBreakdown] = None
    operation_cycle: Optional[OperationCycle] = None

    position: Optional[PositionInfo] = None
    position_size_rule: str = ""

    buy_suitable: Optional[bool] = None
    buy_reason: str = ""
    entry_candidates: List[dict] = Field(default_factory=list)

    long: Optional[SidePlan] = None
    short: Optional[SidePlan] = None

    # ---- BBand ----
    bband: Optional[BbandInfo] = None

    rationale: str
    risk_score: int = Field(ge=1, le=5)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    notes: str = ""

    # ---- 籌碼分析 ----
    chips: List[ChipAnalysis] = Field(default_factory=list)
    chip_score: Optional[int] = None

    # ---- 識別 ----
    symbol_guess_candidates: List[str] = Field(default_factory=list)
    name_guess_candidates: List[str] = Field(default_factory=list)

    # ---- 系統用 ----
    model_used: Optional[str] = None
    response_time: Optional[float] = None

    model_config = ConfigDict(extra="ignore")