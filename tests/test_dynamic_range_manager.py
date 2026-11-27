"""
tests/test_dynamic_range_manager.py
Suíte de Testes Unitários Oficiais do DynamicRangeManager (SMC / WIN B3).

Cobre:
  1. Sweep de 1 candle (rejeição imediata de topo -> Não expande).
  2. Rompimento anêmico de 2 candles (Dojis com avanço < 300 pts -> Rejeitado).
  3. Estrela cadente no Candle 2 (Upthrust Trap com pavio superior > 30% -> Rejeitado).
  4. BOS válido em 2 candles M5 de Alta (Aceito -> Recálculo atômico do Dealing Range).
  5. BOS válido em 2 candles M5 de Baixa (Aceito -> Recálculo atômico do Dealing Range).
  6. Preservação de Zonas em STANDBY_DEEP_PULLBACK e Injeção das 3 Novas Zonas (S/R Flip, FVG, Exaustão).
  7. Promoção de Order Block / FVG Intermediário a BREAKER BLOCK (inversão de polaridade).
  8. Trava de Janelas Operacionais (Blackout 09h-10h e 11h28-11h33 bloqueando expansão).
  9. Escrita Atômica e Hot-Reload (integridade de arquivo via os.replace).
"""

import os
import json
import unittest
import tempfile
import shutil
from datetime import datetime, timedelta, time

from core.models import Candle
from core.harness.contracts import (
    DealingRange,
    FVGZone,
    Niveis60mContract,
    ZoneType,
    ZoneStatus,
    PrimarySetup
)
from core.smc.dynamic_range_manager import (
    DynamicRangeManager,
    DynamicRangeState,
    M5CandleBuilder
)


class TestDynamicRangeManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.niveis_file = os.path.join(self.test_dir, "niveis_60m_test.json")
        self.base_time = datetime(2026, 11, 26, 11, 40, 0) # Janela válida pós-NY

        # Dealing Range inicial: 170.000 (Fundo) a 174.000 (Topo), Eq: 172.000
        self.initial_dr = DealingRange(
            topo_estrutural=174000.0,
            fundo_estrutural=170000.0,
            equilibrium_50=172000.0
        )

        # Zonas iniciais
        self.zone_deep = FVGZone(
            id="ZONA_01_FUNDO_170500",
            tipo_original=ZoneType.BULLISH,
            top=170550.0,
            ce_50=170500.0,
            bottom=170450.0,
            setup_primario=PrimarySetup.CONTINUATION_BUY,
            stop_sugerido_pts=250.0,
            alvo_sugerido_pts=400.0,
            status=ZoneStatus.UNMITIGATED
        )
        self.zone_intermediate_resistance = FVGZone(
            id="ZONA_02_RESISTENCIA_OB_172500",
            tipo_original=ZoneType.BEARISH,
            top=172550.0,
            ce_50=172500.0,
            bottom=172450.0,
            setup_primario=PrimarySetup.CONTINUATION_SELL,
            stop_sugerido_pts=250.0,
            alvo_sugerido_pts=400.0,
            status=ZoneStatus.UNMITIGATED
        )
        self.zone_top = FVGZone(
            id="ZONA_03_TOPO_173950",
            tipo_original=ZoneType.BEARISH,
            top=174000.0,
            ce_50=173950.0,
            bottom=173900.0,
            setup_primario=PrimarySetup.CONTINUATION_SELL,
            stop_sugerido_pts=250.0,
            alvo_sugerido_pts=400.0,
            status=ZoneStatus.UNMITIGATED
        )

        self.initial_contract = Niveis60mContract(
            versao_contrato="2.0",
            ativo="WINZ26",
            data_referencia="2026-11-26",
            dealing_range=self.initial_dr,
            zonas_fvg=[self.zone_deep, self.zone_intermediate_resistance, self.zone_top]
        )

        with open(self.niveis_file, "w", encoding="utf-8") as f:
            json.dump(self.initial_contract.model_dump(), f, indent=2, default=str)

        self.manager = DynamicRangeManager(
            niveis_path=self.niveis_file,
            clearance_threshold=300.0,
            enforce_time_windows=True,
            enforce_delta_filter=True
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_sweep_one_candle_rejected(self):
        """1. Sweep de 1 candle: rompe o topo com pavio mas fecha dentro do range -> NÃO expande."""
        t0 = self.base_time
        # Candle 1 fura até 174150 mas fecha em 173900 (dentro do range)
        c1 = Candle(5, t0, t0 + timedelta(minutes=5), 173800.0, 174150.0, 173750.0, 173900.0, is_closed=True)
        # Candle 2 volta para 173700
        c2 = Candle(5, t0 + timedelta(minutes=5), t0 + timedelta(minutes=10), 173900.0, 173950.0, 173650.0, 173700.0, is_closed=True)

        res = self.manager.check_expansion_trigger(c1, c2, t0 + timedelta(minutes=10), delta_15m=3500.0)
        self.assertIsNone(res, "Sweep de 1 candle com fechamento interno NÃO deve disparar expansão.")
        self.assertEqual(self.manager.state, DynamicRangeState.RANGE_ORIGINAL)

    def test_anemic_breakout_rejected_by_clearance(self):
        """2. Rompimento anêmico (Dojis): fecham acima mas com avanço < 300 pts -> Rejeitado."""
        t0 = self.base_time
        # Topo é 174000. Candle 1 fecha em 174030, Candle 2 fecha em 174060 (avanço max 174080 - 174000 = 80 pts < 300 pts)
        c1 = Candle(5, t0, t0 + timedelta(minutes=5), 173980.0, 174050.0, 173950.0, 174030.0, is_closed=True)
        c2 = Candle(5, t0 + timedelta(minutes=5), t0 + timedelta(minutes=10), 174030.0, 174080.0, 174010.0, 174060.0, is_closed=True)

        res = self.manager.check_expansion_trigger(c1, c2, t0 + timedelta(minutes=10), delta_15m=4000.0)
        self.assertIsNone(res, "Rompimento anêmico sem clearance de 300 pts deve ser rejeitado.")

    def test_shooting_star_upthrust_trap_rejected(self):
        """3. Estrela cadente no Candle 2 (Upthrust Trap com pavio > 30%) -> Rejeitado."""
        t0 = self.base_time
        # Candle 1 rompe forte
        c1 = Candle(5, t0, t0 + timedelta(minutes=5), 173900.0, 174350.0, 173850.0, 174300.0, is_closed=True)
        # Candle 2 abre em 174300, vai até 174600, mas sofre avalanche e fecha em 174050
        # Range = 174600 - 174000 = 600 pts. Pavio superior = 174600 - 174300 = 300 pts (50% do range > 30%!)
        c2 = Candle(5, t0 + timedelta(minutes=5), t0 + timedelta(minutes=10), 174300.0, 174600.0, 174000.0, 174050.0, is_closed=True)

        res = self.manager.check_expansion_trigger(c1, c2, t0 + timedelta(minutes=10), delta_15m=4000.0)
        self.assertIsNone(res, "Upthrust Trap com pavio superior de 50% deve ser rejeitado.")

    def test_valid_bullish_bos_and_dealing_range_recalculation(self):
        """4. BOS Válido de Alta (2x M5 + Continuidade + Clearance) -> Dealing Range recalculado."""
        t0 = self.base_time
        # Candle 1 fecha em 174250
        c1 = Candle(5, t0, t0 + timedelta(minutes=5), 173900.0, 174300.0, 173850.0, 174250.0, is_closed=True)
        # Candle 2 faz nova máxima (174550), fecha em 174500 no topo sem pavio de rejeição (avanço 550 pts >= 300 pts)
        c2 = Candle(5, t0 + timedelta(minutes=5), t0 + timedelta(minutes=10), 174250.0, 174550.0, 174200.0, 174500.0, is_closed=True)

        event = self.manager.on_candle_closed(c1, delta_15m=3500.0)
        self.assertIsNone(event, "Apenas 1 candle fechado não deve acionar expansão.")

        event = self.manager.on_candle_closed(c2, delta_15m=3500.0)
        self.assertIsNotNone(event, "2x M5 com continuidade deve aprovar a expansão.")
        self.assertEqual(event.event_type, "BULLISH_EXPANSION")
        self.assertEqual(self.manager.state, DynamicRangeState.EXPANSION_ACTIVE)

        # Valida a nova geometria
        new_dr = event.new_dealing_range
        self.assertEqual(new_dr.topo_estrutural, 174550.0) # Nova máxima
        self.assertEqual(new_dr.fundo_estrutural, 174000.0) # S/R Flip do antigo topo
        expected_eq = round((174550.0 + 174000.0) / 2.0, 2) # 174275.0
        self.assertEqual(new_dr.equilibrium_50, expected_eq)

        # Valida gravação atômica em disco
        with open(self.niveis_file, "r", encoding="utf-8") as f:
            saved_data = json.load(f)
        self.assertEqual(saved_data["dealing_range"]["topo_estrutural"], 174550.0)
        self.assertEqual(saved_data["dealing_range"]["fundo_estrutural"], 174000.0)

        # Valida Zonas em STANDBY_DEEP_PULLBACK
        standby_zones = [z for z in saved_data["zonas_fvg"] if z["status"] == "STANDBY_DEEP_PULLBACK"]
        self.assertTrue(len(standby_zones) >= 1, "Zonas antigas abaixo do novo fundo devem ficar em STANDBY.")

        # Valida as 3 novas zonas injetadas
        injected = [z for z in saved_data["zonas_fvg"] if "SR_FLIP" in z["id"] or "EXPANSAO" in z["id"] or "EXAUSTAO" in z["id"]]
        self.assertEqual(len(injected), 3, "Devem ser injetadas exatamente 3 novas zonas na pernada de expansão.")
        for z in injected:
            self.assertEqual(z["stop_sugerido_pts"], 250.0, "Stop padrão deve ser rigorosamente 250 pts.")
            self.assertEqual(z["alvo_sugerido_pts"], 400.0, "Alvo padrão deve ser rigorosamente 400 pts.")

    def test_valid_bearish_bos_and_dealing_range_recalculation(self):
        """5. BOS Válido de Baixa (2x M5 rompendo fundo estrutural de 170000) -> Expansão de Baixa."""
        t0 = self.base_time
        # Candle 1 rompe fundo (170000) e fecha em 169750
        c1 = Candle(5, t0, t0 + timedelta(minutes=5), 170100.0, 170150.0, 169700.0, 169750.0, is_closed=True)
        # Candle 2 renova mínima (169450), fecha na mínima em 169470 (avanço 550 pts >= 300 pts)
        c2 = Candle(5, t0 + timedelta(minutes=5), t0 + timedelta(minutes=10), 169750.0, 169800.0, 169450.0, 169470.0, is_closed=True)

        self.manager.on_candle_closed(c1, delta_15m=-3500.0)
        event = self.manager.on_candle_closed(c2, delta_15m=-3500.0)

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "BEARISH_EXPANSION")
        new_dr = event.new_dealing_range
        self.assertEqual(new_dr.fundo_estrutural, 169450.0) # Nova mínima
        self.assertEqual(new_dr.topo_estrutural, 170000.0) # S/R Flip do antigo fundo
        self.assertEqual(new_dr.equilibrium_50, round((170000.0 + 169450.0) / 2.0, 2))

    def test_breaker_block_promotion(self):
        """6. Promoção de Order Block / FVG Intermediário a BREAKER BLOCK."""
        t0 = self.base_time
        # ZONA_02_RESISTENCIA_OB_172500 tem top em 172550
        # Candle 1 fecha acima em 172650
        c1 = Candle(5, t0, t0 + timedelta(minutes=5), 172400.0, 172700.0, 172350.0, 172650.0, is_closed=True)
        # Candle 2 renova máxima e fecha com continuidade em 172900 (High: 172950)
        c2 = Candle(5, t0 + timedelta(minutes=5), t0 + timedelta(minutes=10), 172650.0, 172950.0, 172600.0, 172900.0, is_closed=True)

        self.manager.candles_m5 = [c1]
        promoted = self.manager.evaluate_breaker_promotion(c1, c2)
        self.assertEqual(len(promoted), 1)
        z = promoted[0]
        self.assertEqual(z.id, "ZONA_02_RESISTENCIA_OB_172500")
        self.assertEqual(z.tipo_original, ZoneType.BREAKER)
        self.assertEqual(z.setup_primario, PrimarySetup.INVERSION_BUY)
        self.assertIn("BREAKER BLOCK", z.notes)

    def test_time_window_blackout_blocks_expansion(self):
        """7. Bloqueio de Horário: Rompimento durante 09h00-10h00 ou 11h28-11h33 é vetado."""
        t_leilao_b3 = datetime(2026, 11, 26, 9, 30, 0)
        c1 = Candle(5, t_leilao_b3, t_leilao_b3 + timedelta(minutes=5), 173900.0, 174500.0, 173850.0, 174450.0, is_closed=True)
        c2 = Candle(5, t_leilao_b3 + timedelta(minutes=5), t_leilao_b3 + timedelta(minutes=10), 174450.0, 174800.0, 174400.0, 174750.0, is_closed=True)

        res = self.manager.check_expansion_trigger(c1, c2, t_leilao_b3 + timedelta(minutes=10), delta_15m=4000.0)
        self.assertIsNone(res, "Blackout da B3 (09:00 - 10:00) deve vetar expansão de range.")

        t_leilao_ny = datetime(2026, 11, 26, 11, 30, 0)
        res_ny = self.manager.check_expansion_trigger(c1, c2, t_leilao_ny, delta_15m=4000.0)
        self.assertIsNone(res_ny, "Blackout de NY (11:28 - 11:33) deve vetar expansão de range.")

    def test_m5_candle_builder_aggregation(self):
        """8. Agregador M5CandleBuilder agrupa ticks e fecha na fronteira de 5 minutos (:00, :05, :10)."""
        builder = M5CandleBuilder()
        t0 = datetime(2026, 11, 26, 10, 0, 15)
        self.assertIsNone(builder.update_tick(174000.0, t0))
        self.assertIsNone(builder.update_tick(174100.0, t0 + timedelta(minutes=2)))
        self.assertIsNone(builder.update_tick(173950.0, t0 + timedelta(minutes=4)))

        # Cruza para 10:05:01
        closed = builder.update_tick(174050.0, t0 + timedelta(minutes=5, seconds=1))
        self.assertIsNotNone(closed)
        self.assertTrue(closed.is_closed)
        self.assertEqual(closed.open, 174000.0)
        self.assertEqual(closed.high, 174100.0)
        self.assertEqual(closed.low, 173950.0)
        self.assertEqual(closed.close, 173950.0)


if __name__ == "__main__":
    unittest.main()
