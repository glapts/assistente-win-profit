"""
ui/dashboard.py
Painel interativo e visualizador em terminal dos 7 tempos gráficos, Tape Reading e Book L2.
"""

import os
import sys
import time
from datetime import datetime

from core.engine import WinAnalysisAssistant
from feeds.base_feed import BaseMarketFeed
from feeds.replay_feed import ReplayMarketFeed
from feeds.dde_feed import ProfitDDEFeed
from core.contract import calculate_financial_risk


def run_dashboard(assistant: WinAnalysisAssistant, update_interval: float = 2.0):
    """Executa o loop interativo do dashboard no terminal."""
    try:
        spec_name = getattr(assistant, 'spec', None)
        title_name = assistant.spec.name if spec_name else "Mini-Índice WIN"
        print(f"\nIniciando Assistente de Análise — {assistant.symbol} ({title_name})...\n")
        assistant.start()
        
        while True:
            # Avaliar mercado e formatar alerta
            alert_text = assistant.evaluate_now()
            
            # Limpar console (opcional, para terminal limpo)
            # os.system('cls' if os.name == 'nt' else 'clear')
            print("\n" + alert_text + "\n")
            
            # Pausa configurável
            time.sleep(update_interval)
            
    except KeyboardInterrupt:
        print("\nEncerrando o assistente com segurança...")
        assistant.stop()
        print("Finalizado.")
