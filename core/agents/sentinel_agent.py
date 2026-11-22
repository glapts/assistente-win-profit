"""
core/agents/sentinel_agent.py
Agente Sentinela de Notícias e Choques Político-Fiscais.
Resolve:
  - Problema 8: Ruído político, fiscal e declarações de autoridades no Brasil.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from core.agents.base_agent import BaseAgent, AgentOpinion


class SentinelAgent(BaseAgent):
    def __init__(self, lockout_duration_minutes: int = 30, ttl_seconds: float = 120.0):
        super().__init__(name="Agente_Sentinela_Politico")
        self.lockout_duration_minutes = lockout_duration_minutes
        self.ttl_seconds = ttl_seconds
        self.news_history: List[Dict[str, Any]] = []
        self.last_news_time: Optional[datetime] = None
        
        # Palavras-chave críticas para detecção de Choques Político-Fiscais (P8)
        self.black_swan_keywords = [
            "meta fiscal",
            "alteracao da meta",
            "estatizacao",
            "intervencao na petrobras",
            "intervencao na vale",
            "demissao de ministro",
            "demissao de campos neto",
            "demissao do presidente do bc",
            "crise institucional",
            "calote",
            "rombo fiscal",
            "contingenciamento bilionario",
            "estado de calamidade",
            "impeachment"
        ]

        self.active_black_swan: Optional[Dict[str, Any]] = None

    def inject_news(self, text: str, source: str = "Feed_Noticias", timestamp: Optional[datetime] = None):
        """Recebe uma notícia ou fala de autoridade em tempo real."""
        ts = timestamp or datetime.now()
        t_lower = text.lower()
        self.last_news_time = ts
        
        is_black_swan = any(kw in t_lower for kw in self.black_swan_keywords)

        item = {
            "timestamp": ts,
            "text": text,
            "source": source,
            "is_black_swan": is_black_swan
        }
        self.news_history.append(item)

        if is_black_swan:
            self.active_black_swan = {
                "triggered_at": ts,
                "text": text,
                "source": source,
                "expires_at": ts + timedelta(minutes=self.lockout_duration_minutes)
            }
            print(f"\n🚨 [SENTINELA] ALERTA CRÍTICO: BLACK SWAN DETECTADO!")
            print(f"   Notícia : \"{text}\" ({source})")
            print(f"   Ação    : Bloqueio emergencial de ordens por {self.lockout_duration_minutes} min.\n")

    def clear_black_swan(self):
        """Limpa manualmente o alerta de cisne negro (caso tenha sido alarme falso)."""
        self.active_black_swan = None

    def evaluate(self, current_time: Optional[datetime] = None) -> AgentOpinion:
        now = current_time or datetime.now()
        origin_ts = self.last_news_time or now

        # 1. Verifica se há Cisne Negro Político Ativo (P8)
        if self.active_black_swan:
            if now < self.active_black_swan["expires_at"]:
                opinion = AgentOpinion(
                    agent_name=self.name,
                    bias="LOCKOUT",
                    confidence=1.0,
                    lockout=True,
                    veto_buy=True,
                    veto_sell=True,
                    reason=f"BLACK SWAN FISCAL/POLÍTICO (P8): \"{self.active_black_swan['text']}\". Bloqueio ativo até {self.active_black_swan['expires_at'].strftime('%H:%M:%S')}.",
                    metadata=self.active_black_swan.copy(),
                    timestamp=now,
                    origin_timestamp=self.active_black_swan["triggered_at"],
                    received_timestamp=now,
                    ttl_seconds=self.ttl_seconds,
                    data_quality="INTEGRITY_OK",
                    source=self.active_black_swan.get("source", "POLITICAL_SENTINEL")
                )
                self.last_opinion = opinion
                return opinion
            else:
                self.active_black_swan = None

        opinion = AgentOpinion(
            agent_name=self.name,
            bias="NEUTRAL",
            confidence=0.80,
            veto_buy=False,
            veto_sell=False,
            lockout=False,
            reason="Ambiente político e fiscal sem choques atípicos de cauda longa.",
            metadata={"last_news_count": len(self.news_history)},
            timestamp=now,
            origin_timestamp=origin_ts,
            received_timestamp=now,
            ttl_seconds=self.ttl_seconds,
            data_quality="INTEGRITY_OK",
            source="NEWS_WIRE"
        )
        self.last_opinion = opinion
        return opinion
