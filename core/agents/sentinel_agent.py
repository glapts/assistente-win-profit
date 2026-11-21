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
    def __init__(self, lockout_duration_minutes: int = 30):
        super().__init__(name="Agente_Sentinela_Politico")
        self.lockout_duration_minutes = lockout_duration_minutes
        self.news_history: List[Dict[str, Any]] = []
        
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

        # 1. Verifica se há Cisne Negro Político Ativo (P8)
        if self.active_black_swan:
            if now < self.active_black_swan["expires_at"]:
                return AgentOpinion(
                    agent_name=self.name,
                    bias="LOCKOUT",
                    confidence=1.0,
                    lockout=True,
                    veto_buy=True,
                    veto_sell=True,
                    reason=f"BLACK SWAN FISCAL/POLÍTICO (P8): {self.active_black_swan['text']} [{self.active_black_swan['source']}]. Trava de segurança até {self.active_black_swan['expires_at'].strftime('%H:%M:%S')}.",
                    metadata={"news": self.active_black_swan}
                )
            else:
                # Expirou o tempo de quarentena da notícia
                self.active_black_swan = None

        # 2. Clima Normal
        opinion = AgentOpinion(
            agent_name=self.name,
            bias="NEUTRAL",
            confidence=0.85,
            veto_buy=False,
            veto_sell=False,
            lockout=False,
            reason="Radar de notícias estável. Nenhum choque político ou fiscal em Brasília detectado.",
            metadata={"last_news_count": len(self.news_history)}
        )
        self.last_opinion = opinion
        return opinion
