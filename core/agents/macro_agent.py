"""
core/agents/macro_agent.py
Agente Macro & Correlação Global.
Resolve:
  - Problema 6: Submissão absoluta ao S&P 500, Nasdaq e Treasuries (EUA).
  - Problema 7: Impacto de dados macroeconômicos (Payroll, CPI, FOMC).
  - Problema 11: Distorções na abertura de Wall Street (NY Open).
"""

from datetime import datetime, time, timedelta
from typing import List, Dict, Any, Optional

from core.agents.base_agent import BaseAgent, AgentOpinion


class MacroAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Agente_Macro_Global")
        # Estado de mercado externo
        self.sp500_price: float = 0.0
        self.sp500_change_pct: float = 0.0
        self.us10y_yield: float = 4.40
        self.us10y_change_bps: float = 0.0
        self.dxy_value: float = 104.0
        self.dxy_change_pct: float = 0.0
        
        # Calendário Econômico de Alto Impacto
        # Lista de dicts: {"name": "Payroll", "time": datetime, "before_min": 5, "after_min": 10}
        self.calendar_events: List[Dict[str, Any]] = []

    def add_calendar_event(self, name: str, event_time: datetime, before_min: int = 5, after_min: int = 10):
        self.calendar_events.append({
            "name": name,
            "time": event_time,
            "before_min": before_min,
            "after_min": after_min
        })

    def update_sp500(self, price: float, change_pct: float):
        self.sp500_price = price
        self.sp500_change_pct = change_pct

    def update_us10y(self, yield_pct: float, change_bps: float):
        self.us10y_yield = yield_pct
        self.us10y_change_bps = change_bps

    def update_dxy(self, dxy_val: float, change_pct: float):
        self.dxy_value = dxy_val
        self.dxy_change_pct = change_pct

    def evaluate(self, current_time: Optional[datetime] = None) -> AgentOpinion:
        now = current_time or datetime.now()
        
        # 1. Checagem de Calendário Econômico (P7: Payroll, CPI, FOMC)
        for ev in self.calendar_events:
            ev_time = ev["time"]
            start_window = ev_time - timedelta(minutes=ev["before_min"])
            end_window = ev_time + timedelta(minutes=ev["after_min"])
            
            if start_window <= now <= end_window:
                return AgentOpinion(
                    agent_name=self.name,
                    bias="LOCKOUT",
                    confidence=1.0,
                    lockout=True,
                    veto_buy=True,
                    veto_sell=True,
                    reason=f"CALENDÁRIO EUA (P7): Evento de altíssimo impacto '{ev['name']}' em andamento. Book rarefeito e alto risco de violinada.",
                    metadata={"event": ev["name"], "window_start": start_window.isoformat(), "window_end": end_window.isoformat()}
                )

        # 2. Checagem de Janela de Transição NY (P11: 10h28-10h35 e 11h28-11h35)
        t = now.time()
        if (time(10, 28) <= t <= time(10, 35)) or (time(11, 28) <= t <= time(11, 35)):
            return AgentOpinion(
                agent_name=self.name,
                bias="LOCKOUT",
                confidence=0.95,
                lockout=True,
                veto_buy=True,
                veto_sell=True,
                reason="ABERTURA DE WALL STREET (P11): Janela de volatilidade extrema e fluxo institucional de Nova York na B3.",
                metadata={"time": t.strftime("%H:%M:%S")}
            )

        # 3. Análise de Correlação S&P 500 e Treasuries (P6)
        veto_buy = False
        veto_sell = False
        bias = "NEUTRAL"
        confidence = 0.70
        reasons = []

        # S&P 500 caindo forte (> -0.50%) ou Treasuries disparando (> +5 bps):
        if self.sp500_change_pct < -0.40 or self.us10y_change_bps > 4.0:
            veto_buy = True
            bias = "BEARISH"
            confidence = 0.85
            reasons.append(f"Aversão a Risco Global: S&P 500 ({self.sp500_change_pct:+.2f}%) ou US 10Y ({self.us10y_change_bps:+.1f} bps) drenando capital emergente.")

        # S&P 500 subindo forte (> +0.50%) e Dólar caindo:
        elif self.sp500_change_pct > 0.40 and self.dxy_change_pct < 0.0:
            veto_sell = True
            bias = "BULLISH"
            confidence = 0.85
            reasons.append(f"Apetite por Risco Global: S&P 500 positivo ({self.sp500_change_pct:+.2f}%) favorecendo fluxo comprador.")

        else:
            bias = "NEUTRAL"
            confidence = 0.75
            reasons.append("Mercado externo operando em estabilidade.")

        opinion = AgentOpinion(
            agent_name=self.name,
            bias=bias,
            confidence=confidence,
            veto_buy=veto_buy,
            veto_sell=veto_sell,
            lockout=False,
            reason="; ".join(reasons),
            metadata={
                "sp500_pct": self.sp500_change_pct,
                "us10y_bps": self.us10y_change_bps,
                "dxy_pct": self.dxy_change_pct
            }
        )
        self.last_opinion = opinion
        return opinion
