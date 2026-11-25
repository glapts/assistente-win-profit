"""
agents/base_agent.py
Contrato base e definição de veredito para os 7 Agentes Especialistas do Execution Harness.
Camada determinística, sem LLM no caminho crítico, compatível com Python 3.14 / Windows 11.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


VALID_BIASES = ("COMPRA", "VENDA", "NEUTRO")

VALID_STATUS_TAGS = {
    "PULLBACK_VALIDO",
    "ESTICADO",
    "COMPRA_VENCIDA",
    "VENDA_VENCIDA",
    "REACAO_FORTE_DEFESA",
    "DEFESA_MODERADA",
    "DEFESA_VENCIDA",
    "ESCORA_PASSIVA",
    "BLEFE_PULLING",
    "ALINHADO",
    "DIVERGENTE"
}


@dataclass
class AgentVerdict:
    """
    Veredito padronizado emitido por cada Agente Especialista.
    Consumido pelo ExecutionHarness para confluência estatística e painel no PowerShell.
    """
    agent_name: str
    weight: float                                      # Peso relativo do agente (ex: 0.10 a 0.25)
    bias: str                                          # "COMPRA" | "VENDA" | "NEUTRO"
    score: float                                       # Convicção normalizada de 0.0 a 100.0
    status_tag: str                                    # Tag padronizada de classificação técnica
    reasons: List[str] = field(default_factory=list)   # No máximo 3 fatos objetivos e curtos
    metrics: Dict[str, Any] = field(default_factory=dict)  # Insumos numéricos compartilháveis

    def __post_init__(self):
        # Validação estrita do bias
        self.bias = self.bias.upper().strip() if isinstance(self.bias, str) else "NEUTRO"
        if self.bias not in VALID_BIASES:
            self.bias = "NEUTRO"

        # Limitação do score entre 0.0 e 100.0
        try:
            self.score = max(0.0, min(100.0, float(self.score)))
        except (ValueError, TypeError):
            self.score = 50.0

        # Normalização do peso
        try:
            self.weight = max(0.0, float(self.weight))
        except (ValueError, TypeError):
            self.weight = 1.0

        # Validação do status_tag
        if self.status_tag not in VALID_STATUS_TAGS:
            # Fallback seguro caso seja enviada variação não padronizada
            self.status_tag = "ALINHADO" if self.bias in ("COMPRA", "VENDA") else "DIVERGENTE"

        # Garantia de no máximo 3 razões
        if not isinstance(self.reasons, list):
            self.reasons = [str(self.reasons)] if self.reasons else []
        if len(self.reasons) > 3:
            self.reasons = self.reasons[:3]


class BaseSpecialistAgent(ABC):
    """
    Interface abstrata obrigatória para todos os 7 Agentes Especialistas.
    Garante isolamento modular, processamento em sub-milissegundo e contratos previsíveis.
    """

    def __init__(self, agent_name: str, weight: float = 1.0):
        self.agent_name = agent_name
        self.weight = weight

    @abstractmethod
    def evaluate(self, side: str, context: Dict[str, Any]) -> AgentVerdict:
        """
        Avalia o contexto operacional e retorna o veredito determinístico do agente.

        :param side: Direção operacional em análise ("COMPRA" | "VENDA" | "NEUTRO")
        :param context: Dicionário contendo snapshot DDE, histórico, contexto SMC e fluxo
        :return: AgentVerdict preenchido com bias, score, status_tag e métricas
        """
        raise NotImplementedError("Cada Agente Especialista deve implementar seu método evaluate.")
