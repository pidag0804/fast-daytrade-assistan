from pydantic import BaseModel, Field
from typing import Optional, Literal

class AnalysisResult(BaseModel):
    """Schema for the GPT analysis response."""
    bias: Literal["多", "空", "觀望"]
    entry_price: Optional[float] = Field(None, description="建議入場價位")
    stop_loss: Optional[float] = Field(None, description="明確停損價位")
    hold_overnight: Optional[bool] = Field(None, description="是否適合留倉做短波")
    rationale: str = Field(..., description="分析理由與依據")
    risk_score: Literal[1, 2, 3, 4, 5] = Field(..., description="風險分數 (1低風險、5高風險)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="信心指數")
    notes: str = Field("", description="備註或需要的補充資訊")
    
    # Metadata added by the client (Optional for the GPT response, but useful internally)
    model_used: Optional[str] = None
    response_time: Optional[float] = None