"""
agents/global_index_agent.py
Agente 7 do Execution Harness — Monitor de Índice Global / S&P 500 (GlobalIndexAgent).
Peso: 0.05. Analisa o Mini S&P 500 Futuro na B3 (WSPZ26) com correlação direta ao WIN.
Valida o apetite global a risco (Risk-On / Risk-Off) via variação e saldo de agressão do S&P.
"""

from typing import Dict, Any, List, Optional
from agents.base_agent import BaseSpecialistAgent, AgentVerdict


def _get_asset(context: Dict[str, Any], symbol: str) -> Optional[Any]:
    sym = symbol.upper()
    if "assets" in context and isinstance(context["assets"], dict) and sym in context["assets"]:
        return context["assets"][sym]
    if "dde_snapshot" in context:
        snap = context["dde_snapshot"]
        if hasattr(snap, "assets") and sym in snap.assets:
            return snap.assets[sym]
    if sym in context:
        return context[sym]
    return None


def _get_val(asset: Any, field_name: str, default: float = 0.0) -> float:
    if asset is None:
        return default
    if hasattr(asset, field_name):
        val = getattr(asset, field_name)
    elif isinstance(asset, dict):
        val = asset.get(field_name, default)
    else:
        return default
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _is_valid_asset(asset: Any) -> bool:
    if asset is None:
        return False
    if hasattr(asset, "is_valid") and callable(asset.is_valid):
        return asset.is_valid()
    ultimo = _get_val(asset, "ultimo", 0.0)
    neg = int(_get_val(asset, "negocios", 0.0))
    qtd = _get_val(asset, "quantidade", 0.0)
    return ultimo > 0.0 and (neg > 0 or qtd > 0.0)


class GlobalIndexAgent(BaseSpecialistAgent):
    """
    Agente Especialista no Mini S&P 500 Futuro B3 (WSPZ26).
    Correlação Direta ao WIN:
    - Venda no WIN: WSPZ26 negativo (variacao < 0 ou ultimo < abertura) com saldo_agressao < 0.
    - Compra no WIN: WSPZ26 positivo (variacao > 0 ou ultimo > abertura) com saldo_agressao > 0.
    - Dados herdados / desatualizados: retorna NEUTRO (score = 50.0).
    """

    def __init__(self, weight: float = 0.05):
        super().__init__(agent_name="GlobalIndexAgent", weight=weight)

    def evaluate(self, side: str, context: Dict[str, Any]) -> AgentVerdict:
        side_norm = side.upper().strip() if isinstance(side, str) else "NEUTRO"
        if side_norm not in ("COMPRA", "VENDA"):
            side_norm = "COMPRA"

        wsp = _get_asset(context, "WSPZ26")

        # 1. Verificação de dados herdados ou ausentes
        if not _is_valid_asset(wsp):
            return AgentVerdict(
                agent_name=self.agent_name,
                weight=self.weight,
                bias="NEUTRO",
                score=50.0,
                status_tag="ALINHADO",
                reasons=[
                    "Dados do Mini S&P 500 (WSPZ26) ausentes ou herdados do pregão anterior",
                    "Aguardando transmissão ativa de cotações DDE do índice global",
                    "Score de correlação externa mantido neutro por prudência operacional"
                ],
                metrics={"status": "DADOS_INDISPONIVEIS_OU_HERDADOS"}
            )

        # 2. Extração das métricas do WSPZ26
        ultimo = _get_val(wsp, "ultimo", 0.0)
        abertura = _get_val(wsp, "abertura", 0.0)
        variacao = _get_val(wsp, "variacao", 0.0)
        saldo_agr = _get_val(wsp, "saldo_agressao", 0.0)

        # Condições direcionais do S&P 500
        is_sp_positivo = (variacao > 0 or (abertura > 0 and ultimo > abertura)) and saldo_agr > 0
        is_sp_negativo = (variacao < 0 or (abertura > 0 and ultimo < abertura)) and saldo_agr < 0

        reasons: List[str] = []

        if side_norm == "COMPRA":
            if is_sp_positivo:
                status_tag = "ALINHADO"
                bias = "COMPRA"
                score = 90.0 if (variacao > 0 and saldo_agr > 0) else 80.0
                reasons.append(f"Mini S&P 500 (WSPZ26) operando positivo: {variacao:+.2f}% (Último: {ultimo:.1f})")
                reasons.append(f"Saldo de agressão comprador no S&P ({saldo_agr:+.0f} contratos)")
                reasons.append("Apetite global a risco (Risk-On internacional) favorável à compra no WIN")

            elif is_sp_negativo:
                status_tag = "DIVERGENTE"
                bias = "VENDA"
                score = 30.0
                reasons.append(f"Divergência Global: S&P 500 em queda ({variacao:+.2f}%) com saldo negativo ({saldo_agr:+.0f}ct)")
                reasons.append("Mercados internacionais em modo de aversão a risco (Risk-Off)")
                reasons.append("Vento contra internacional reduz probabilidade de avanço comprador no WIN")

            else:
                status_tag = "ALINHADO"
                bias = "NEUTRO"
                score = 50.0
                reasons.append(f"S&P 500 em estabilidade ou fluxo misto (Var: {variacao:+.2f}%, Saldo: {saldo_agr:+.0f}ct)")
                reasons.append("Sem direcionamento forte vindo das bolsas internacionais")

        else:  # VENDA
            if is_sp_negativo:
                status_tag = "ALINHADO"
                bias = "VENDA"
                score = 90.0 if (variacao < 0 and saldo_agr < 0) else 80.0
                reasons.append(f"Mini S&P 500 (WSPZ26) operando negativo: {variacao:+.2f}% (Último: {ultimo:.1f})")
                reasons.append(f"Saldo de agressão vendedor no S&P ({saldo_agr:+.0f} contratos)")
                reasons.append("Aversão global a risco (Risk-Off internacional) alinhada à venda no WIN")

            elif is_sp_positivo:
                status_tag = "DIVERGENTE"
                bias = "COMPRA"
                score = 30.0
                reasons.append(f"Divergência Global: S&P 500 em alta ({variacao:+.2f}%) com saldo comprador ({saldo_agr:+.0f}ct)")
                reasons.append("Mercados internacionais em modo de alta (Risk-On) contrariando vendas no WIN")
                reasons.append("Risco de recuperação do índice futuro puxado por Wall Street")

            else:
                status_tag = "ALINHADO"
                bias = "NEUTRO"
                score = 50.0
                reasons.append(f"S&P 500 em estabilidade ou fluxo misto (Var: {variacao:+.2f}%, Saldo: {saldo_agr:+.0f}ct)")
                reasons.append("Sem direcionamento forte vindo das bolsas internacionais")

        reasons = reasons[:3]

        metrics = {
            "ultimo": ultimo,
            "abertura": abertura,
            "variacao": variacao,
            "saldo_agressao": saldo_agr,
            "is_sp_positivo": is_sp_positivo,
            "is_sp_negativo": is_sp_negativo
        }
        context["global_index_insights"] = metrics

        return AgentVerdict(
            agent_name=self.agent_name,
            weight=self.weight,
            bias=bias,
            score=score,
            status_tag=status_tag,
            reasons=reasons,
            metrics=metrics
        )
