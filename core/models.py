# core/models.py
from typing import Optional, Literal, List
from pydantic import BaseModel, Field

class TradePlan(BaseModel):
    entry_price: Optional[float] = Field(None, description="入場價位")
    stop_loss: Optional[float] = Field(None, description="停損價位")
    targets: List[float] = Field(default_factory=list, description="停利目標價（可多段）")
    plan: str = Field("", description="條件、加減碼、風報比等細節")

class PlanBreakdown(BaseModel):
    entry: str = Field("", description="進場")
    stop: str = Field("", description="停損")
    take_profit: str = Field("", description="停利")

class OperationCycle(BaseModel):
    momentum: str = Field("", description="動能")
    volume: str = Field("", description="成交量")
    institutions: str = Field("", description="法人籌碼")
    concentration: str = Field("", description="籌碼集中度")

class PositionMetrics(BaseModel):
    """位階與量化指標（有數字就填，沒有可為 null）"""
    level: Literal["低位階", "中位階", "高位階"] = "中位階"
    pct_from_52w_high: Optional[float] = None   # (price - 52wHigh)/52wHigh
    pct_from_52w_low: Optional[float] = None    # (price - 52wLow)/52wLow
    pct_from_ma200: Optional[float] = None      # (price - MA200)/MA200
    pct_from_ma60: Optional[float] = None       # (price - MA60)/MA60
    avwap_from_pivot: Optional[float] = None    # (price - AVWAP)/AVWAP
    rsi14: Optional[float] = None
    rsi_rank_1y: Optional[float] = None         # 0~1 百分位排名
    volume_20d_ratio: Optional[float] = None    # 今日量 / 20日均量
    near_vpoc: Optional[bool] = None            # 是否接近VPOC/VA區

class EntryIdea(BaseModel):
    """低位階時的入場候選"""
    label: str = Field("", description="類型：突破/回測/VWAP收復等")
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    note: str = Field("", description="條件、加減碼、風報比或倉位提示")

class AnalysisResult(BaseModel):
    # 建議方向（相容舊欄位）
    bias: Literal["多", "空", "觀望"]
    entry_price: Optional[float] = Field(None, description="主方案入場價（對應建議方向）")
    stop_loss: Optional[float] = Field(None, description="主方案停損價（對應建議方向）")
    hold_overnight: Optional[bool] = Field(None, description="是否適合留倉做短波")

    # 五段重點
    structure: str = Field("", description="結構：趨勢/箱體/型態、均線、VWAP位置")
    momentum: str = Field("", description="動能：量能趨勢、K棒變化、延續/鈍化")
    key_levels: str = Field("", description="關鍵價位（支撐/壓力/VWAP/開盤/昨收/前高前低等）")
    trade_plan: str = Field("", description="總結版交易計畫（可涵蓋雙向要點）")
    bonus_signals: str = Field("", description="加分訊號：提升勝率/信心的跡象")

    # 條列與操作週期
    plan_breakdown: Optional[PlanBreakdown] = None
    operation_cycle: Optional[OperationCycle] = None

    # 位階 & 低位階買入建議
    position: Optional[PositionMetrics] = None
    buy_suitable: Optional[bool] = None
    buy_reason: str = Field("", description="為何（不）適合在低位階布局")
    entry_candidates: List[EntryIdea] = Field(default_factory=list)

    # 雙向方案
    long: Optional[TradePlan] = None
    short: Optional[TradePlan] = None

    # 其他
    rationale: str = Field(..., description="分析依據與理由")
    risk_score: Literal[1, 2, 3, 4, 5] = Field(..., description="風險分數（1低風險、5高風險）")
    confidence: float = Field(..., ge=0.0, le=1.0, description="信心指數（0~1）")
    notes: str = Field("", description="備註")

    # 中繼資料
    model_used: Optional[str] = None
    response_time: Optional[float] = None
