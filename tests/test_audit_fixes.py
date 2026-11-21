"""
tests/test_audit_fixes.py
Testes unitários automatizados para validar as correções de auditoria:
1. Ciclo de vida estrito de FVG (sem mitigação na formação, mitigação no reteste, invalidação no rompimento).
2. Modelo ICT Unicorn com FVG íntegro e mitigação de Breaker.
3. Tape Reading calibrado para o Mini-Dólar (WDO) e Ações (VALE3).
4. Rotação automática de arquivos de log e deduplicação de alertas.
"""

import unittest
import sys
import os
from datetime import datetime, timedelta

# Garantir importações locais
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.models import Candle, Trade, AggressorSide, Direction, SetupStatus
from core.contract import WIN_SPEC, WDO_SPEC, VALE3_SPEC, TZ_BRASILIA
from analysis.market_structure import TimeframeStructureAnalyzer
from analysis.tape_reading import TapeReadingAnalyzer
from analysis.smc_advanced import ICTUnicornEngine, BreakerBlock
from core.engine import WinAnalysisAssistant


class TestAuditFixes(unittest.TestCase):

    def setUp(self):
        self.base_time = datetime(2026, 11, 13, 9, 0, 0, tzinfo=TZ_BRASILIA)

    def test_fvg_proper_lifecycle(self):
        """Valida que o FVG não é mitigado na barra de formação, é mitigado no reteste e invalidado no rompimento."""
        analyzer = TimeframeStructureAnalyzer(timeframe=5, min_fvg_size=10.0)
        
        # c1, c2, c3 formam Bullish FVG [110.0 - 120.0]
        c1 = Candle(5, self.base_time, self.base_time + timedelta(minutes=5), 100, 110, 95, 105, is_closed=True)
        c2 = Candle(5, self.base_time + timedelta(minutes=5), self.base_time + timedelta(minutes=10), 105, 130, 105, 128, is_closed=True)
        c3 = Candle(5, self.base_time + timedelta(minutes=10), self.base_time + timedelta(minutes=15), 128, 140, 120, 135, is_closed=True)
        
        analyzer.add_candle(c1)
        analyzer.add_candle(c2)
        analyzer.add_candle(c3)
        
        self.assertEqual(len(analyzer.fvgs), 1)
        fvg = analyzer.fvgs[0]
        self.assertEqual(fvg.direction, "BULLISH")
        self.assertEqual(fvg.bottom, 110.0)
        self.assertEqual(fvg.top, 120.0)
        
        # 1. Na barra de formação, o FVG NÃO PODE estar mitigado nem invalidado
        self.assertFalse(fvg.is_mitigated, "FVG não pode nascer mitigado na barra de formação!")
        self.assertFalse(fvg.is_invalidated, "FVG não pode nascer invalidado!")
        
        # 2. Barra 4 penetra na zona (mínima 115 <= 120), mas fecha acima (125) -> Mitigado com sucesso
        c4 = Candle(5, self.base_time + timedelta(minutes=15), self.base_time + timedelta(minutes=20), 135, 136, 115, 125, is_closed=True)
        analyzer.add_candle(c4)
        self.assertTrue(fvg.is_mitigated, "FVG deve ser marcado como mitigado após penetração de preço posterior!")
        self.assertFalse(fvg.is_invalidated)
        
        # 3. Barra 5 fecha abaixo da base do FVG (fechamento 100 < 110) -> Invalidado com sucesso
        c5 = Candle(5, self.base_time + timedelta(minutes=20), self.base_time + timedelta(minutes=25), 125, 126, 95, 100, is_closed=True)
        analyzer.add_candle(c5)
        self.assertTrue(fvg.is_invalidated, "FVG deve ser marcado como invalidado após fechamento abaixo do bottom!")

    def test_wdo_flow_pattern_calibration(self):
        """Valida que os limiares de Tape Reading do Mini-Dólar (WDO) usam passos em pontos de dólar e não índice."""
        tr = TapeReadingAnalyzer(window_seconds=300, asset_spec=WDO_SPEC)
        self.assertEqual(tr.large_trade_thresh, 30, "Limiar de grandes ordens no WDO deve ser 30 contratos")
        
        # 1. Continuidade Compradora no WDO: Delta positivo e avanço >= 3.0 pts
        pat_cont = tr._classify_flow_pattern(delta=150, price_displacement=3.5, total_volume=400)
        self.assertIn("Continuidade Compradora", pat_cont)
        
        # 2. Continuidade Vendedora no WDO: Delta negativo e recuo <= -3.0 pts
        pat_cont_v = tr._classify_flow_pattern(delta=-150, price_displacement=-3.5, total_volume=400)
        self.assertIn("Continuidade Vendedora", pat_cont_v)
        
        # 3. Absorção Vendedora no WDO: Forte compra (delta +150) sem deslocamento (<= 1.0 pt)
        pat_abs_v = tr._classify_flow_pattern(delta=150, price_displacement=0.5, total_volume=400)
        self.assertIn("Possível Absorção Vendedora", pat_abs_v)
        
        # 4. Absorção Compradora no WDO: Forte venda (delta -150) sem deslocamento (>= -1.0 pt)
        pat_abs_c = tr._classify_flow_pattern(delta=-150, price_displacement=-0.5, total_volume=400)
        self.assertIn("Possível Absorção Compradora", pat_abs_c)

    def test_breaker_block_mitigation(self):
        """Valida que o Breaker Block é mitigado quando o preço rompe sua estrutura."""
        engine = ICTUnicornEngine(min_overlap_ratio=0.30, asset_spec=WIN_SPEC)
        
        # Cria um Bullish Breaker (suporte entre 100 e 110)
        bb = BreakerBlock(
            breaker_type="BULLISH",
            top=110.0,
            bottom=100.0,
            origin_candle_index=0,
            sweep_level=90.0,
            breakout_level=110.0,
            timestamp=self.base_time,
            timeframe=5
        )
        engine.breakers.append(bb)
        self.assertFalse(bb.is_mitigated)
        
        # Candle posterior fecha abaixo de 100 -> deve mitigar o breaker
        c_break = Candle(5, self.base_time + timedelta(minutes=5), self.base_time + timedelta(minutes=10), 105, 105, 90, 95, is_closed=True)
        engine.detect_breakers(candles=[c_break], pivots=[], timeframe=5)
        self.assertTrue(bb.is_mitigated, "Bullish Breaker deve ser mitigado quando candle fecha abaixo da base!")

    def test_log_rotation_mechanism(self):
        """Valida que a rotação de log cria arquivos .1 e limita o tamanho físico."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_log = os.path.join(tmp_dir, "test_alerts.log")
            
            # Gravar conteúdo pequeno (~600 bytes) com max_bytes de 1000 bytes
            small_chunk = "A" * 600 + "\n"
            WinAnalysisAssistant._append_with_rotation(test_log, small_chunk, max_bytes=1000, backup_count=2)
            self.assertTrue(os.path.exists(test_log))
            initial_size = os.path.getsize(test_log)
            self.assertTrue(initial_size >= 600)
            
            # Gravar segundo chunk excedendo o limite de 1000 bytes
            WinAnalysisAssistant._append_with_rotation(test_log, small_chunk, max_bytes=1000, backup_count=2)
            # O arquivo original deve ter rotacionado para test_alerts.log.1
            self.assertTrue(os.path.exists(f"{test_log}.1"), "Arquivo de backup rotacionado deve existir!")
            self.assertEqual(os.path.getsize(test_log), initial_size, "Arquivo principal deve conter apenas o novo registro!")


if __name__ == "__main__":
    unittest.main()
