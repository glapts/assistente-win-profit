"""
agents/macro_rates_agent.py
Agente 5 do Execution Harness — Monitor Macro de Taxas e Câmbio (MacroRatesAgent).
Peso: 0.12. Analisa DI1F29, DI1F31 e WDOZ26 (com fallback WDOFUT), com correlação inversa ao WIN.
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


class MacroRatesAgent(BaseSpecialistAgent):
    """
    Agente Especialista de Juros Futuros (DI1) e Dólar Futuro (WDO).
    Correlação Inversa ao WIN:
    - Venda no WIN: DI abrindo taxa (variacao > 0, saldo > 0) e Dólar subindo (variacao > 0, saldo > 0, VOC > VOV).
    - Compra no WIN: DI fechando taxa (variacao < 0, saldo < 0) e Dólar recuando (variacao < 0, saldo < 0, VOV > VOC).
    - Dados herdados / desatualizados: retorna NEUTRO (score = 50.0).
    """

    def __init__(self, weight: float = 0.12):
        super().__init__(agent_name="MacroRatesAgent", weight=weight)

    def evaluate(self, side: str, context: Dict[str, Any]) -> AgentVerdict:
        side_norm = side.upper().strip() if isinstance(side, str) else "NEUTRO"
        if side_norm not in ("COMPRA", "VENDA"):
            side_norm = "COMPRA"

        # 1. Obtenção dos ativos de juros e câmbio
        di29 = _get_asset(context, "DI1F29")
        di31 = _get_asset(context, "DI1F31")

        # Dólar primário WDOZ26 com fallback automático para WDOFUT
        wdo = _get_asset(context, "WDOZ26")
        wdo_sym = "WDOZ26"
        if not _is_valid_asset(wdo):
            wdo_fut = _get_asset(context, "WDOFUT")
            if _is_valid_asset(wdo_fut):
                wdo = wdo_fut
                wdo_sym = "WDOFUT"

        # 2. Verificação de dados herdados ou ausentes
        if not _is_valid_asset(di29) or not _is_valid_asset(di31) or not _is_valid_asset(wdo):
            return AgentVerdict(
                agent_name=self.agent_name,
                weight=self.weight,
                bias="NEUTRO",
                score=50.0,
                status_tag="ALINHADO",
                reasons=[
                    "Dados de DI ou Dólar indisponíveis ou herdados do pregão anterior",
                    "Aguardando transmissão ativa de cotações DDE na grade macro",
                    "Score de taxas mantido neutro por prudência operacional"
                ],
                metrics={"status": "DADOS_INDISPONIVEIS_OU_HERDADOS"}
            )

        # 3. Extração das métricas
        var_di29 = _get_val(di29, "variacao", 0.0)
        saldo_di29 = _get_val(di29, "saldo_agressao", 0.0)

        var_di31 = _get_val(di31, "variacao", 0.0)
        saldo_di31 = _get_val(di31, "saldo_agressao", 0.0)

        var_wdo = _get_val(wdo, "variacao", 0.0)
        saldo_wdo = _get_val(wdo, "saldo_agressao", 0.0)
        voc_wdo = _get_val(wdo, "voc", 0.0)
        vov_wdo = _get_val(wdo, "vov", 0.0)

        # 4. Avaliação das condições macro
        # DI abrindo taxa: taxa subindo e saldo de agressão comprador de taxa
        di_opening = (var_di29 > 0 or var_di31 > 0) and (saldo_di29 >= 0 or saldo_di31 >= 0)
        di_closing = (var_di29 < 0 or var_di31 < 0) and (saldo_di29 <= 0 or saldo_di31 <= 0)

        # Dólar subindo: variação positiva, saldo comprador e pressão compradora no book
        wdo_rising = (var_wdo > 0) and (saldo_wdo > 0 or voc_wdo >= vov_wdo)
        wdo_falling = (var_wdo < 0) and (saldo_wdo < 0 or vov_wdo >= voc_wdo)

        reasons: List[str] = []

        if side_norm == "VENDA":
            # Confluência de VENDA no WIN: DI abrindo e Dólar subindo
            if di_opening and wdo_rising:
                status_tag = "ALINHADO"
                bias = "VENDA"
                score = 88.0
                if (var_di29 > 0 and var_di31 > 0 and saldo_wdo > 0 and voc_wdo > vov_wdo):
                    score = 96.0  # Alinhamento perfeito
                reasons.append(f"Curva de DI abrindo: DI1F29 {var_di29:+.2f}% / DI1F31 {var_di31:+.2f}%")
                reasons.append(f"Dólar ({wdo_sym}) em alta ({var_wdo:+.2f}%) com saldo comprador ({saldo_wdo:+.0f}ct)")
                reasons.append("Pressão macro e cambial plenamente favorável à VENDA no WIN")

            elif di_closing and wdo_falling:
                # Mercado em Risk-On (DI caindo, Dólar caindo) -> VENDA no WIN é altamente divergente
                status_tag = "DIVERGENTE"
                bias = "COMPRA"
                score = 25.0
                reasons.append(f"Divergência Macro: DI fechando taxa ({var_di29:+.2f}%) e Dólar em queda ({var_wdo:+.2f}%)")
                reasons.append("Apetite a risco local contraria vendas no índice futuro")
                reasons.append(f"Book do Dólar ofertado na venda (VOV {vov_wdo:.0f} > VOC {voc_wdo:.0f})")

            else:
                status_tag = "ALINHADO"
                bias = "NEUTRO"
                score = 52.0
                reasons.append(f"Sinais mistos na curva de DI ({var_di29:+.2f}%) e Dólar ({var_wdo:+.2f}%)")
                reasons.append("Sem confluência direcional soberana nas taxas de juros")

        else:  # COMPRA
            # Confluência de COMPRA no WIN: DI fechando e Dólar recuando
            if di_closing and wdo_falling:
                status_tag = "ALINHADO"
                bias = "COMPRA"
                score = 88.0
                if (var_di29 < 0 and var_di31 < 0 and saldo_wdo < 0 and vov_wdo > voc_wdo):
                    score = 96.0
                reasons.append(f"Curva de DI fechando: DI1F29 {var_di29:+.2f}% / DI1F31 {var_di31:+.2f}%")
                reasons.append(f"Dólar ({wdo_sym}) recuando ({var_wdo:+.2f}%) com saldo vendedor ({saldo_wdo:+.0f}ct)")
                reasons.append("Cenário de apetite a risco (Risk-On) plenamente favorável à COMPRA no WIN")

            elif di_opening and wdo_rising:
                # Estresse macro (DI subindo, Dólar disparando) -> COMPRA no WIN é divergente
                status_tag = "DIVERGENTE"
                bias = "VENDA"
                score = 25.0
                reasons.append(f"Divergência Macro: DI abrindo taxa ({var_di29:+.2f}%) e Dólar em alta ({var_wdo:+.2f}%)")
                reasons.append("Estresse de juros e aversão a risco contraria compras no WIN")
                reasons.append(f"Book do Dólar escorado na compra (VOC {voc_wdo:.0f} > VOV {vov_wdo:.0f})")

            else:
                status_tag = "ALINHADO"
                bias = "NEUTRO"
                score = 52.0
                reasons.append(f"Sinais mistos na curva de DI ({var_di29:+.2f}%) e Dólar ({var_wdo:+.2f}%)")
                reasons.append("Sem confluência direcional soberana nas taxas de juros")

        reasons = reasons[:3]

        metrics = {
            "di29_var": var_di29,
            "di29_saldo": saldo_di29,
            "di31_var": var_di31,
            "di31_saldo": saldo_di31,
            "wdo_symbol": wdo_sym,
            "wdo_var": var_wdo,
            "wdo_saldo": saldo_wdo,
            "wdo_voc": voc_wdo,
            "wdo_vov": vov_wdo,
            "di_opening": di_opening,
            "di_closing": di_closing,
            "wdo_rising": wdo_rising,
            "wdo_falling": wdo_falling
        }
        context["macro_rates_insights"] = metrics

        return AgentVerdict(
            agent_name=self.agent_name,
            weight=self.weight,
            bias=bias,
            score=score,
            status_tag=status_tag,
            reasons=reasons,
            metrics=metrics
        )
