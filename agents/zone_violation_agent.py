"""
agents/zone_violation_agent.py
Agente 2 do Execution Harness — Monitor de Violação e Defesa de Zonas (ZoneViolationDefenseAgent).
Peso: 0.20. Avalia reação defensiva em faixas [L_inf, L_sup], agressão vencida (COMPRA_VENCIDA / VENDA_VENCIDA)
e calcula a Probabilidade de Reação Forte de Defesa (P_defesa).
"""

from typing import Dict, Any, List, Optional, Tuple
from agents.base_agent import BaseSpecialistAgent, AgentVerdict


class ZoneViolationDefenseAgent(BaseSpecialistAgent):
    """
    Agente Especialista de Defesa vs Violação de Zonas Críticas SMC (FVG, Order Blocks, Caixotes).
    Quantifica a disputa em número de contratos (V_C vs V_V), afastamento da borda vulnerável (I_rep)
    e confluência passiva de book (I_book) para calcular P_defesa.
    """

    def __init__(self, weight: float = 0.20):
        super().__init__(agent_name="ZoneViolationDefenseAgent", weight=weight)

    def evaluate(self, side: str, context: Dict[str, Any]) -> AgentVerdict:
        side_norm = side.upper().strip() if isinstance(side, str) else "NEUTRO"
        if side_norm not in ("COMPRA", "VENDA"):
            side_norm = "COMPRA"

        # 1. Extração dos limites da zona [L_inf, L_sup]
        # Aceita context['zone'] como tupla/lista ou chaves diretas 'l_inf', 'l_sup'
        zone_tuple = context.get("zone") or context.get("fvg_zone_bounds")
        l_inf = 0.0
        l_sup = 0.0

        if isinstance(zone_tuple, (tuple, list)) and len(zone_tuple) >= 2:
            l_inf = float(zone_tuple[0])
            l_sup = float(zone_tuple[1])
        else:
            l_inf = float(context.get("l_inf", context.get("bottom", 0.0)))
            l_sup = float(context.get("l_sup", context.get("top", 0.0)))

        # Se não fornecido zona explícita, tenta extrair de ativos ou preço corrente
        current_p = float(context.get("current_price", context.get("ultimo", 0.0)))
        if current_p <= 0.0 and "win_snapshot" in context:
            current_p = getattr(context["win_snapshot"], "ultimo", 0.0)

        if l_inf <= 0.0 or l_sup <= 0.0:
            # Fallback seguro: cria zona nominal de 30 pontos ao redor do preço
            l_inf = current_p - 15.0 if current_p > 0 else 170000.0
            l_sup = current_p + 15.0 if current_p > 0 else 170030.0

        if l_inf > l_sup:
            l_inf, l_sup = l_sup, l_inf

        # Largura da zona W = max(L_sup - L_inf, 5.0)
        w_zone = max(l_sup - l_inf, 5.0)

        # 2. Volume de agressão na zona: V_C e V_V
        v_c = float(context.get("v_c", context.get("agr_compra_zone", context.get("agr_compra", 0.0))))
        v_v = float(context.get("v_v", context.get("agr_venda_zone", context.get("agr_venda", 0.0))))

        # Se não houver dados específicos de zona, usa deltas de agressão da sessão/minuto
        if v_c <= 0 and v_v <= 0:
            v_c = float(context.get("delta_c", 100.0))
            v_v = float(context.get("delta_v", 100.0))

        # 3. Detecção de Agressão Vencida em Contratos
        # COMPRA_VENCIDA: preço perdeu L_inf (P < L_inf) com V_V > V_C
        is_compra_vencida = (current_p < l_inf) and (v_v > v_c) and (v_c > 0)
        # VENDA_VENCIDA: preço superou L_sup (P > L_sup) com V_C > V_V
        is_venda_vencida = (current_p > l_sup) and (v_c > v_v) and (v_v > 0)

        # 4. Cálculo do Domínio Líquido de Contratos (R_contratos)
        total_v = v_c + v_v
        r_contratos = 0.0

        if side_norm == "COMPRA":
            # Defesa de suporte: compradores defendendo
            if is_compra_vencida:
                r_contratos = 0.0  # Vencido e rompido
            elif v_c >= v_v:
                r_contratos = (v_c - v_v) / total_v if total_v > 0 else 0.5
            else:
                # Absorção: V_V > V_C mas o preço NÃO perdeu L_inf
                if current_p >= l_inf:
                    ratio_preservado = min(1.0, max(0.0, (current_p - l_inf) / w_zone))
                    r_contratos = 0.40 * ratio_preservado
                else:
                    r_contratos = 0.0

            # Afastamento de segurança da borda inferior (delta_P_afastamento)
            delta_p_afastamento = current_p - l_inf

        else:
            # Defesa de resistência: vendedores defendendo
            if is_venda_vencida:
                r_contratos = 0.0  # Vencido e rompido
            elif v_v >= v_c:
                r_contratos = (v_v - v_c) / total_v if total_v > 0 else 0.5
            else:
                # Absorção: V_C > V_V mas o preço NÃO superou L_sup
                if current_p <= l_sup:
                    ratio_preservado = min(1.0, max(0.0, (l_sup - current_p) / w_zone))
                    r_contratos = 0.40 * ratio_preservado
                else:
                    r_contratos = 0.0

            # Afastamento de segurança da borda superior (delta_P_afastamento)
            delta_p_afastamento = l_sup - current_p

        # 5. Índice de Repulsão (I_rep = min(1.0, max(0.0, delta_P_afastamento) / W))
        i_rep = min(1.0, max(0.0, delta_p_afastamento) / w_zone)

        # 6. Índice de Livro Passivo (I_book fornecido pelo OrderBookAgent)
        book_insights = context.get("book_insights") or {}
        i_book = float(book_insights.get("i_book", 0.5))
        # Garante que I_book esteja entre 0.0 e 1.0
        i_book = min(1.0, max(0.0, i_book))

        # 7. Fórmula Canônica: P_defesa = (0.45 * R_contratos + 0.35 * I_rep + 0.20 * I_book) * 100.0
        p_defesa = (0.45 * r_contratos + 0.35 * i_rep + 0.20 * i_book) * 100.0
        p_defesa = round(min(100.0, max(0.0, p_defesa)), 1)

        # 8. Classificação de Status Tag, Score e Bias
        reasons: List[str] = []

        if is_compra_vencida:
            status_tag = "COMPRA_VENCIDA"
            bias = "VENDA"
            score = round(max(10.0, 100.0 - p_defesa), 1)
            reasons.append(f"Suporte [{l_inf:.0f}] perdido por agressão vendedora ({int(v_v)}ct vs {int(v_c)}ct)")
            reasons.append(f"Agressão compradora vencida em contratos abaixo da zona")
            reasons.append(f"Probabilidade de defesa compradora em colapso ({p_defesa:.1f}%)")

        elif is_venda_vencida:
            status_tag = "VENDA_VENCIDA"
            bias = "COMPRA"
            score = round(max(10.0, 100.0 - p_defesa), 1)
            reasons.append(f"Resistência [{l_sup:.0f}] rompida por agressão compradora ({int(v_c)}ct vs {int(v_v)}ct)")
            reasons.append(f"Agressão vendedora vencida em contratos acima da zona")
            reasons.append(f"Probabilidade de defesa vendedora em colapso ({p_defesa:.1f}%)")

        elif p_defesa >= 75.0:
            status_tag = "REACAO_FORTE_DEFESA"
            bias = side_norm
            score = p_defesa
            lado_str = "compradora" if side_norm == "COMPRA" else "vendedora"
            reasons.append(f"Reação forte de defesa {lado_str} na zona [{l_inf:.0f} - {l_sup:.0f}] ({p_defesa:.1f}%)")
            reasons.append(f"Domínio de contratos {r_contratos*100:.1f}% e repulsão I_rep={i_rep:.2f}")
            reasons.append(f"Escora passiva em confluência I_book={i_book:.2f}")

        elif p_defesa >= 50.0:
            status_tag = "DEFESA_MODERADA"
            bias = side_norm
            score = p_defesa
            reasons.append(f"Defesa moderada na faixa [{l_inf:.0f} - {l_sup:.0f}] ({p_defesa:.1f}%)")
            reasons.append(f"Afastamento favorável de {delta_p_afastamento:+.1f} pts da borda crítica")
            reasons.append(f"Equilíbrio de contratos ({int(v_c)}ct C vs {int(v_v)}ct V)")

        else:
            status_tag = "DEFESA_VENCIDA"
            bias = "NEUTRO"
            score = p_defesa
            reasons.append(f"Defesa fraca ou vencida na zona [{l_inf:.0f} - {l_sup:.0f}] ({p_defesa:.1f}%)")
            reasons.append("Preço vulnerável sem repulsão consistente")
            reasons.append(f"Baixo apoio de contratos e livro I_book={i_book:.2f}")

        reasons = reasons[:3]

        zone_insights = {
            "l_inf": l_inf,
            "l_sup": l_sup,
            "w_zone": w_zone,
            "v_c": v_c,
            "v_v": v_v,
            "current_price": current_p,
            "r_contratos": round(r_contratos, 3),
            "i_rep": round(i_rep, 3),
            "i_book": round(i_book, 3),
            "p_defesa": p_defesa,
            "status_tag": status_tag
        }
        context["zone_defense_insights"] = zone_insights

        return AgentVerdict(
            agent_name=self.agent_name,
            weight=self.weight,
            bias=bias,
            score=score,
            status_tag=status_tag,
            reasons=reasons,
            metrics=zone_insights
        )
