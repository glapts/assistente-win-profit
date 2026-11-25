"""
agents/pullback_value_agent.py
Agente 3 do Execution Harness — Avaliador de Pullback e Zonas de Valor (PullbackValueZoneAgent).
Peso: 0.20. Aplica a Regra ANTI-ESTICADO obrigatória e valida confluência de retração
em Order Blocks (OB) ou FVGs de 15m, 10m e 5m (incluindo Consequent Encroachment 50% CE).
"""

from typing import Dict, Any, List, Optional
from agents.base_agent import BaseSpecialistAgent, AgentVerdict


class PullbackValueZoneAgent(BaseSpecialistAgent):
    """
    Agente Especialista de Localização e Zonas de Valor Institucional.
    Regra ANTI-ESTICADO:
    - Em tendência de ALTA: NUNCA valida compra no topo esticado (Score = 0.0, status_tag = 'ESTICADO').
    - Em tendência de BAIXA: NUNCA valida venda no fundo esticado (Score = 0.0, status_tag = 'ESTICADO').
    - Validação de retração (Pullback) em FVG/OB (15m, 10m, 5m com 50% CE): pontuação 85 a 100.
    """

    def __init__(self, weight: float = 0.20):
        super().__init__(agent_name="PullbackValueZoneAgent", weight=weight)

    def evaluate(self, side: str, context: Dict[str, Any]) -> AgentVerdict:
        side_norm = side.upper().strip() if isinstance(side, str) else "NEUTRO"
        if side_norm not in ("COMPRA", "VENDA"):
            side_norm = "COMPRA"

        current_p = float(context.get("current_price", context.get("ultimo", 0.0)))
        if current_p <= 0.0 and "win_snapshot" in context:
            current_p = getattr(context["win_snapshot"], "ultimo", 0.0)

        # Tendência e regime de mercado (60m, 30m, 15m)
        trend = str(context.get("trend", context.get("regime", "ALTA"))).upper()
        if "COMPRA" in trend or "ALTA" in trend:
            trend_dir = "ALTA"
        elif "VENDA" in trend or "BAIXA" in trend:
            trend_dir = "BAIXA"
        else:
            trend_dir = "CONSOLIDACAO"

        # Indicador explícito de esticado ou detecção por distância de suporte/resistência
        is_stretched_flag = bool(context.get("is_stretched", False))
        pullback_confirmed = bool(context.get("is_pullback", False) or context.get("pullback_confirmed", False))

        # Obtenção de zonas ativas de FVG ou Order Blocks (15m, 10m, 5m)
        active_fvgs = context.get("active_fvgs") or context.get("fvgs") or []
        active_obs = context.get("active_obs") or context.get("order_blocks") or []

        # Detecção de zona de valor em teste
        matched_zone = None
        min_dist_to_zone = 9999.0
        zone_tf = 5

        all_zones = []
        # Normalização de zonas FVG/OB recebidas
        for f in active_fvgs:
            tf = getattr(f, "timeframe", None) or (f.get("timeframe") if isinstance(f, dict) else 5)
            if tf in (5, 10, 15, 30, 60):
                top = getattr(f, "top", None) if hasattr(f, "top") else (f.get("top", 0.0) if isinstance(f, dict) else 0.0)
                bot = getattr(f, "bottom", None) if hasattr(f, "bottom") else (f.get("bottom", 0.0) if isinstance(f, dict) else 0.0)
                ce = getattr(f, "ce_50", None) if hasattr(f, "ce_50") else (f.get("ce_50", (top + bot)/2.0) if isinstance(f, dict) else 0.0)
                d = getattr(f, "direction", "BULLISH") if hasattr(f, "direction") else (f.get("direction", "BULLISH") if isinstance(f, dict) else "BULLISH")
                all_zones.append({"type": "FVG", "timeframe": tf, "top": top, "bottom": bot, "ce_50": ce, "direction": d})

        for ob in active_obs:
            tf = getattr(ob, "timeframe", None) or (ob.get("timeframe") if isinstance(ob, dict) else 5)
            if tf in (5, 10, 15):
                top = getattr(ob, "top", None) if hasattr(ob, "top") else (ob.get("top", 0.0) if isinstance(ob, dict) else 0.0)
                bot = getattr(ob, "bottom", None) if hasattr(ob, "bottom") else (ob.get("bottom", 0.0) if isinstance(ob, dict) else 0.0)
                ce = (top + bot) / 2.0
                all_zones.append({"type": "OB", "timeframe": tf, "top": top, "bottom": bot, "ce_50": ce, "direction": "BULLISH" if side_norm == "COMPRA" else "BEARISH"})

        # Se houver zonas mapeadas, calcula proximidade do preço atual
        for z in all_zones:
            top_val = z["top"]
            bot_val = z["bottom"]
            ce_val = z["ce_50"]
            if bot_val <= current_p <= top_val or abs(current_p - ce_val) <= 25.0:
                matched_zone = z
                min_dist_to_zone = 0.0
                zone_tf = z["timeframe"]
                pullback_confirmed = True
                break
            else:
                dist = min(abs(current_p - top_val), abs(current_p - bot_val), abs(current_p - ce_val))
                if dist < min_dist_to_zone:
                    min_dist_to_zone = dist
                    zone_tf = z["timeframe"]

        # Se o contexto fornecer retração explícita (ex: teste unitário ou setup canônico de pullback)
        if context.get("pullback_zone"):
            pz = context["pullback_zone"]
            matched_zone = {
                "type": pz.get("type", "FVG"),
                "timeframe": pz.get("timeframe", 15),
                "top": pz.get("top", current_p + 10),
                "bottom": pz.get("bottom", current_p - 10),
                "ce_50": pz.get("ce_50", current_p)
            }
            pullback_confirmed = True
            is_stretched_flag = False

        # Avaliação de Esticado: se distância da zona for grande (> 80 pontos) e sem teste
        if not pullback_confirmed:
            dist_pts = float(context.get("distancia_suporte_pts", context.get("distancia_resistencia_pts", min_dist_to_zone)))
            if dist_pts > 80.0 or is_stretched_flag:
                is_stretched_flag = True

        reasons: List[str] = []

        # --- APLICAÇÃO DA REGRA ANTI-ESTICADO ---
        if side_norm == "COMPRA":
            if is_stretched_flag:
                status_tag = "ESTICADO"
                bias = "NEUTRO"
                score = 0.0  # NUNCA valida compra no movimento esticado
                reasons.append("Movimento de alta esticado longe do suporte de 15m/10m/5m")
                reasons.append("Regra Anti-Esticado ativa: compra no topo estritamente bloqueada")
                reasons.append("Aguardar retração institucional (pullback) até FVG ou Order Block")

            elif pullback_confirmed and matched_zone:
                status_tag = "PULLBACK_VALIDO"
                bias = "COMPRA"
                ce_val = matched_zone["ce_50"]
                tf_val = matched_zone["timeframe"]
                z_type = matched_zone["type"]
                # Confluência de pullback pontua 85 a 100
                score = 85.0 + (15.0 if tf_val in (10, 15) else 8.0)
                score = min(100.0, score)
                reasons.append(f"Pullback institucional confirmado em {z_type} de {tf_val}m")
                reasons.append(f"Preço retestando zona de valor de desconto (CE 50%: {ce_val:.0f})")
                reasons.append("Excelente assimetria de retorno/risco a favor da tendência de alta")

            else:
                # Transição / Não esticado mas sem FVG imediato
                status_tag = "ALINHADO"
                bias = "COMPRA"
                score = 65.0
                reasons.append("Preço em localização neutra sem violação de extremos")
                reasons.append("Assimetria moderada próxima da média da sessão")

        else:  # VENDA
            if is_stretched_flag:
                status_tag = "ESTICADO"
                bias = "NEUTRO"
                score = 0.0  # NUNCA valida venda no movimento esticado
                reasons.append("Movimento de baixa esticado longe da resistência de 15m/10m/5m")
                reasons.append("Regra Anti-Esticado ativa: venda no fundo estritamente bloqueada")
                reasons.append("Aguardar retração institucional (pullback) até FVG ou Order Block")

            elif pullback_confirmed and matched_zone:
                status_tag = "PULLBACK_VALIDO"
                bias = "VENDA"
                ce_val = matched_zone["ce_50"]
                tf_val = matched_zone["timeframe"]
                z_type = matched_zone["type"]
                score = 85.0 + (15.0 if tf_val in (10, 15) else 8.0)
                score = min(100.0, score)
                reasons.append(f"Pullback institucional confirmado em {z_type} de {tf_val}m")
                reasons.append(f"Preço retestando zona de valor de prêmio (CE 50%: {ce_val:.0f})")
                reasons.append("Excelente assimetria de retorno/risco a favor da tendência de baixa")

            else:
                status_tag = "ALINHADO"
                bias = "VENDA"
                score = 65.0
                reasons.append("Preço em localização intermediária sem rompimento esticado")
                reasons.append("Aguardando confirmação de gatilho em tempo menor")

        reasons = reasons[:3]

        value_insights = {
            "current_price": current_p,
            "trend": trend_dir,
            "is_stretched": is_stretched_flag,
            "pullback_confirmed": pullback_confirmed,
            "matched_zone": matched_zone,
            "score": score,
            "status_tag": status_tag
        }
        context["value_zone_insights"] = value_insights

        return AgentVerdict(
            agent_name=self.agent_name,
            weight=self.weight,
            bias=bias,
            score=score,
            status_tag=status_tag,
            reasons=reasons,
            metrics=value_insights
        )
