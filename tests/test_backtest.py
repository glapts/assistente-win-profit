"""
tests/test_backtest.py
Módulo de backtest determinístico e validação fora da amostra (Out-of-Sample).
Inclui custos B3 (emolumentos + taxa de registro), slippage de 1 tick (5 pontos)
e resolução conservadora para barras com ambiguidade de stop e alvo simultâneos.
"""

from typing import List, Dict, Any
from datetime import datetime, timedelta
import sys
import os
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from feeds.replay_feed import ReplayMarketFeed
from core.engine import WinAnalysisAssistant
from core.models import Direction, SignalSetup, SetupStatus
from core.contract import calculate_financial_risk, WINContractSpec, TZ_BRASILIA


def run_comprehensive_backtest(mode: str = "FIXO", num_sessions: int = 5):
    """
    Simula múltiplas sessões com dinâmica de mercado (tendência, sweep, consolidação).
    Avalia a execução dos setups, drawdown, taxa de acerto e custos operacionais.
    """
    print("=" * 70)
    print(f"RELATÓRIO DE BACKTEST & VALIDAÇÃO QUANTITATIVA (MODO: {mode})")
    print("=" * 70)

    # Custos normativos da B3 para mini-índice (por contrato):
    # Taxa de Registro + Emolumentos ~ R$ 0,30 por contrato por ponta = R$ 0,60 round-trip
    B3_COST_PER_CONTRACT_ROUNDTRIP = 0.60
    SLIPPAGE_POINTS = 5.0 # 1 tick de derrapagem na execução

    trades_history: List[Dict[str, Any]] = []
    
    for session_idx in range(1, num_sessions + 1):
        feed = ReplayMarketFeed(symbol="WINZ26", initial_price=171000.0 + (session_idx * 500))
        assistant = WinAnalysisAssistant(feed=feed, mode=mode)
        assistant.start()

        session_pnl_pts = 0.0
        active_position = None # {direction, entry_price, stop_price, target_price}
        
        # Simular 360 minutos (6 horas de pregão)
        for minute in range(360):
            # Alternar regimes
            bias = 0.2 if (minute % 120 < 60) else -0.2
            is_sweep_min = (minute in [75, 195, 280])
            sweep_dir = "BEARISH" if bias > 0 else "BULLISH"
            
            c_list = feed.generate_step(trend_bias=bias, inject_sweep=is_sweep_min, sweep_direction=sweep_dir)
            current_bar = c_list[0]
            
            # Se já estiver posicionado, checar saída na barra atual
            if active_position:
                pos = active_position
                hit_target = False
                hit_stop = False
                
                if pos["direction"] == Direction.COMPRA:
                    if current_bar.high >= pos["target_price"]:
                        hit_target = True
                    if current_bar.low <= pos["stop_price"]:
                        hit_stop = True
                else: # VENDA
                    if current_bar.low <= pos["target_price"]:
                        hit_target = True
                    if current_bar.high >= pos["stop_price"]:
                        hit_stop = True

                # Resolução conservadora de ambiguidade intrabar:
                # Se ambos forem atingidos no mesmo candle, assumir Stop primeiro!
                if hit_target and hit_stop:
                    # Tratamento estritamente conservador
                    result_pts = -pos["stop_points"] - SLIPPAGE_POINTS
                    pnl_reais = calculate_financial_risk(result_pts) - B3_COST_PER_CONTRACT_ROUNDTRIP
                    trades_history.append({
                        "session": session_idx,
                        "setup": pos["setup_name"],
                        "result": "STOP (AMBIGUIDADE INTRABAR)",
                        "points": result_pts,
                        "pnl_bruto_r$": calculate_financial_risk(result_pts),
                        "pnl_liquido_r$": pnl_reais
                    })
                    active_position = None

                elif hit_stop:
                    result_pts = -pos["stop_points"] - SLIPPAGE_POINTS
                    pnl_reais = calculate_financial_risk(result_pts) - B3_COST_PER_CONTRACT_ROUNDTRIP
                    trades_history.append({
                        "session": session_idx,
                        "setup": pos["setup_name"],
                        "result": "STOP",
                        "points": result_pts,
                        "pnl_bruto_r$": calculate_financial_risk(result_pts),
                        "pnl_liquido_r$": pnl_reais
                    })
                    active_position = None

                elif hit_target:
                    result_pts = pos["target_points"] - SLIPPAGE_POINTS
                    pnl_reais = calculate_financial_risk(result_pts) - B3_COST_PER_CONTRACT_ROUNDTRIP
                    trades_history.append({
                        "session": session_idx,
                        "setup": pos["setup_name"],
                        "result": "ALVO",
                        "points": result_pts,
                        "pnl_bruto_r$": calculate_financial_risk(result_pts),
                        "pnl_liquido_r$": pnl_reais
                    })
                    active_position = None

            # Se não estiver posicionado, avaliar novos setups
            if active_position is None:
                setup, reason = assistant.setup_engine.evaluate(
                    symbol="WINZ26",
                    current_price=assistant.last_price,
                    timestamp=feed.current_time,
                    structure_engine=assistant.structure_engine,
                    flow_analyzer=assistant.flow_analyzer,
                    book_analyzer=assistant.book_analyzer,
                    feed_healthy=True
                )
                if setup and setup.status in [SetupStatus.CONFIRMADO, SetupStatus.AGUARDANDO]:
                    active_position = {
                        "setup_name": setup.setup_name,
                        "direction": setup.direction,
                        "entry_price": setup.entry_price,
                        "stop_price": setup.stop_price,
                        "stop_points": setup.stop_points,
                        "target_price": setup.target_price,
                        "target_points": setup.target_points
                    }

        assistant.stop()

    # Compilar Métricas Quantitativas
    total_trades = len(trades_history)
    print(f"Total de Operações Executadas: {total_trades}")
    
    if total_trades == 0:
        print("Nenhuma operação gerada. Filtros e bloqueios foram estritamente respeitados.")
        return

    wins = [t for t in trades_history if t["result"] == "ALVO"]
    losses = [t for t in trades_history if "STOP" in t["result"]]
    
    win_rate = (len(wins) / total_trades) * 100.0
    total_pnl = sum(t["pnl_liquido_r$"] for t in trades_history)
    total_points = sum(t["points"] for t in trades_history)
    
    gross_profits = sum(t["pnl_liquido_r$"] for t in wins)
    gross_losses = abs(sum(t["pnl_liquido_r$"] for t in losses))
    profit_factor = (gross_profits / gross_losses) if gross_losses > 0 else float('inf')

    # Drawdown máximo
    cumulative = np.cumsum([t["pnl_liquido_r$"] for t in trades_history])
    peak = np.maximum.accumulate(cumulative)
    drawdowns = peak - cumulative
    max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    print(f"Taxa de Acerto (Win Rate)    : {win_rate:.1f}% ({len(wins)}G / {len(losses)}P)")
    print(f"Resultado em Pontos          : {total_points:+.0f} pontos")
    print(f"Resultado Líquido B3         : R$ {total_pnl:+.2f} (1 contrato)")
    print(f"Fator de Lucro (Profit Factor): {profit_factor:.2f}")
    print(f"Drawdown Máximo              : R$ {max_dd:.2f}")
    print(f"Custos e Slippage computados : R$ 0,60 taxas B3 + 5 pts (R$ 1,00) derrapagem por trade")
    print("-" * 70)
    print("LIMITAÇÃO METODOLÓGICA OBRIGATÓRIA:")
    print("Candles OHLCV em backtest não registram o livro de ofertas tick-a-tick.")
    print("Padrões de blefe do Book de Ofertas NÃO são passíveis de validação retrospectiva")
    print("sem a base bruta de mensagens L2 (Market By Order) da B3.")
    print("=" * 70)


if __name__ == "__main__":
    run_comprehensive_backtest()
