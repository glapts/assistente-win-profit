from core.engine import WinAnalysisAssistant
from feeds.dde_feed import ProfitDDEFeed
import time

feed = ProfitDDEFeed()
assistant = WinAnalysisAssistant(feed=feed, symbol="WINZ26", mode="FIXO")
assistant.start()

print("Aguardando 2 segundos para o DDE processar...")
time.sleep(2.0)

alert = assistant.evaluate_now()
print("\n" + alert)

assistant.stop()
