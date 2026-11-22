"""
core/agents/basket_agent.py
Agente de Cesta IBOV, Arbitragem e Curva de Juros (O "Espelho").
Resolve:
  - Problema 1: Natureza derivativa e falta de formação própria do WIN.
  - Problema 4: Assimetria de horário (ações fechadas entre 09h00 e 10h00).
  - Problema 5: Risco de concentração em Blue Chips (VALE3, PETR4 e Bancos).
  - Problema 9: Correlação inversa e distorções com os Juros Futuros (DI).
"""

from datetime import datetime, time
from typing import Dict, Any, Optional

from core.agents.base_agent import BaseAgent, AgentOpinion


class BasketAgent(BaseAgent):
    def __init__(self, ttl_seconds: float = 120.0):
        super().__init__(name="Agente_Cesta_Arbitragem")
        self.ttl_seconds = ttl_seconds
        # Monitoramento das Blue Chips (pesos dominantes no IBOV)
        self.stocks: Dict[str, float] = {
            "VALE3": 0.0,  # ~13%
            "PETR4": 0.0,  # ~12%
            "ITUB4": 0.0,  # ~8%
            "BBDC4": 0.0   # ~4%
        }
        # Curva de Juros Futuros (DIs) em variação de bps no dia
        self.di_rates: Dict[str, float] = {
            "DI1F27": 0.0, # Curto
            "DI1F29": 0.0, # Médio
            "DI1F31": 0.0  # Longo
        }
        self.last_update_time: Optional[datetime] = None

    def update_stock(self, ticker: str, change_pct: float, timestamp: Optional[datetime] = None):
        t_clean = ticker.upper().strip()
        self.stocks[t_clean] = change_pct
        self.last_update_time = timestamp or datetime.now()

    def update_di(self, contract: str, change_bps: float, timestamp: Optional[datetime] = None):
        c_clean = contract.upper().strip()
        self.di_rates[c_clean] = change_bps
        self.last_update_time = timestamp or datetime.now()

    def evaluate(self, current_time: Optional[datetime] = None) -> AgentOpinion:
        now = current_time or datetime.now()
        t = now.time()
        origin_ts = self.last_update_time or now

        # 1. Checagem de Horário do Mercado à Vista (P4: 09h00 às 10h00)
        if time(9, 0) <= t < time(10, 0):
            opinion = AgentOpinion(
                agent_name=self.name,
                bias="LOCKOUT",
                confidence=1.0,
                lockout=True,
                veto_buy=True,
                veto_sell=True,
                reason="MERCADO À VISTA FECHADO (P4): Blue Chips em leilão. WIN operando no escuro sem formação de preço real.",
                metadata={"time": t.strftime("%H:%M:%S")},
                timestamp=now,
                origin_timestamp=origin_ts,
                received_timestamp=now,
                ttl_seconds=self.ttl_seconds,
                data_quality="INTEGRITY_OK",
                source="B3_SCHEDULE"
            )
            self.last_opinion = opinion
            return opinion

        veto_buy = False
        veto_sell = False
        reasons = []

        # Verificar dados obsoletos
        data_quality = "INTEGRITY_OK"
        if self.last_update_time and (now - self.last_update_time).total_seconds() > self.ttl_seconds:
            data_quality = "STALE"
            reasons.append(f"Aviso: Dados de Blue Chips/DI sem atualização há {(now - self.last_update_time).total_seconds():.0f}s.")

        # 2. Concentração de Blue Chips (P5: VALE3 e PETR4)
        vale = self.stocks.get("VALE3", 0.0)
        petr = self.stocks.get("PETR4", 0.0)
        itub = self.stocks.get("ITUB4", 0.0)

        # Se Commodities estiverem caindo forte:
        if vale < -0.80 and petr < -0.80:
            veto_buy = True
            reasons.append(f"VETO BLUE CHIPS (P5): VALE3 ({vale:+.2f}%) e PETR4 ({petr:+.2f}%) em queda firme. Proibido comprar WIN.")

        # Se Blue Chips estiverem subindo forte em bloco:
        elif vale > 0.80 and petr > 0.80 and itub > 0.50:
            veto_sell = True
            reasons.append(f"FORÇA BLUE CHIPS (P5): VALE3 ({vale:+.2f}%) e PETR4 ({petr:+.2f}%) em forte alta. Proibido vender WIN.")

        # 3. Estresse na Curva de DI (P9: Juros Futuros)
        di_longo = self.di_rates.get("DI1F31", 0.0)
        di_medio = self.di_rates.get("DI1F29", 0.0)

        if di_longo >= 8.0 or di_medio >= 8.0:
            veto_buy = True
            reasons.append(f"ESTRESSE CURVA DI (P9): DI longo subindo forte ({di_longo:+.1f} bps). Robôs de arbitragem vendendo WIN para travar taxa.")

        elif di_longo <= -8.0 and di_medio <= -8.0:
            veto_sell = True
            reasons.append(f"ALÍVIO CURVA DI (P9): DI longo em queda ({di_longo:+.1f} bps). Favorece expansão de múltiplos e compras no WIN.")

        # 4. Consolidação do Viés
        if veto_buy and not veto_sell:
            bias = "BEARISH"
            conf = 0.88
        elif veto_sell and not veto_buy:
            bias = "BULLISH"
            conf = 0.88
        elif veto_buy and veto_sell:
            bias = "LOCKOUT"
            conf = 0.90
        else:
            bias = "NEUTRAL"
            conf = 0.75
            reasons.append("Cesta IBOV e Curva DI em equilíbrio sem distorções agudas de arbitragem.")

        opinion = AgentOpinion(
            agent_name=self.name,
            bias=bias,
            confidence=conf,
            veto_buy=veto_buy,
            veto_sell=veto_sell,
            lockout=False,
            reason="; ".join(reasons),
            metadata={
                "stocks": self.stocks.copy(),
                "di_rates": self.di_rates.copy()
            },
            timestamp=now,
            origin_timestamp=origin_ts,
            received_timestamp=now,
            ttl_seconds=self.ttl_seconds,
            data_quality=data_quality,
            source="BASKET_DI"
        )
        self.last_opinion = opinion
        return opinion
