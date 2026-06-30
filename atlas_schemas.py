from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class AtlasSignal(BaseModel):
    ticker: str
    trigger_price: float
    current_price: float
    stop_loss: float
    target_price: float
    pillar_score: str # e.g., "4/4", "3/4"
    risk_pct: float = 0.5
    rsi: Optional[float] = None
    macd_hist: Optional[float] = None
    momentum_weak: bool = False
    fundamentals_ok: bool = False
    fundamentals_pct: Optional[float] = None
    no_earnings: bool = False
    neg_margin: bool = False
    is_too_hot: bool = False
    pct_over_ema: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.now)

class AtlasTrade(BaseModel):
    trade_id: int
    ticker: str
    broker: str # "eToro" or "Wio"
    entry_price: float
    current_price: float
    stop_loss: float
    target_price: float
    shares: float
    manual_stop_lock: bool = False
    status: str # "OPEN", "CLOSED"
    
    @property
    def unrealized_pl_pct(self) -> float:
        return ((self.current_price - self.entry_price) / self.entry_price) * 100

    @property
    def unrealized_pl_usd(self) -> float:
        return (self.current_price - self.entry_price) * self.shares
        
    @property
    def current_value(self) -> float:
        return self.current_price * self.shares
        
    @property
    def invested_capital(self) -> float:
        return self.entry_price * self.shares
