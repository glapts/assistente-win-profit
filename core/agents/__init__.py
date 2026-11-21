"""
Pacote core.agents
Comitê Multi-Agente Assíncrono para o Mini-Índice B3 (WIN).
Contém:
  - MacroAgent: Monitoramento global (S&P 500, Treasuries, DXY, Calendário Econômico).
  - BasketAgent: Cesta IBOV (PETR4, VALE3, Bancos) e Curva de Juros (DI).
  - SentinelAgent: Sentinela de Notícias, Risco Político/Fiscal e Alertas Black Swan.
  - Orchestrator: Gestor de Mesa que consolida os pareceres e gera o runtime_state.json.
"""

from core.agents.base_agent import BaseAgent, AgentOpinion
from core.agents.macro_agent import MacroAgent
from core.agents.basket_agent import BasketAgent
from core.agents.sentinel_agent import SentinelAgent
from core.agents.orchestrator import Orchestrator

__all__ = [
    "BaseAgent",
    "AgentOpinion",
    "MacroAgent",
    "BasketAgent",
    "SentinelAgent",
    "Orchestrator"
]
