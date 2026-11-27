"""
tests/test_scalper_glaucio.py
========================================================================================
Suíte de testes unitários do módulo ScalperGlaucio (SMC 1-Minuto WIN B3).
Valida numeração de candles, gaps a partir de 5 pts, 50% CE, iFVG e filtros de tendência.
========================================================================================
"""

import unittest
from datetime import datetime, date

from core.smc.scalper_glaucio import ScalperGlaucio, ScalperSignal, FVGZone


class TestScalperGlaucio(unittest.TestCase):

    def setUp(self):
        self.scalper = ScalperGlaucio(
            min_gap_pts=5.0,
            target_pts=100.0,
            stop_pts=150.0,
            filter_trend=True,
            beep_on_signal=False
        )

    def test_candle_numbering_and_bullish_fvg_small_gap(self):
        """Valida se a numeração incrementa como no Profit e detecta gap de 10 pts."""
        # Candle 1 (09:00)
        sig1 = self.scalper.on_candle_closed(
            timestamp=datetime(2026, 11, 23, 9, 0),
            open_price=166000.0, high_price=166050.0, low_price=165980.0, close_price=166040.0
        )
        self.assertEqual(self.scalper.candle_counter, 1)
        self.assertEqual(len(sig1), 0)

        # Candle 2 (09:01) - Deslocamento forte
        sig2 = self.scalper.on_candle_closed(
            timestamp=datetime(2026, 11, 23, 9, 1),
            open_price=166040.0, high_price=166150.0, low_price=166030.0, close_price=166140.0
        )
        self.assertEqual(self.scalper.candle_counter, 2)
        self.assertEqual(len(sig2), 0)

        # Candle 3 (09:02) - Mínima fica acima da Máxima do Candle 1 (166.060 > 166.050 = Gap 10 pts)
        sig3 = self.scalper.on_candle_closed(
            timestamp=datetime(2026, 11, 23, 9, 2),
            open_price=166140.0, high_price=166200.0, low_price=166060.0, close_price=166190.0
        )
        self.assertEqual(self.scalper.candle_counter, 3)
        self.assertEqual(len(sig3), 1)

        s = sig3[0]
        self.assertEqual(s.signal_type, "FVG_DIRECT")
        self.assertEqual(s.direction, "LONG")
        self.assertEqual(s.candle_ids, [1, 2, 3])
        self.assertEqual(s.trigger_candle_id, 4)
        self.assertEqual(s.gap_size, 10.0) # 166060 - 166050 = 10 pts
        self.assertEqual(s.ce_50, 166055.0) # (166060 + 166050) / 2 = 166055
        self.assertEqual(s.target_price, 166155.0) # +100 pts
        self.assertEqual(s.stop_price, 165905.0)   # -150 pts

    def test_minimum_gap_threshold_5_pts(self):
        """Valida que um gap de exatamente 5 pontos (1 tick) é aceito."""
        # C1 High = 166000
        self.scalper.on_candle_closed(
            datetime(2026, 11, 23, 9, 0), 165950.0, 166000.0, 165940.0, 165990.0
        )
        # C2
        self.scalper.on_candle_closed(
            datetime(2026, 11, 23, 9, 1), 165990.0, 166080.0, 165980.0, 166070.0
        )
        # C3 Low = 166005 (Gap = 5 pts)
        sigs = self.scalper.on_candle_closed(
            datetime(2026, 11, 23, 9, 2), 166070.0, 166100.0, 166005.0, 166090.0
        )
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].gap_size, 5.0)
        self.assertEqual(sigs[0].ce_50, 166000.0) # Arredondado para tick favorável de 5 pts

    def test_bearish_fvg_in_downtrend(self):
        """Valida formação de FVG de venda quando tendência é de baixa."""
        # Abertura em 167000
        self.scalper.on_candle_closed(
            datetime(2026, 11, 23, 9, 0), 167000.0, 167010.0, 166850.0, 166860.0
        )
        # C2 Queda forte
        self.scalper.on_candle_closed(
            datetime(2026, 11, 23, 9, 1), 166860.0, 166870.0, 166700.0, 166710.0
        )
        # C3 Máxima = 166840 < C1 Mínima 166850 (Gap de 10 pts)
        sigs = self.scalper.on_candle_closed(
            datetime(2026, 11, 23, 9, 2), 166710.0, 166840.0, 166680.0, 166690.0
        )
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s.direction, "SHORT")
        self.assertEqual(s.ce_50, 166845.0) # (166850 + 166840) / 2 = 166845
        self.assertEqual(s.target_price, 166745.0) # -100 pts
        self.assertEqual(s.stop_price, 166995.0)   # +150 pts

    def test_inversion_to_ifvg(self):
        """Valida que quando um FVG é rompido por fechamento, inverte para iFVG."""
        # 1. Forma Bullish FVG (Gap 166000 a 166020, CE 166010)
        self.scalper.on_candle_closed(datetime(2026, 11, 23, 9, 0), 165950, 166000, 165940, 165990)
        self.scalper.on_candle_closed(datetime(2026, 11, 23, 9, 1), 165990, 166080, 165980, 166070)
        self.scalper.on_candle_closed(datetime(2026, 11, 23, 9, 2), 166070, 166100, 166020, 166090)

        # Desativa filtro de tendência momentâneo para testar a inversão puramente mecânica
        self.scalper.filter_trend = False

        # Candle 4 rompe e fecha abaixo de 166000 (Close = 165950) -> Promove para iFVG de VENDA
        sigs_inv = self.scalper.on_candle_closed(
            datetime(2026, 11, 23, 9, 3), 166090, 166090, 165940, 165950
        )
        self.assertEqual(len(sigs_inv), 1)
        s_inv = sigs_inv[0]
        self.assertEqual(s_inv.signal_type, "IFVG_INVERTED")
        self.assertEqual(s_inv.direction, "SHORT")
        self.assertEqual(s_inv.ce_50, 166010.0)

    def test_session_reset_on_new_date(self):
        """Valida que ao mudar de dia o contador de candles reseta determinísticamente para 1."""
        self.scalper.on_candle_closed(datetime(2026, 11, 23, 9, 0), 166000, 166050, 165980, 166020)
        self.assertEqual(self.scalper.candle_counter, 1)

        # Próximo dia
        self.scalper.on_candle_closed(datetime(2026, 11, 24, 9, 0), 167000, 167050, 166980, 167020)
        self.assertEqual(self.scalper.candle_counter, 1)
        self.assertEqual(self.scalper.current_date, date(2026, 11, 24))

    def test_deterministic_indexing_midday_restart(self):
        """Valida que reiniciando o script ao meio-dia (ex: 10:45 com abertura 09:03) o índice é exatamente 103."""
        from datetime import time as dt_time
        scalper_midday = ScalperGlaucio(
            min_gap_pts=5.0,
            market_open_time=dt_time(9, 3)
        )
        # Primeiro candle recebido após restart às 10:45
        scalper_midday.on_candle_closed(
            datetime(2026, 11, 23, 10, 45), 183000, 183100, 182900, 183050
        )
        # (10 * 60 + 45) - (9 * 60 + 3) + 1 = 645 - 543 + 1 = 103
        self.assertEqual(scalper_midday.candle_counter, 103)

    def test_double_notation_in_signals(self):
        """Valida se o sinal contém a notação dupla com horários e números absolutos de barras."""
        scalper = ScalperGlaucio(min_gap_pts=5.0, filter_trend=False)
        scalper.on_candle_closed(datetime(2026, 11, 23, 9, 3), 180000, 180050, 179980, 180020)
        scalper.on_candle_closed(datetime(2026, 11, 23, 9, 4), 180020, 180150, 180010, 180140)
        sigs = scalper.on_candle_closed(datetime(2026, 11, 23, 9, 5), 180140, 180200, 180060, 180190)

        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual(s.candle_ids, [1, 2, 3])
        self.assertEqual(s.trigger_candle_id, 4)
        self.assertEqual(s.candle_times, ["09:03", "09:04", "09:05"])
        self.assertEqual(s.trigger_candle_time, "09:06")
        self.assertIn("Candles [09:03, 09:04 e 09:05] (Barras #1, #2 e #3)", s.description)


if __name__ == "__main__":
    unittest.main()
