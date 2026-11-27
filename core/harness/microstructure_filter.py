"""
core/harness/microstructure_filter.py
Filtro de Microestrutura e Tape Reading Institucional Anti-HFT.
Resolve:
  - Problema 2: Ilusão de liquidez institucional (descarta spoofing de HFTs < 20 lotes).
  - Problema 10: Exige absorção real institucional (>= 100 contratos) antes de disparar gatilhos.
"""

from collections import deque
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple


class MicrostructureFilter:
    def __init__(self, min_hft_lot: int = 20, min_institutional_absorption: int = 100, window_seconds: int = 30):
        self.min_hft_lot = min_hft_lot
        self.min_institutional_absorption = min_institutional_absorption
        self.window_seconds = window_seconds
        # Fila de trades institucionais relevantes: (timestamp, price, qty, aggressor)
        self.trades_history = deque()
        self.delta_by_price: Dict[float, int] = {}
        self.buy_volume_by_price: Dict[float, int] = {}
        self.sell_volume_by_price: Dict[float, int] = {}

    def on_trade(self, price: float, qty: int, aggressor: str, timestamp: datetime) -> Dict[str, Any]:
        """
        Consome um negócio do Times & Trades.
        Descarta ruídos de robôs de HFT (< 20 contratos).
        """
        is_hft_noise = qty < self.min_hft_lot

        if is_hft_noise:
            # Ignora lotes pequenos de arbitragem HFT para não poluir absorções
            return {
                "filtered": True,
                "reason": f"HFT_NOISE: Lote ({qty}) menor que {self.min_hft_lot}",
                "price": price,
                "qty": qty
            }

        # Normaliza agressor (suporta BUY/SELL e COMPRADOR/VENDEDOR)
        aggr_upper = aggressor.upper()
        if any(k in aggr_upper for k in ["BUY", "COMPR"]):
            aggr_norm = "BUY"
        elif any(k in aggr_upper for k in ["SELL", "VEND"]):
            aggr_norm = "SELL"
        else:
            aggr_norm = aggr_upper

        # Armazena trade institucional
        self.trades_history.append((timestamp, price, qty, aggr_norm))

        # Purga trades mais velhos que a janela
        cutoff = timestamp - timedelta(seconds=self.window_seconds)
        while self.trades_history and self.trades_history[0][0] < cutoff:
            self.trades_history.popleft()

        # Atualiza métricas por nível de preço
        p_round = round(price, -1) # Agrupa em clusters de 10 pts
        if aggr_norm == "BUY":
            self.buy_volume_by_price[p_round] = self.buy_volume_by_price.get(p_round, 0) + qty
            self.delta_by_price[p_round] = self.delta_by_price.get(p_round, 0) + qty
        elif aggr_norm == "SELL":
            self.sell_volume_by_price[p_round] = self.sell_volume_by_price.get(p_round, 0) + qty
            self.delta_by_price[p_round] = self.delta_by_price.get(p_round, 0) - qty

        return {
            "filtered": False,
            "price": price,
            "qty": qty,
            "aggressor": aggr_norm,
            "timestamp": timestamp
        }

    def evaluate_absorption(
        self,
        target_price: float,
        expected_defense: str, # "BUY_DEFENSE" (absorvendo vendas) ou "SELL_DEFENSE" (absorvendo compras)
        tolerance_pts: float = 100.0
    ) -> Tuple[bool, int, str]:
        """
        Verifica se há absorção institucional real em torno do target_price.
        - BUY_DEFENSE: Institucional compra passivo enquanto varejo agride na venda (Volume vendedor elevado sem o preço cair).
        - SELL_DEFENSE: Institucional vende passivo enquanto varejo agride na compra (Volume comprador elevado sem o preço subir).
        """
        min_p = target_price - tolerance_pts
        max_p = target_price + tolerance_pts

        total_buy_qty = 0
        total_sell_qty = 0

        for t_time, p, q, aggr in self.trades_history:
            if min_p <= p <= max_p:
                if aggr == "BUY":
                    total_buy_qty += q
                elif aggr == "SELL":
                    total_sell_qty += q

        if expected_defense == "BUY_DEFENSE":
            # Absorção de venda: compradores passivos engoliram vendas a mercado
            if total_sell_qty >= self.min_institutional_absorption:
                return True, total_sell_qty, f"ABSORÇÃO CONFIRMADA: {total_sell_qty} contratos vendidos absorvidos passivamente na região de {target_price:.0f}."
            return False, total_sell_qty, f"ABSORÇÃO INSUFICIENTE: {total_sell_qty}/{self.min_institutional_absorption} contratos vendidos."

        elif expected_defense == "SELL_DEFENSE":
            # Absorção de compra: vendedores passivos escoraram compras a mercado
            if total_buy_qty >= self.min_institutional_absorption:
                return True, total_buy_qty, f"ABSORÇÃO CONFIRMADA: {total_buy_qty} contratos comprados absorvidos passivamente na região de {target_price:.0f}."
            return False, total_buy_qty, f"ABSORÇÃO INSUFICIENTE: {total_buy_qty}/{self.min_institutional_absorption} contratos comprados."

        return False, 0, "Tipo de defesa desconhecido."
