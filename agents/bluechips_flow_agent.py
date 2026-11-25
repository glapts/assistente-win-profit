"""
agents/bluechips_flow_agent.py
Agente 6 do Execution Harness — Monitor de Fluxo das Blue Chips (BlueChipsFlowAgent).
Peso: 0.08. Analisa ITUB4, PETR4 e VALE3 com correlação direta ao WIN.
Valida se pelo menos 2 das 3 ações líderes confirmam saldo de agressão ou pressão no book.
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


class BlueChipsFlowAgent(BaseSpecialistAgent):
    """
    Agente Especialista nas 3 Principais Blue Chips do Ibovespa (ITUB4, PETR4, VALE3).
    Correlação Direta ao WIN:
    - Venda no WIN: Pelo menos 2 das 3 ações com saldo_agressao < 0 ou book vendedor (VOV > VOC * 1.10).
    - Compra no WIN: Pelo menos 2 das 3 ações com saldo_agressao > 0 ou book comprador (VOC > VOV * 1.10).
    - Dados herdados / desatualizados: retorna NEUTRO (score = 50.0).
    """

    def __init__(self, weight: float = 0.08):
        super().__init__(agent_name="BlueChipsFlowAgent", weight=weight)

    def evaluate(self, side: str, context: Dict[str, Any]) -> AgentVerdict:
        side_norm = side.upper().strip() if isinstance(side, str) else "NEUTRO"
        if side_norm not in ("COMPRA", "VENDA"):
            side_norm = "COMPRA"

        symbols = ["ITUB4", "PETR4", "VALE3"]
        assets = {sym: _get_asset(context, sym) for sym in symbols}

        # 1. Verificação de dados herdados ou ausentes
        valid_count = sum(1 for a in assets.values() if _is_valid_asset(a))
        if valid_count < 2:
            return AgentVerdict(
                agent_name=self.agent_name,
                weight=self.weight,
                bias="NEUTRO",
                score=50.0,
                status_tag="ALINHADO",
                reasons=[
                    "Dados de Blue Chips (ITUB4/PETR4/VALE3) insuficientes ou herdados do pregão anterior",
                    "Aguardando cotações e negócios ao vivo no DDE para as ações líderes",
                    "Score do fluxo das ações líderes mantido neutro por prudência"
                ],
                metrics={"status": "DADOS_INDISPONIVEIS_OU_HERDADOS", "valid_count": valid_count}
            )

        # 2. Avaliação de cada uma das 3 ações
        compra_signals = 0
        venda_signals = 0
        stock_details: Dict[str, Dict[str, Any]] = {}

        for sym, asset in assets.items():
            if not _is_valid_asset(asset):
                continue

            saldo = _get_val(asset, "saldo_agressao", 0.0)
            voc = _get_val(asset, "voc", 0.0)
            vov = _get_val(asset, "vov", 0.0)
            var = _get_val(asset, "variacao", 0.0)

            # Condições de compra: saldo > 0 ou book comprador expressivo (VOC > VOV * 1.10)
            is_compra = (saldo > 0) or (voc > vov * 1.10 and vov > 0)
            # Condições de venda: saldo < 0 ou book vendedor expressivo (VOV > VOC * 1.10)
            is_venda = (saldo < 0) or (vov > voc * 1.10 and voc > 0)

            if is_compra and not is_venda:
                compra_signals += 1
            elif is_venda and not is_compra:
                venda_signals += 1
            elif saldo > 0:
                compra_signals += 1
            elif saldo < 0:
                venda_signals += 1

            stock_details[sym] = {
                "saldo_agressao": saldo,
                "voc": voc,
                "vov": vov,
                "variacao": var,
                "is_compra": is_compra,
                "is_venda": is_venda
            }

        reasons: List[str] = []

        if side_norm == "COMPRA":
            if compra_signals >= 2:
                status_tag = "ALINHADO"
                bias = "COMPRA"
                score = 85.0 if compra_signals == 2 else 95.0
                reasons.append(f"{compra_signals} de 3 Blue Chips (ITUB4/PETR4/VALE3) com fluxo comprador ou book escorado")
                reasons.append("Sustentação do índice à vista apoiando compra no índice futuro")
                reasons.append(f"Ações líderes com confluência compradora ({compra_signals}/3 alinhadas)")

            elif venda_signals >= 2:
                # Divergência: Blue chips vendidas enquanto avalia compra no WIN
                status_tag = "DIVERGENTE"
                bias = "VENDA"
                score = 30.0
                reasons.append(f"Divergência: {venda_signals} de 3 Blue Chips com pressão vendedora no fluxo")
                reasons.append("PETR4, VALE3 ou ITUB4 pesando no índice à vista")
                reasons.append("Falta de tração das ações líderes desfavorece compra no WIN")

            else:
                status_tag = "ALINHADO"
                bias = "NEUTRO"
                score = 50.0
                reasons.append("Blue Chips em dispersão (sem maioria compradora ou vendedora)")
                reasons.append("Fluxo das ações líderes em equilíbrio relativo")

        else:  # VENDA
            if venda_signals >= 2:
                status_tag = "ALINHADO"
                bias = "VENDA"
                score = 85.0 if venda_signals == 2 else 95.0
                reasons.append(f"{venda_signals} de 3 Blue Chips (ITUB4/PETR4/VALE3) com saldo negativo ou book vendedor")
                reasons.append("Pesos pesados do Ibovespa puxando o índice à vista para baixo")
                reasons.append(f"Fluxo vendedor institucional alinhado nas ações ({venda_signals}/3)")

            elif compra_signals >= 2:
                # Divergência: Blue chips compradas enquanto avalia venda no WIN
                status_tag = "DIVERGENTE"
                bias = "COMPRA"
                score = 30.0
                reasons.append(f"Divergência: {compra_signals} de 3 Blue Chips com saldo comprador ou book de alta")
                reasons.append("Sustentação em PETR4, VALE3 ou ITUB4 freando a queda do índice")
                reasons.append("Risco de rejeição de mínimas pela força das ações líderes")

            else:
                status_tag = "ALINHADO"
                bias = "NEUTRO"
                score = 50.0
                reasons.append("Blue Chips em dispersão (sem maioria compradora ou vendedora)")
                reasons.append("Fluxo das ações líderes em equilíbrio relativo")

        reasons = reasons[:3]

        metrics = {
            "compra_signals": compra_signals,
            "venda_signals": venda_signals,
            "stocks": stock_details
        }
        context["bluechips_insights"] = metrics

        return AgentVerdict(
            agent_name=self.agent_name,
            weight=self.weight,
            bias=bias,
            score=score,
            status_tag=status_tag,
            reasons=reasons,
            metrics=metrics
        )
