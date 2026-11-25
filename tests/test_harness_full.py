"""
tests/test_harness_full.py
Bateria de Testes Canônica e Validação Completa da Arquitetura Multi-Agente & Execution Harness.
Simula 5 cenários operacionais completos no PowerShell, renderizando a saída ANSI integral
e registrando a telemetria auditável em logs/signals_telemetry.jsonl.
"""

import sys
import os
import unittest
import json
from datetime import datetime, timedelta
import colorama
from colorama import Fore, Back, Style

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

colorama.init(autoreset=True)

from core.models import SignalSetup, SetupStatus, Direction
from core.contract import get_current_win_contract, TZ_BRASILIA
from analysis.alert_formatter import format_operational_alert
from harness.execution_harness import ExecutionHarness, HarnessVerdict
from harness.telemetry_logger import TelemetryLogger
from harness.dde_snapshot import HarnessFullSnapshot, AssetSnapshot


def _make_asset(symbol: str, ultimo: float, var: float = 0.0, saldo: float = 0.0,
                voc: float = 0.0, vov: float = 0.0, neg: int = 150, abertura: float = 0.0) -> AssetSnapshot:
    """Cria um snapshot de ativo DDE válido com volume e negócios consistentes."""
    return AssetSnapshot(
        symbol=symbol,
        timestamp=datetime.now(TZ_BRASILIA),
        ultimo=ultimo,
        abertura=abertura or ultimo,
        variacao=var,
        negocios=neg,
        quantidade=2500.0,
        of_compra=ultimo - (0.5 if "WDO" in symbol or "DI" in symbol else 5.0),
        of_venda=ultimo,
        voc=voc,
        vov=vov,
        saldo_agressao=saldo
    )


class TestHarnessFullScenarios(unittest.TestCase):
    """Bateria oficial de validação dos 5 cenários do Execution Harness."""

    @classmethod
    def setUpClass(cls):
        cls.harness = ExecutionHarness()
        cls.log_file = os.path.join(PROJECT_DIR, "logs", "signals_telemetry.jsonl")

    def _get_log_tail_count(self) -> int:
        if not os.path.exists(self.log_file):
            return 0
        with open(self.log_file, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())

    # =========================================================================
    # CENÁRIO 1: VENDA em Topo / Pullback FVG 5m-15m com Absorção e Escora Vendedora
    # =========================================================================
    def test_cenario_1_venda_topo_absorcao_escora(self):
        """
        Cenário 1:
        - Delta +23.374 comprado absorvido com deslocamento de -45 pts
        - Preço abaixo da Média Aritmética de Reação T&T
        - VOV > VOC com stacking vendedor no OrderBookAgent
        - DI1F29 / DI1F31 / WDOZ26 subindo
        - Blue Chips e WSPZ26 caindo
        """
        now = datetime.now(TZ_BRASILIA)
        symbol = get_current_win_contract()
        initial_log_count = self._get_log_tail_count()

        # 1. Snapshot DDE Macro Alinhado para VENDA
        snap = HarnessFullSnapshot(timestamp=now)
        snap.assets["WINZ26"] = _make_asset("WINZ26", 171455.0, var=-0.35, saldo=-12500.0, voc=1200.0, vov=3200.0)
        snap.assets["DI1F29"] = _make_asset("DI1F29", 12.45, var=+0.55, saldo=+4500.0)
        snap.assets["DI1F31"] = _make_asset("DI1F31", 12.80, var=+0.48, saldo=+3800.0)
        snap.assets["WDOZ26"] = _make_asset("WDOZ26", 5510.0, var=+0.72, saldo=+6200.0, voc=2800.0, vov=1100.0)
        snap.assets["ITUB4"] = _make_asset("ITUB4", 34.20, var=-1.25, saldo=-420000.0, voc=70000.0, vov=210000.0)
        snap.assets["PETR4"] = _make_asset("PETR4", 38.60, var=-1.60, saldo=-680000.0, voc=85000.0, vov=340000.0)
        snap.assets["VALE3"] = _make_asset("VALE3", 62.80, var=-1.10, saldo=-310000.0, voc=75000.0, vov=200000.0)
        snap.assets["WSPZ26"] = _make_asset("WSPZ26", 5960.0, var=-0.65, saldo=-4800.0, abertura=6000.0)

        # 2. Contexto Operacional com Absorção e Reação Direcional
        p_medio_reacao = 171500.0
        current_p = 171455.0  # Preço abaixo da média aritmética de reação (171455 < 171500)

        context = {
            "current_price": current_p,
            "ultimo": current_p,
            "dde_snapshot": snap,
            # Book com Escora Vendedora (VOV >= 1.5 * VOC e delta_vov > 0)
            "win_book": {
                "of_compra": 171450.0,
                "of_venda": 171455.0,
                "spread_pts": 5.0,
                "voc": 1200.0,
                "vov": 3200.0,
                "delta_voc": -200.0,
                "delta_vov": 800.0,
                "delta_negocios": 45
            },
            # Zona de Defesa no Topo [171450 - 171550]
            "zone": (171450.0, 171550.0),
            "l_inf": 171450.0,
            "l_sup": 171550.0,
            "v_c": 1800.0,
            "v_v": 5200.0,
            "delta_P_afastamento": 95.0,  # 171550 - 171455 = 95 pts de afastamento do topo
            # Pullback FVG 15m/5m ativo
            "pullback_zone": {
                "type": "FVG",
                "timeframe": 15,
                "top": 171550.0,
                "bottom": 171450.0,
                "ce_50": 171500.0,
                "direction": "BEARISH"
            },
            # Times & Trades: Delta +23.374 comprado absorvido com deslocamento de -45 pts
            "flow_metrics": {
                "buy_volume": 32000,
                "sell_volume": 8626,
                "delta": +23374,
                "price_displacement_pts": -45.0,
                "trades_count": 480,
                "absorcao_detectada": True,
                "flow_pattern": "Absorção vendedora no topo: delta comprador de +23.374 absorvido",
                "large_trades": [
                    {"qty": 500, "price": 171500.0, "side": "SELL"},
                    {"qty": 400, "price": 171490.0, "side": "SELL"},
                    {"qty": 350, "price": 171480.0, "side": "SELL"}
                ]
            },
            "p_medio_reacao": p_medio_reacao
        }

        setup = SignalSetup(
            timestamp=now,
            setup_name="Venda por Pullback em FVG 15m com Absorção Institucional no Topo",
            direction=Direction.VENDA,
            symbol=symbol,
            status=SetupStatus.CONFIRMADO,
            entry_price=171455.0,
            stop_price=171705.0,
            stop_points=250.0,
            target_price=171055.0,
            target_points=400.0,
            risk_reward=1.60,
            timeframe_trigger=15,
            in_trend_direction=True,
            structure_event="Rejeição de topo no 15m com absorção massiva da agressão compradora",
            obstacles=["PASSAGEM LIVRE: Vácuo de liquidez mapeado até 171.055 (-400 pontos)"],
            facts_observed=[
                "Preço: 171.455 (abaixo da Média Aritmética de Reação T&T: 171.500)",
                "Times & Trades: DELTA=+23.374 contratos compradores absorvidos pela venda passiva",
                "Deslocamento do preço: -45 pontos contrariando agressão compradora",
                "OrderBook: VOV 3.200 ct vs VOC 1.200 ct (Escora vendedora 2.7x)"
            ],
            interpretations=[
                "Absorção institucional vendedora perfeita confirmada no topo.",
                "Execução autorizada no SuperDOM na coluna vermelha (Alvo 400 pts / Stop 250 pts)."
            ],
            limitations=["Oscilação padrão de mercado"],
            invalidation_criteria="Superação de 171.705 com fechamento de candle"
        )

        regimes = {"240m": "BAIXA", "60m": "BAIXA", "15m": "BAIXA", "5m": "BAIXA", "1m": "BAIXA"}

        verdict = self.harness.evaluate_market_confluence(
            side="VENDA",
            context=context,
            setup_name=setup.setup_name,
            entry_price=setup.entry_price,
            use_color=True
        )

        alert_text = format_operational_alert(
            setup=setup,
            regimes=regimes,
            source_name="Nelogica ProfitPro (DDE)",
            delay_ms=0.4,
            quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
            flow_data=context["flow_metrics"],
            symbol_override=f"{symbol} (Mini-Índice B3)",
            use_color=True,
            harness_verdict=verdict,
            p_medio_reacao=verdict.p_medio_reacao
        )

        print("\n" + "=" * 80)
        print(Fore.CYAN + Style.BRIGHT + ">>> CENÁRIO 1/5: VENDA EM TOPO / PULLBACK FVG COM ABSORÇÃO E ESCORA VENDEDORA <<<" + Style.RESET_ALL)
        print("=" * 80)
        print(alert_text)
        print("=" * 80 + "\n")

        # Validações Estruturais do Cenário 1
        self.assertGreaterEqual(verdict.score_final, 75.0, f"Score esperado >= 75.0, obtido: {verdict.score_final}")
        self.assertEqual(verdict.classification, "FAVORÁVEL (CONFLUÊNCIA ALTA)")
        self.assertEqual(verdict.agent_verdicts["ExtremesTapeAgent"].status_tag, "REACAO_FORTE_DEFESA")
        self.assertEqual(verdict.agent_verdicts["OrderBookAgent"].status_tag, "ESCORA_PASSIVA")
        self.assertEqual(verdict.agent_verdicts["MacroRatesAgent"].bias, "VENDA")
        self.assertEqual(verdict.agent_verdicts["BlueChipsFlowAgent"].bias, "VENDA")
        self.assertEqual(verdict.agent_verdicts["GlobalIndexAgent"].bias, "VENDA")
        self.assertGreater(self._get_log_tail_count(), initial_log_count)

    # =========================================================================
    # CENÁRIO 2: COMPRA em Fundo / Pullback OB 10m-15m com Absorção e Escora Compradora
    # =========================================================================
    def test_cenario_2_compra_fundo_absorcao_escora(self):
        """
        Cenário 2:
        - Delta -18.500 vendido absorvido com deslocamento de +40 pts
        - Preço evoluindo acima da Média Aritmética de Reação T&T
        - VOC > VOV com stacking comprador no OrderBookAgent
        - DI1F29 / DI1F31 / WDOZ26 caindo
        - Blue Chips e WSPZ26 subindo
        """
        now = datetime.now(TZ_BRASILIA)
        symbol = get_current_win_contract()
        initial_log_count = self._get_log_tail_count()

        # 1. Snapshot DDE Macro Alinhado para COMPRA (Risk-On)
        snap = HarnessFullSnapshot(timestamp=now)
        snap.assets["WINZ26"] = _make_asset("WINZ26", 169840.0, var=+0.65, saldo=+14200.0, voc=3500.0, vov=1300.0)
        snap.assets["DI1F29"] = _make_asset("DI1F29", 12.15, var=-0.45, saldo=-4200.0)
        snap.assets["DI1F31"] = _make_asset("DI1F31", 12.40, var=-0.40, saldo=-3600.0)
        snap.assets["WDOZ26"] = _make_asset("WDOZ26", 5460.0, var=-0.68, saldo=-7500.0, voc=950.0, vov=2500.0)
        snap.assets["ITUB4"] = _make_asset("ITUB4", 35.40, var=+1.20, saldo=+410000.0, voc=230000.0, vov=75000.0)
        snap.assets["PETR4"] = _make_asset("PETR4", 39.70, var=+1.85, saldo=+750000.0, voc=360000.0, vov=110000.0)
        snap.assets["VALE3"] = _make_asset("VALE3", 64.10, var=+0.95, saldo=+290000.0, voc=180000.0, vov=85000.0)
        snap.assets["WSPZ26"] = _make_asset("WSPZ26", 6025.0, var=+0.75, saldo=+5200.0, abertura=5980.0)

        # 2. Contexto Operacional com Absorção Compradora
        p_medio_reacao = 169800.0
        current_p = 169840.0  # Preço evoluindo acima da média aritmética de reação (169840 > 169800)

        context = {
            "current_price": current_p,
            "ultimo": current_p,
            "dde_snapshot": snap,
            # Book com Escora Compradora (VOC >= 1.5 * VOV e delta_voc > 0)
            "win_book": {
                "of_compra": 169835.0,
                "of_venda": 169840.0,
                "spread_pts": 5.0,
                "voc": 3500.0,
                "vov": 1300.0,
                "delta_voc": 900.0,
                "delta_vov": -150.0,
                "delta_negocios": 55
            },
            # Zona de Defesa no Fundo [169750 - 169850]
            "zone": (169750.0, 169850.0),
            "l_inf": 169750.0,
            "l_sup": 169850.0,
            "v_c": 5400.0,
            "v_v": 1700.0,
            "delta_P_afastamento": 90.0,  # 169840 - 169750 = 90 pts de afastamento da borda inferior
            # Pullback OB 15m/10m ativo
            "pullback_zone": {
                "type": "OB",
                "timeframe": 15,
                "top": 169850.0,
                "bottom": 169750.0,
                "ce_50": 169800.0,
                "direction": "BULLISH"
            },
            # Times & Trades: Delta -18.500 vendido absorvido com deslocamento de +40 pts
            "flow_metrics": {
                "buy_volume": 8500,
                "sell_volume": 27000,
                "delta": -18500,
                "price_displacement_pts": +40.0,
                "trades_count": 520,
                "absorcao_detectada": True,
                "flow_pattern": "Absorção compradora no fundo: delta vendedor de -18.500 absorvido",
                "large_trades": [
                    {"qty": 450, "price": 169800.0, "side": "BUY"},
                    {"qty": 380, "price": 169810.0, "side": "BUY"},
                    {"qty": 300, "price": 169825.0, "side": "BUY"}
                ]
            },
            "p_medio_reacao": p_medio_reacao
        }

        setup = SignalSetup(
            timestamp=now,
            setup_name="Compra por Pullback em Order Block 15m com Absorção Institucional no Fundo",
            direction=Direction.COMPRA,
            symbol=symbol,
            status=SetupStatus.CONFIRMADO,
            entry_price=169840.0,
            stop_price=169590.0,
            stop_points=250.0,
            target_price=170240.0,
            target_points=400.0,
            risk_reward=1.60,
            timeframe_trigger=15,
            in_trend_direction=True,
            structure_event="Reteste do Order Block de 15m com absorção massiva das vendas a mercado",
            obstacles=["PASSAGEM LIVRE: Nenhum obstáculo até o alvo em 170.240 (+400 pontos)"],
            facts_observed=[
                "Preço: 169.840 (acima da Média Aritmética de Reação T&T: 169.800)",
                "Times & Trades: DELTA=-18.500 contratos vendedores absorvidos passivamente",
                "Deslocamento do preço: +40 pontos confirmando exaustão vendedora",
                "OrderBook: VOC 3.500 ct vs VOV 1.300 ct (Escora compradora 2.7x)"
            ],
            interpretations=[
                "Confluência plena de alta no fundo com absorção do fluxo vendedor.",
                "Execução autorizada no SuperDOM na coluna azul (Alvo 400 pts / Stop 250 pts)."
            ],
            limitations=["Oscilação padrão de mercado"],
            invalidation_criteria="Perda de 169.590 com candle fechado"
        )

        regimes = {"240m": "ALTA", "60m": "ALTA", "15m": "ALTA", "5m": "ALTA", "1m": "ALTA"}

        verdict = self.harness.evaluate_market_confluence(
            side="COMPRA",
            context=context,
            setup_name=setup.setup_name,
            entry_price=setup.entry_price,
            use_color=True
        )

        alert_text = format_operational_alert(
            setup=setup,
            regimes=regimes,
            source_name="Nelogica ProfitPro (DDE)",
            delay_ms=0.3,
            quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
            flow_data=context["flow_metrics"],
            symbol_override=f"{symbol} (Mini-Índice B3)",
            use_color=True,
            harness_verdict=verdict,
            p_medio_reacao=verdict.p_medio_reacao
        )

        print("\n" + "=" * 80)
        print(Fore.GREEN + Style.BRIGHT + ">>> CENÁRIO 2/5: COMPRA EM FUNDO / PULLBACK OB COM ABSORÇÃO E ESCORA COMPRADORA <<<" + Style.RESET_ALL)
        print("=" * 80)
        print(alert_text)
        print("=" * 80 + "\n")

        # Validações Estruturais do Cenário 2
        self.assertGreaterEqual(verdict.score_final, 75.0, f"Score esperado >= 75.0, obtido: {verdict.score_final}")
        self.assertEqual(verdict.classification, "FAVORÁVEL (CONFLUÊNCIA ALTA)")
        self.assertEqual(verdict.agent_verdicts["ExtremesTapeAgent"].status_tag, "REACAO_FORTE_DEFESA")
        self.assertEqual(verdict.agent_verdicts["OrderBookAgent"].status_tag, "ESCORA_PASSIVA")
        self.assertEqual(verdict.agent_verdicts["MacroRatesAgent"].bias, "COMPRA")
        self.assertEqual(verdict.agent_verdicts["BlueChipsFlowAgent"].bias, "COMPRA")
        self.assertEqual(verdict.agent_verdicts["GlobalIndexAgent"].bias, "COMPRA")
        self.assertGreater(self._get_log_tail_count(), initial_log_count)

    # =========================================================================
    # CENÁRIO 3: Movimento ESTICADO — Anti-Falso Positivo
    # =========================================================================
    def test_cenario_3_movimento_esticado_anti_falso_positivo(self):
        """
        Cenário 3:
        - Sinal de Compra após perna esticada na máxima sem retração a FVG/OB (15m/10m/5m)
        - PullbackValueZoneAgent marca 0/100 [ESTICADO]
        - Rebaixa o veredito sem bloquear o alerta demo (Modo Demo não bloqueante)
        """
        now = datetime.now(TZ_BRASILIA)
        symbol = get_current_win_contract()
        initial_log_count = self._get_log_tail_count()

        current_p = 172400.0

        context = {
            "current_price": current_p,
            "ultimo": current_p,
            # Regra Anti-Esticado ativada: distância para suporte institucional > 80 pts sem teste
            "is_stretched": True,
            "distancia_suporte_pts": 220.0,
            "pullback_zone": None,
            "win_book": {
                "of_compra": 172395.0,
                "of_venda": 172400.0,
                "spread_pts": 5.0,
                "voc": 1400.0,
                "vov": 1500.0,
                "delta_voc": 50.0,
                "delta_vov": 50.0,
                "delta_negocios": 20
            },
            "flow_metrics": {
                "buy_volume": 6000,
                "sell_volume": 4000,
                "delta": +2000,
                "trades_count": 180,
                "price_displacement_pts": +15.0
            }
        }

        setup = SignalSetup(
            timestamp=now,
            setup_name="Compra de Rompimento na Máxima (Breakout Esticado)",
            direction=Direction.COMPRA,
            symbol=symbol,
            status=SetupStatus.CONFIRMADO,
            entry_price=172400.0,
            stop_price=172150.0,
            stop_points=250.0,
            target_price=172800.0,
            target_points=400.0,
            risk_reward=1.60,
            timeframe_trigger=1,
            in_trend_direction=True,
            structure_event="Rompimento de máxima sem retração MTF",
            obstacles=["Nenhum obstáculo técnico intermediário mapeado"],
            facts_observed=[
                "Preço: 172.400 na máxima da sessão",
                "Afastamento de 220 pontos do suporte institucional mais próximo",
                "Sem confluência de retração em FVG ou Order Block nos tempos 5m/10m/15m"
            ],
            interpretations=[
                "Sinal original emitido pelo algoritmo canônico (Modo Demo Ativo).",
                "Harness quantifica risco de compra no topo esticado sem censurar o alerta."
            ],
            limitations=["Risco severo de correção e falso rompimento"],
            invalidation_criteria="Perda de 172.150"
        )

        regimes = {"60m": "ALTA", "15m": "ALTA", "5m": "ALTA", "1m": "ALTA"}

        verdict = self.harness.evaluate_market_confluence(
            side="COMPRA",
            context=context,
            setup_name=setup.setup_name,
            entry_price=setup.entry_price,
            use_color=True
        )

        alert_text = format_operational_alert(
            setup=setup,
            regimes=regimes,
            source_name="Nelogica ProfitPro (DDE)",
            delay_ms=0.5,
            quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
            flow_data=context["flow_metrics"],
            symbol_override=f"{symbol} (Mini-Índice B3)",
            use_color=True,
            harness_verdict=verdict,
            p_medio_reacao=verdict.p_medio_reacao
        )

        print("\n" + "=" * 80)
        print(Fore.YELLOW + Style.BRIGHT + ">>> CENÁRIO 3/5: MOVIMENTO ESTICADO (ANTI-FALSO POSITIVO) <<<" + Style.RESET_ALL)
        print("=" * 80)
        print(alert_text)
        print("=" * 80 + "\n")

        # Validações Estruturais do Cenário 3
        pullback_verdict = verdict.agent_verdicts["PullbackValueZoneAgent"]
        self.assertEqual(pullback_verdict.score, 0.0, f"PullbackValueZoneAgent deve marcar 0.0 para esticado, obteve {pullback_verdict.score}")
        self.assertEqual(pullback_verdict.status_tag, "ESTICADO")
        self.assertIn("ESTICADO", verdict.panel_text)
        # Modo Demo não bloqueia o sinal (alerta é emitido com status CONFIRMADO mantido)
        self.assertEqual(setup.status, SetupStatus.CONFIRMADO)
        self.assertIn("MODO DEMO ATIVO", verdict.panel_text)
        self.assertGreater(self._get_log_tail_count(), initial_log_count)

    # =========================================================================
    # CENÁRIO 4: Zona de Violação [165.250 - 165.350] com Agressão de Compra VENCIDA
    # =========================================================================
    def test_cenario_4_zona_violacao_compra_vencida(self):
        """
        Cenário 4:
        - Zona de Violação [165.250 - 165.350] com W = 100 pts
        - Após toque do candle, V_C = 1.420 ct é vencida por V_V = 3.180 ct
        - Preço perde 165.250 (165.230)
        - Validação de COMPRA_VENCIDA e cálculo de P_defesa
        """
        now = datetime.now(TZ_BRASILIA)
        symbol = get_current_win_contract()
        initial_log_count = self._get_log_tail_count()

        current_p = 165230.0  # Perdeu 165.250 (P < L_inf)

        context = {
            "current_price": current_p,
            "ultimo": current_p,
            "zone": (165250.0, 165350.0),
            "l_inf": 165250.0,
            "l_sup": 165350.0,
            "v_c": 1420.0,
            "v_v": 3180.0,
            "delta_P_afastamento": -20.0,
            "win_book": {
                "of_compra": 165225.0,
                "of_venda": 165230.0,
                "spread_pts": 5.0,
                "voc": 900.0,
                "vov": 2400.0,
                "delta_voc": -300.0,
                "delta_vov": 500.0,
                "delta_negocios": 35
            },
            "flow_metrics": {
                "buy_volume": 1420,
                "sell_volume": 3180,
                "delta": -1760,
                "trades_count": 210,
                "price_displacement_pts": -70.0
            }
        }

        setup = SignalSetup(
            timestamp=now,
            setup_name="Teste de Suporte em [165.250 - 165.350] com Agressão Vencida",
            direction=Direction.COMPRA,
            symbol=symbol,
            status=SetupStatus.CONFIRMADO,
            entry_price=165230.0,
            stop_price=164980.0,
            stop_points=250.0,
            target_price=165630.0,
            target_points=400.0,
            risk_reward=1.60,
            timeframe_trigger=5,
            in_trend_direction=False,
            structure_event="Perda de suporte na zona [165.250 - 165.350]",
            obstacles=["Suporte rompido transformando-se em resistência imediata"],
            facts_observed=[
                "Preço: 165.230 perdeu a borda inferior de 165.250",
                "Agressão compradora na zona: V_C = 1.420 contratos",
                "Agressão vendedora na zona: V_V = 3.180 contratos (Domínio de 69.1% das vendas)",
                "Compradores absorvidos e vencidos na tentativa de sustentar o nível"
            ],
            interpretations=[
                "COMPRA_VENCIDA: Suporte violado e defesa compradora em colapso.",
                "Harness sinaliza viés de VENDA devido ao rompimento."
            ],
            limitations=["Falso rompimento se recuperar 165.350"],
            invalidation_criteria="Recuperação imediata acima de 165.350"
        )

        regimes = {"60m": "BAIXA", "15m": "BAIXA", "5m": "BAIXA", "1m": "BAIXA"}

        verdict = self.harness.evaluate_market_confluence(
            side="COMPRA",
            context=context,
            setup_name=setup.setup_name,
            entry_price=setup.entry_price,
            use_color=True
        )

        alert_text = format_operational_alert(
            setup=setup,
            regimes=regimes,
            source_name="Nelogica ProfitPro (DDE)",
            delay_ms=0.6,
            quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
            flow_data=context["flow_metrics"],
            symbol_override=f"{symbol} (Mini-Índice B3)",
            use_color=True,
            harness_verdict=verdict,
            p_medio_reacao=verdict.p_medio_reacao
        )

        print("\n" + "=" * 80)
        print(Fore.RED + Style.BRIGHT + ">>> CENÁRIO 4/5: ZONA DE VIOLAÇÃO COM AGRESSÃO DE COMPRA VENCIDA <<<" + Style.RESET_ALL)
        print("=" * 80)
        print(alert_text)
        print("=" * 80 + "\n")

        # Validações Estruturais do Cenário 4
        zone_verdict = verdict.agent_verdicts["ZoneViolationDefenseAgent"]
        self.assertEqual(zone_verdict.status_tag, "COMPRA_VENCIDA", f"Esperado COMPRA_VENCIDA, obtido {zone_verdict.status_tag}")
        self.assertEqual(zone_verdict.bias, "VENDA", f"Esperado viés VENDA após compra vencida, obtido {zone_verdict.bias}")
        self.assertLess(verdict.p_defesa, 50.0, f"P_defesa esperado em colapso (< 50%), obtido: {verdict.p_defesa}%")
        self.assertIn("COMPRA_VENCIDA", verdict.panel_text)
        self.assertGreater(self._get_log_tail_count(), initial_log_count)

    # =========================================================================
    # CENÁRIO 5: Blefe / Liquidity Pulling no Book de Ofertas
    # =========================================================================
    def test_cenario_5_blefe_liquidity_pulling(self):
        """
        Cenário 5:
        - Sinal de Compra em suporte onde VOC cai 55% entre snapshots sem execução proporcional de negócios
        - OrderBookAgent detecta BLEFE_PULLING
        - Score do Book penalizado (< 40) e emissão de alerta de cautela
        """
        now = datetime.now(TZ_BRASILIA)
        symbol = get_current_win_contract()
        initial_log_count = self._get_log_tail_count()

        current_p = 170000.0

        # VOC caiu 55%: voc_anterior = 2000.0, voc = 900.0, delta_voc = -1100.0
        # delta_negocios = 15 (muito menor que delta_voc * 0.35 = 385), comprovando retirada sem negócio
        context = {
            "current_price": current_p,
            "ultimo": current_p,
            "win_book": {
                "of_compra": 169995.0,
                "of_venda": 170000.0,
                "spread_pts": 5.0,
                "voc": 900.0,
                "vov": 1800.0,
                "delta_voc": -1100.0,
                "delta_vov": 100.0,
                "delta_negocios": 15
            },
            "flow_metrics": {
                "buy_volume": 3200,
                "sell_volume": 4100,
                "delta": -900,
                "trades_count": 140,
                "price_displacement_pts": -10.0
            }
        }

        setup = SignalSetup(
            timestamp=now,
            setup_name="Compra em Suporte Nominal com Liquidez Retirada",
            direction=Direction.COMPRA,
            symbol=symbol,
            status=SetupStatus.CONFIRMADO,
            entry_price=170000.0,
            stop_price=169750.0,
            stop_points=250.0,
            target_price=170400.0,
            target_points=400.0,
            risk_reward=1.60,
            timeframe_trigger=5,
            in_trend_direction=True,
            structure_event="Teste de suporte psicológico 170.000",
            obstacles=["Nenhum obstáculo mapeado"],
            facts_observed=[
                "Preço: 170.000 em suporte psicológico",
                "OrderBook: VOC desabou de 2.000 para 900 contratos (-55.0%)",
                "Apenas 15 negócios executados no período (Retirada artificial de ofertas)",
                "Book vendedora dominando com 1.800 contratos"
            ],
            interpretations=[
                "Cancelamento brusco de ofertas compradora compatível com blefe (Pulling).",
                "Harness penaliza o score e alerta cautela operacional."
            ],
            limitations=["Potencial aceleração vendedora se romper o suporte"],
            invalidation_criteria="Perda de 169.750"
        )

        regimes = {"60m": "ALTA", "15m": "CONSOLIDAÇÃO", "5m": "ALTA", "1m": "CONSOLIDAÇÃO"}

        verdict = self.harness.evaluate_market_confluence(
            side="COMPRA",
            context=context,
            setup_name=setup.setup_name,
            entry_price=setup.entry_price,
            use_color=True
        )

        alert_text = format_operational_alert(
            setup=setup,
            regimes=regimes,
            source_name="Nelogica ProfitPro (DDE)",
            delay_ms=0.3,
            quality_status="ÍNTEGRO (FLUXO + ESTRUTURA)",
            flow_data=context["flow_metrics"],
            symbol_override=f"{symbol} (Mini-Índice B3)",
            use_color=True,
            harness_verdict=verdict,
            p_medio_reacao=verdict.p_medio_reacao
        )

        print("\n" + "=" * 80)
        print(Fore.MAGENTA + Style.BRIGHT + ">>> CENÁRIO 5/5: BLEFE / LIQUIDITY PULLING NO BOOK DE OFERTAS <<<" + Style.RESET_ALL)
        print("=" * 80)
        print(alert_text)
        print("=" * 80 + "\n")

        # Validações Estruturais do Cenário 5
        book_verdict = verdict.agent_verdicts["OrderBookAgent"]
        self.assertEqual(book_verdict.status_tag, "BLEFE_PULLING", f"Esperado BLEFE_PULLING, obtido {book_verdict.status_tag}")
        self.assertLess(book_verdict.score, 40.0, f"Score de blefe esperado < 40, obtido: {book_verdict.score}")
        self.assertEqual(book_verdict.bias, "VENDA", f"Bias de blefe na compra deve ser VENDA, obtido: {book_verdict.bias}")
        self.assertIn("BLEFE_PULLING", verdict.panel_text)
        self.assertGreater(self._get_log_tail_count(), initial_log_count)


if __name__ == "__main__":
    unittest.main()
