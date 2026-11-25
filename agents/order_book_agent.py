"""
agents/order_book_agent.py
Agente 1 do Execution Harness — Leitor Especialista de Book de Ofertas (OrderBookAgent).
Peso: 0.15. Analisa profundidade, spread, imbalance, escora passiva e blefe/pulling.
"""

from typing import Dict, Any, List, Optional
from agents.base_agent import BaseSpecialistAgent, AgentVerdict


class OrderBookAgent(BaseSpecialistAgent):
    """
    Agente Especialista de Book de Ofertas L1/L2 para o Mini-Índice B3.
    Analisa desbalanceamento de liquidez passiva, recargas/escoras defensivas
    e cancelamentos rápidos compatíveis com blefe (pulling).
    Publica 'book_insights' no contexto operacional.
    """

    def __init__(self, weight: float = 0.15):
        super().__init__(agent_name="OrderBookAgent", weight=weight)

    def evaluate(self, side: str, context: Dict[str, Any]) -> AgentVerdict:
        side_norm = side.upper().strip() if isinstance(side, str) else "NEUTRO"
        if side_norm not in ("COMPRA", "VENDA"):
            side_norm = "COMPRA"  # Padrão de análise contextual

        # Extração flexível dos dados de book (aceita win_book, win_snapshot ou chaves diretas)
        book_data = context.get("win_book") or {}
        win_snap = context.get("win_snapshot")

        def _get_num(key: str, default: float = 0.0) -> float:
            if key in context:
                try:
                    return float(context[key])
                except (ValueError, TypeError):
                    pass
            if key in book_data:
                try:
                    return float(book_data[key])
                except (ValueError, TypeError):
                    pass
            if win_snap and hasattr(win_snap, key):
                try:
                    return float(getattr(win_snap, key))
                except (ValueError, TypeError):
                    pass
            return default

        of_compra = _get_num("of_compra", 0.0)
        of_venda = _get_num("of_venda", 0.0)
        voc = _get_num("voc", 0.0)
        vov = _get_num("vov", 0.0)
        delta_voc = _get_num("delta_voc", 0.0)
        delta_vov = _get_num("delta_vov", 0.0)
        delta_negocios = int(_get_num("delta_negocios", 0.0))

        # Suporte opcional a L2 Top 5 níveis se fornecido
        l2_top5 = context.get("l2_top5") or []
        if l2_top5 and isinstance(l2_top5, list):
            # Se fornecido L2 completo, refina VOC e VOV agregando os 5 melhores níveis
            try:
                l2_bid_vol = sum(lvl.get("quantity", 0) for lvl in l2_top5 if lvl.get("side") == "BID")
                l2_ask_vol = sum(lvl.get("quantity", 0) for lvl in l2_top5 if lvl.get("side") == "ASK")
                if l2_bid_vol > 0 and l2_ask_vol > 0:
                    voc = float(l2_bid_vol)
                    vov = float(l2_ask_vol)
            except Exception:
                pass

        # 1. Spread de Ofertas (pontos)
        spread_pts = round(abs(of_venda - of_compra), 2) if (of_compra > 0 and of_venda > 0) else 5.0
        spread_penalized = spread_pts > 10.0

        # 2. Imbalance Ratio na direção do trade
        total_vol = voc + vov
        if total_vol > 0:
            imbalance_compra = voc / total_vol
            imbalance_venda = vov / total_vol
        else:
            imbalance_compra = 0.5
            imbalance_venda = 0.5

        imbalance_ratio = imbalance_compra if side_norm == "COMPRA" else imbalance_venda

        # 3. Análise de Escora / Recarga Passiva (ESCORA_PASSIVA)
        is_escora = False
        if side_norm == "COMPRA":
            # Escora compradora: VOC >= 1.5 * VOV com delta_voc > 0 sustentando nível
            if vov > 0 and voc >= 1.5 * vov and delta_voc > 0:
                is_escora = True
        else:
            # Escora vendedora: VOV >= 1.5 * VOC com delta_vov > 0 sustentando nível
            if voc > 0 and vov >= 1.5 * voc and delta_vov > 0:
                is_escora = True

        # 4. Análise de Blefe / Cancelamento Brusco (BLEFE_PULLING)
        is_blefe = False
        pulling_pct = 0.0
        if side_norm == "COMPRA":
            voc_anterior = voc - delta_voc
            if voc_anterior > 50 and delta_voc < -0.40 * voc_anterior:
                # Queda > 40% sem aumento equivalente em negócios executados
                if delta_negocios < abs(delta_voc) * 0.35:
                    is_blefe = True
                    pulling_pct = abs(delta_voc) / voc_anterior * 100.0
        else:
            vov_anterior = vov - delta_vov
            if vov_anterior > 50 and delta_vov < -0.40 * vov_anterior:
                if delta_negocios < abs(delta_vov) * 0.35:
                    is_blefe = True
                    pulling_pct = abs(delta_vov) / vov_anterior * 100.0

        # 5. Cálculo do Score e Status Tag
        reasons: List[str] = []
        observed_behavior: str = ""

        if is_blefe:
            status_tag = "BLEFE_PULLING"
            # Score penalizado severamente (< 40)
            score = max(15.0, 35.0 - (pulling_pct - 40.0) * 0.3)
            bias = "VENDA" if side_norm == "COMPRA" else "COMPRA"  # Blefe indica fraqueza do lado que puxou
            reasons.append(f"Queda brusca de {pulling_pct:.1f}% nas ofertas sem execuções equivalentes")
            reasons.append(f"Padrão compatível com cancelamento rápido (Pulling) de {abs(int(delta_voc if side_norm == 'COMPRA' else delta_vov))} contratos")
            reasons.append("Liquidez passiva retirada antes da chegada do preço")
            observed_behavior = f"Padrão compatível com blefe: retirada rápida de liquidez ({pulling_pct:.0f}%)"

        elif is_escora:
            status_tag = "ESCORA_PASSIVA"
            ratio_val = (voc / vov) if (side_norm == "COMPRA" and vov > 0) else ((vov / voc) if voc > 0 else 2.0)
            # Score robusto (80 a 100)
            score = min(100.0, 80.0 + min(20.0, (ratio_val - 1.5) * 10.0))
            bias = side_norm
            defensor = "compradora" if side_norm == "COMPRA" else "vendedora"
            reasons.append(f"Escora {defensor} expressiva: {int(voc if side_norm == 'COMPRA' else vov)}ct vs {int(vov if side_norm == 'COMPRA' else voc)}ct ({ratio_val:.1f}x)")
            reasons.append(f"Recarga defensiva confirmada no book (delta de +{int(delta_voc if side_norm == 'COMPRA' else delta_vov)} contratos)")
            reasons.append("Sustentação passiva favorável à continuidade imediata")
            observed_behavior = f"Escora passiva confirmada: concentração {defensor} ({ratio_val:.1f}x)"

        else:
            # Livro regular / distribuído
            if imbalance_ratio >= 0.58:
                status_tag = "ALINHADO"
                score = 55.0 + (imbalance_ratio - 0.58) * 60.0
                bias = side_norm
                reasons.append(f"Predomínio de liquidez no sentido da operação ({imbalance_ratio*100:.1f}%)")
                observed_behavior = f"Comportamento de oferta observado: {imbalance_ratio*100:.0f}% a favor"
            elif imbalance_ratio <= 0.42:
                status_tag = "DIVERGENTE"
                score = max(20.0, 50.0 - (0.42 - imbalance_ratio) * 70.0)
                bias = "VENDA" if side_norm == "COMPRA" else "COMPRA"
                reasons.append(f"Livro adverso contra a ponta ({imbalance_ratio*100:.1f}% favorável)")
                observed_behavior = f"Pressão contrária no livro ({imbalance_ratio*100:.0f}%)"
            else:
                status_tag = "ALINHADO"
                score = 50.0
                bias = "NEUTRO"
                reasons.append("Livro distribuído em equilíbrio relativo entre as pontas")
                observed_behavior = "Livro distribuído sem concentração anômala"

        # Penalização por spread aberto (> 10 pts)
        if spread_penalized:
            score = max(5.0, score - 15.0)
            reasons.append(f"Spread aberto ({spread_pts:.0f} pts) acima da tolerância")

        # Garante no máximo 3 razões
        reasons = reasons[:3]

        # 6. Publicação estruturada em context['book_insights']
        book_insights = {
            "spread_pts": spread_pts,
            "imbalance_ratio": round(imbalance_ratio, 3),
            "voc": voc,
            "vov": vov,
            "delta_voc": delta_voc,
            "delta_vov": delta_vov,
            "is_escora": is_escora,
            "is_blefe": is_blefe,
            "i_book": round(imbalance_ratio, 3),  # Insumo direto para o ZoneViolationDefenseAgent
            "status_tag": status_tag,
            "observed_behavior": observed_behavior,
            "metrics": {
                "spread_pts": spread_pts,
                "voc": voc,
                "vov": vov,
                "imbalance_pct": round(imbalance_ratio * 100.0, 1),
                "delta_voc": delta_voc,
                "delta_vov": delta_vov
            }
        }
        context["book_insights"] = book_insights

        return AgentVerdict(
            agent_name=self.agent_name,
            weight=self.weight,
            bias=bias,
            score=round(score, 1),
            status_tag=status_tag,
            reasons=reasons,
            metrics=book_insights
        )
