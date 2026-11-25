"""
agents/extremes_tape_agent.py
Agente 4 do Execution Harness — Leitor Especialista de Tape Reading nos Extremos (ExtremesTapeAgent).
Peso: 0.20. Analisa a janela de 300 segundos do Times & Trades (Delta, agressão, absorção e grandes lotes)
e aplica o Filtro Anti-Falso Positivo via Média Aritmética de Reação Direcional (P_medio_reacao).
"""

from typing import Dict, Any, List, Optional
from agents.base_agent import BaseSpecialistAgent, AgentVerdict


class ExtremesTapeAgent(BaseSpecialistAgent):
    """
    Agente Especialista de Tape Reading e Fluxo de Ordens nos Extremos.
    Consome métricas da janela de 300 segundos e valida a evolução de ticks
    a partir da Média Aritmética de Reação Direcional (P_medio_reacao = sum(P_i) / N).
    """

    def __init__(self, weight: float = 0.20):
        super().__init__(agent_name="ExtremesTapeAgent", weight=weight)

    def evaluate(self, side: str, context: Dict[str, Any]) -> AgentVerdict:
        side_norm = side.upper().strip() if isinstance(side, str) else "NEUTRO"
        if side_norm not in ("COMPRA", "VENDA"):
            side_norm = "COMPRA"

        # 1. Extração das métricas da janela de 300s (Times & Trades)
        flow_data = context.get("flow_metrics") or context.get("tape_reading") or {}

        def _get_val(key: str, default: Any = 0) -> Any:
            if key in context:
                return context[key]
            if key in flow_data:
                return flow_data[key]
            return default

        agr_c_300s = float(_get_val("agr_compra_300s", _get_val("buy_volume", 0.0)))
        agr_v_300s = float(_get_val("agr_venda_300s", _get_val("sell_volume", 0.0)))
        delta_300s = float(_get_val("delta_300s", _get_val("delta", 0.0)))
        deslocamento_pts = float(_get_val("deslocamento_pts", _get_val("price_displacement_pts", 0.0)))
        grandes_execucoes = _get_val("grandes_execucoes", _get_val("large_trades", []))
        flow_pattern = str(_get_val("flow_pattern", "")).lower()

        # Detecção de Absorção
        absorcao_detectada = bool(
            "absorção" in flow_pattern or "absorcao" in flow_pattern or
            _get_val("absorcao_detectada", False) or _get_val("is_absorption", False)
        )

        current_p = float(_get_val("current_price", _get_val("ultimo", 0.0)))
        if current_p <= 0.0 and "win_snapshot" in context:
            current_p = getattr(context["win_snapshot"], "ultimo", 0.0)

        # 2. Filtro Anti-Falso Positivo via Média Aritmética de Reação Direcional
        # P_medio_reacao = sum(P_i) / N dos preços onde houve agressão na direção com evolução de ticks
        reaction_prices: List[float] = []

        raw_levels = context.get("p_reacao_levels") or context.get("reaction_levels")
        if raw_levels and isinstance(raw_levels, list):
            reaction_prices = [float(p) for p in raw_levels if float(p) > 0]
        elif isinstance(grandes_execucoes, list) and grandes_execucoes:
            for trade in grandes_execucoes:
                if isinstance(trade, dict):
                    t_side = str(trade.get("side", "")).upper()
                    t_price = float(trade.get("price", 0.0))
                    if t_price > 0 and (t_side == side_norm or t_side.startswith(side_norm[:3])):
                        reaction_prices.append(t_price)

        if reaction_prices:
            p_medio_reacao = round(sum(reaction_prices) / len(reaction_prices), 2)
        else:
            # Fallback quando não há histórico de ticks pontuais: utiliza o preço de entrada ou último preço
            p_medio_reacao = float(context.get("p_medio_reacao", current_p))

        # 3. Teste do Filtro de Reação Direcional
        # Na Compra: exige Ultimo >= P_medio_reacao
        # Na Venda: exige Ultimo <= P_medio_reacao
        filter_passed = False
        if side_norm == "COMPRA":
            filter_passed = (current_p >= p_medio_reacao)
        else:
            filter_passed = (current_p <= p_medio_reacao)

        reasons: List[str] = []
        n_grandes = len(grandes_execucoes) if isinstance(grandes_execucoes, list) else int(grandes_execucoes)

        # 4. Cálculo de Score, Bias e Status Tag
        if not filter_passed:
            # FALSO ROMPIMENTO / TRAP: Preço falhou em sustentar acima/abaixo da média de agressão
            score = 25.0
            if side_norm == "COMPRA":
                status_tag = "COMPRA_VENCIDA"
                bias = "VENDA"
                reasons.append(f"Falso Rompimento: preço ({current_p:.0f}) recuou abaixo da média de agressão compradora ({p_medio_reacao:.0f})")
                reasons.append("Vendedores absorveram ou anularam o avanço comprador no topo recente")
            else:
                status_tag = "VENDA_VENCIDA"
                bias = "COMPRA"
                reasons.append(f"Falso Rompimento: preço ({current_p:.0f}) superou a média de agressão vendedora ({p_medio_reacao:.0f})")
                reasons.append("Compradores absorveram ou anularam o avanço vendedor no fundo recente")

            reasons.append(f"Delta 300s de {delta_300s:+.0f} contratos sem evolução de preço favorável")

        else:
            # Filtro passou com sucesso
            bias = side_norm

            if absorcao_detectada:
                status_tag = "REACAO_FORTE_DEFESA"
                score = 92.0
                tipo_abs = "compradora (venda absorvida)" if side_norm == "COMPRA" else "vendedora (compra absorvida)"
                reasons.append(f"Absorção {tipo_abs} detectada com sustentação de preço")
                reasons.append(f"Preço evoluindo ({current_p:.0f}) a partir da média de reação ({p_medio_reacao:.0f})")
                reasons.append(f"Delta 300s de {delta_300s:+.0f} contratos confirmando esgotamento contrário")

            elif (side_norm == "COMPRA" and delta_300s > 0) or (side_norm == "VENDA" and delta_300s < 0):
                status_tag = "ALINHADO"
                score = 85.0
                reasons.append(f"Agressão com continuidade favorável na janela de 300s (Delta {delta_300s:+.0f}ct)")
                reasons.append(f"Preço sustentado ({current_p:.0f}) >= média de agressão ({p_medio_reacao:.0f})")
                reasons.append(f"{n_grandes} grande(s) execução(ões) institucional(is) apoiando o movimento")

            else:
                # Delta divergente do lado, mas o filtro de preço ainda está segurando
                status_tag = "ALINHADO"
                score = 60.0
                reasons.append(f"Preço segurando no nível de reação ({p_medio_reacao:.0f}), mas com delta divergente ({delta_300s:+.0f}ct)")
                reasons.append(f"Deslocamento de {deslocamento_pts:+.0f} pts na janela de 300s")
                reasons.append("Aguardando maior confluência de agressão a favor do movimento")

        reasons = reasons[:3]

        tape_insights = {
            "agr_compra_300s": agr_c_300s,
            "agr_venda_300s": agr_v_300s,
            "delta_300s": delta_300s,
            "deslocamento_pts": deslocamento_pts,
            "p_medio_reacao": p_medio_reacao,
            "current_price": current_p,
            "filter_passed": filter_passed,
            "absorcao_detectada": absorcao_detectada,
            "status_tag": status_tag
        }
        context["tape_insights"] = tape_insights

        return AgentVerdict(
            agent_name=self.agent_name,
            weight=self.weight,
            bias=bias,
            score=score,
            status_tag=status_tag,
            reasons=reasons,
            metrics=tape_insights
        )
