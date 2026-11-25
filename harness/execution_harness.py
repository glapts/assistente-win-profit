"""
harness/execution_harness.py
Execution Harness e Orquestrador dos 7 Agentes Especialistas de Alta Concorrência.
Calcula o Índice de Previsibilidade Ponderado (Score_Final), classifica a confluência (Modo Demo),
renderiza o painel ANSI no terminal e despacha a telemetria para o gravador JSONL.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import colorama
from colorama import Fore, Back, Style

colorama.init(autoreset=True)

from agents.base_agent import AgentVerdict
from agents.order_book_agent import OrderBookAgent
from agents.zone_violation_agent import ZoneViolationDefenseAgent
from agents.pullback_value_agent import PullbackValueZoneAgent
from agents.extremes_tape_agent import ExtremesTapeAgent
from agents.macro_rates_agent import MacroRatesAgent
from agents.bluechips_flow_agent import BlueChipsFlowAgent
from agents.global_index_agent import GlobalIndexAgent
from harness.telemetry_logger import TelemetryLogger


@dataclass
class HarnessVerdict:
    """Consolidado de avaliação dos 7 agentes especialistas."""
    score_final: float
    classification: str
    side: str
    agent_verdicts: Dict[str, AgentVerdict]
    book_insights: Dict[str, Any]
    p_defesa: float
    p_medio_reacao: float
    panel_text: str = ""


class ExecutionHarness:
    """
    Motor central determinístico de orquestração.
    Executa os 7 agentes especialistas com prioridade estrita para o OrderBookAgent (alimentando context),
    calcula o Score Final Ponderado e gera a Seção 4 para exibição no PowerShell.
    """

    # Pesos Canônicos dos 7 Agentes Especialistas (Soma exata = 1.00)
    WEIGHT_ZONA_DEFESA = 0.20
    WEIGHT_PULLBACK_SMC = 0.20
    WEIGHT_TAPE_MEDIA = 0.20
    WEIGHT_ORDER_BOOK = 0.15
    WEIGHT_MACRO_RATES = 0.12
    WEIGHT_BLUE_CHIPS = 0.08
    WEIGHT_GLOBAL_INDEX = 0.05

    def __init__(self, logger: Optional[TelemetryLogger] = None):
        self.logger = logger or TelemetryLogger()

        # Instanciação dos 7 Agentes com seus respectivos pesos
        self.order_book_agent = OrderBookAgent(weight=self.WEIGHT_ORDER_BOOK)
        self.zone_defense_agent = ZoneViolationDefenseAgent(weight=self.WEIGHT_ZONA_DEFESA)
        self.pullback_value_agent = PullbackValueZoneAgent(weight=self.WEIGHT_PULLBACK_SMC)
        self.extremes_tape_agent = ExtremesTapeAgent(weight=self.WEIGHT_TAPE_MEDIA)
        self.macro_rates_agent = MacroRatesAgent(weight=self.WEIGHT_MACRO_RATES)
        self.bluechips_flow_agent = BlueChipsFlowAgent(weight=self.WEIGHT_BLUE_CHIPS)
        self.global_index_agent = GlobalIndexAgent(weight=self.WEIGHT_GLOBAL_INDEX)

    def evaluate_market_confluence(
        self,
        side: str,
        context: Dict[str, Any],
        setup_name: Optional[str] = None,
        entry_price: Optional[float] = None,
        use_color: bool = True
    ) -> HarnessVerdict:
        """
        Executa o pipeline determinístico completo de avaliação:
        1. Executa primeiro o OrderBookAgent para popular context['book_insights'] (I_book, escora, blefe).
        2. Executa os outros 6 agentes especializados.
        3. Calcula o Índice de Previsibilidade Ponderado (Score_Final).
        4. Classifica o sinal sem bloquear nada (Modo Demo).
        5. Renderiza a Seção 4 em ANSI colorido.
        6. Persiste a telemetria em JSONL.
        """
        side_norm = side.upper().strip() if isinstance(side, str) else "NEUTRO"
        if side_norm not in ("COMPRA", "VENDA"):
            side_norm = "COMPRA"

        # ── 1. Executa primeiro o OrderBookAgent ──
        verdict_book = self.order_book_agent.evaluate(side_norm, context)
        book_insights = context.get("book_insights") or verdict_book.metrics

        # ── 2. Executa os outros 6 agentes consumindo o contexto enriquecido ──
        verdict_zone = self.zone_defense_agent.evaluate(side_norm, context)
        verdict_pullback = self.pullback_value_agent.evaluate(side_norm, context)
        verdict_tape = self.extremes_tape_agent.evaluate(side_norm, context)
        verdict_macro = self.macro_rates_agent.evaluate(side_norm, context)
        verdict_blue = self.bluechips_flow_agent.evaluate(side_norm, context)
        verdict_global = self.global_index_agent.evaluate(side_norm, context)

        verdicts: Dict[str, AgentVerdict] = {
            "OrderBookAgent": verdict_book,
            "ZoneViolationDefenseAgent": verdict_zone,
            "PullbackValueZoneAgent": verdict_pullback,
            "ExtremesTapeAgent": verdict_tape,
            "MacroRatesAgent": verdict_macro,
            "BlueChipsFlowAgent": verdict_blue,
            "GlobalIndexAgent": verdict_global
        }

        # ── 3. Cálculo do Índice de Previsibilidade Ponderado ──
        score_final = (
            self.WEIGHT_ZONA_DEFESA * verdict_zone.score +
            self.WEIGHT_PULLBACK_SMC * verdict_pullback.score +
            self.WEIGHT_TAPE_MEDIA * verdict_tape.score +
            self.WEIGHT_ORDER_BOOK * verdict_book.score +
            self.WEIGHT_MACRO_RATES * verdict_macro.score +
            self.WEIGHT_BLUE_CHIPS * verdict_blue.score +
            self.WEIGHT_GLOBAL_INDEX * verdict_global.score
        )
        score_final = round(min(100.0, max(0.0, score_final)), 1)

        # ── 4. Classificação sem bloqueio (Modo Demo) ──
        if score_final >= 75.0:
            classification = "FAVORÁVEL (CONFLUÊNCIA ALTA)"
        elif score_final >= 50.0:
            classification = "MODERADO (CONFIRMAR ESTRUTURA)"
        else:
            classification = "CAUTELA (CONTRA-FLUXO, BLEFE NO BOOK OU ESTICADO)"

        # Extração das métricas chave de microestrutura
        p_defesa = float(verdict_zone.metrics.get("p_defesa", verdict_zone.score))
        p_medio_reacao = float(verdict_tape.metrics.get("p_medio_reacao", context.get("current_price", 0.0)))

        # ── 5. Renderização em ANSI Colorido do Painel 4 ──
        panel_text = self._render_panel(
            side=side_norm,
            score_final=score_final,
            classification=classification,
            verdicts=verdicts,
            use_color=use_color
        )

        # ── 6. Persistência de Telemetria em JSONL ──
        dde_summary = {}
        if "dde_snapshot" in context:
            snap = context["dde_snapshot"]
            if hasattr(snap, "assets"):
                dde_summary = {
                    sym: {
                        "ultimo": a.ultimo,
                        "variacao": a.variacao,
                        "saldo": a.saldo_agressao,
                        "voc": a.voc,
                        "vov": a.vov
                    }
                    for sym, a in snap.assets.items()
                }

        self.logger.log_evaluation(
            side=side_norm,
            score_final=score_final,
            classification=classification,
            verdicts=verdicts,
            book_insights=book_insights,
            p_defesa=p_defesa,
            p_medio_reacao=p_medio_reacao,
            dde_summary=dde_summary,
            setup_name=setup_name,
            entry_price=entry_price
        )

        return HarnessVerdict(
            score_final=score_final,
            classification=classification,
            side=side_norm,
            agent_verdicts=verdicts,
            book_insights=book_insights,
            p_defesa=p_defesa,
            p_medio_reacao=p_medio_reacao,
            panel_text=panel_text
        )

    def _render_panel(
        self,
        side: str,
        score_final: float,
        classification: str,
        verdicts: Dict[str, AgentVerdict],
        use_color: bool = True
    ) -> str:
        """Renderiza a Seção 4: PAINEL DE DECISÃO MULTI-AGENTE."""
        C_DIV = (Fore.CYAN + Style.DIM) if use_color else ""
        C_RESET = Style.RESET_ALL if use_color else ""
        C_LABEL = (Fore.WHITE + Style.BRIGHT) if use_color else ""

        if use_color:
            if score_final >= 75.0:
                c_score = Back.GREEN + Fore.BLACK + Style.BRIGHT
                c_class = Fore.GREEN + Style.BRIGHT
            elif score_final >= 50.0:
                c_score = Back.YELLOW + Fore.BLACK + Style.BRIGHT
                c_class = Fore.YELLOW + Style.BRIGHT
            else:
                c_score = Back.RED + Fore.WHITE + Style.BRIGHT
                c_class = Fore.RED + Style.BRIGHT
        else:
            c_score = ""
            c_class = ""

        div_main = f"{C_DIV}=================================================================={C_RESET}"
        div_sub = f"{C_DIV}------------------------------------------------------------------{C_RESET}"

        lines = []
        lines.append(div_main)
        lines.append(f"{C_LABEL}4. PAINEL DE DECISÃO MULTI-AGENTE (HARNESS ZONA + PULLBACK + BOOK + DDE + TAPE) [DEMO]:{C_RESET}")
        lines.append(f"  * STATUS OPERACIONAL          : {Fore.CYAN + Style.BRIGHT if use_color else ''}MODO DEMO ATIVO (SINAIS ORIGINAIS 100% LIBERADOS){C_RESET}")
        lines.append(f"  * ÍNDICE DE PREVISIBILIDADE   : {c_score} {score_final:.1f}% {C_RESET} | CLASSIFICAÇÃO: {c_class}{classification}{C_RESET}")
        lines.append(div_sub)
        lines.append(f"  {'AGENTE ESPECIALISTA':<28} {'PESO':<6} {'SCORE':<7} {'STATUS':<20} {'PRINCIPAL INSIGHT'}")
        lines.append(f"  {'-'*28} {'-'*6} {'-'*7} {'-'*20} {'-'*30}")

        agents_display_order = [
            ("ZoneViolationDefenseAgent", "ZonaDefesa (0.20)", self.WEIGHT_ZONA_DEFESA),
            ("PullbackValueZoneAgent", "PullbackSMC (0.20)", self.WEIGHT_PULLBACK_SMC),
            ("ExtremesTapeAgent", "TapeMedia (0.20)", self.WEIGHT_TAPE_MEDIA),
            ("OrderBookAgent", "OrderBook (0.15)", self.WEIGHT_ORDER_BOOK),
            ("MacroRatesAgent", "MacroRates (0.12)", self.WEIGHT_MACRO_RATES),
            ("BlueChipsFlowAgent", "BlueChips (0.08)", self.WEIGHT_BLUE_CHIPS),
            ("GlobalIndexAgent", "GlobalIndex (0.05)", self.WEIGHT_GLOBAL_INDEX)
        ]

        for key, display_name, weight in agents_display_order:
            v = verdicts.get(key)
            if v is not None:
                score_str = f"{v.score:.1f}"
                status_str = v.status_tag
                primary_reason = v.reasons[0] if v.reasons else "Sem observações"
                if len(primary_reason) > 52:
                    primary_reason = primary_reason[:49] + "..."

                if use_color:
                    if v.score >= 75.0:
                        c_agent_score = Fore.GREEN + Style.BRIGHT
                    elif v.score >= 50.0:
                        c_agent_score = Fore.YELLOW
                    else:
                        c_agent_score = Fore.RED + Style.BRIGHT

                    if v.status_tag in ("REACAO_FORTE_DEFESA", "ESCORA_PASSIVA", "PULLBACK_VALIDO", "ALINHADO"):
                        c_status = Fore.GREEN
                    elif v.status_tag in ("ESTICADO", "BLEFE_PULLING", "COMPRA_VENCIDA", "VENDA_VENCIDA", "DIVERGENTE"):
                        c_status = Fore.RED + Style.BRIGHT
                    else:
                        c_status = Fore.YELLOW
                else:
                    c_agent_score = ""
                    c_status = ""

                lines.append(
                    f"  {display_name:<28} {weight:<6.2f} {c_agent_score}{score_str:<7}{C_RESET} {c_status}{status_str:<20}{C_RESET} {primary_reason}"
                )

        lines.append(div_main)
        return "\n".join(lines)
