"""
core/engine.py
Orquestrador central do Assistente de Análise do Mini-Índice WIN — Profit Pro.
Coordena a coleta, validação, agregação dos 7 tempos, Tape Reading, Book e geração de alertas.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
import time

from core.models import Candle, Trade, BookSnapshot, SignalSetup
from core.contract import get_current_win_contract, resolve_symbol, get_asset_spec, TZ_BRASILIA
from core.candle_aggregator import MultiTimeframeCandleAggregator
from analysis.market_structure import MultiTimeframeMarketEngine
from analysis.tape_reading import TapeReadingAnalyzer
from analysis.book_analyzer import BookAnalyzer
from setups.setup_engine import SetupEngine
from analysis.alert_formatter import format_operational_alert
from analysis.fvg_mtf_scanner import FGVMTFScanner
from feeds.base_feed import BaseMarketFeed, FeedHealth


class WinAnalysisAssistant:
    """
    Motor principal do assistente.
    Opera independentemente da conversa e mantém o estado determinístico de mercado.
    Suporta Mini-Índice (WIN), Mini-Dólar (WDO) e Ações (VALE3).
    """

    def __init__(self, feed: BaseMarketFeed, symbol: Optional[str] = None, mode: str = "FIXO"):
        self.symbol = resolve_symbol(symbol)
        self.spec = get_asset_spec(self.symbol)
        self.feed = feed
        self.mode = mode.upper()
        
        # Componentes analíticos calibrados para o ativo
        self.structure_engine = MultiTimeframeMarketEngine(asset_spec=self.spec)
        self.flow_analyzer = TapeReadingAnalyzer(window_seconds=300, asset_spec=self.spec)
        self.book_analyzer = BookAnalyzer(depth_levels=10)
        self.setup_engine = SetupEngine(mode=self.mode, asset_spec=self.spec)
        self.fvg_scanner = FGVMTFScanner(
            min_fvg_size=self.spec.min_fvg_size,
            default_approach_radius=getattr(self.spec, 'approach_radius', 150.0),
            asset_spec=self.spec,
            auto_load=True
        )
        
        # Agregador de candles
        self.aggregator = MultiTimeframeCandleAggregator(
            on_candle_closed=self._handle_candle_closed
        )
        
        # Configurar callbacks do feed
        self.feed.set_callbacks(
            on_candle=self._handle_raw_candle,
            on_trade=self._handle_raw_trade,
            on_book=self._handle_raw_book
        )
        
        if self.spec.symbol_base == "WIN":
            self.last_price = 171400.0
        elif self.spec.symbol_base == "WDO":
            self.last_price = 5470.0
        elif self.spec.symbol_base == "VALE3":
            self.last_price = 62.0
        else:
            self.last_price = 100.0
        self.last_alert: str = "Aguardando inicialização do feed..."
        self.alerted_entry_key: Optional[str] = None

    def start(self) -> bool:
        """Inicia a conexão e a subscrição do ativo."""
        ok = self.feed.connect()
        if ok:
            self.feed.subscribe_symbol(self.symbol)
        return ok

    def stop(self):
        """Encerra com segurança o feed."""
        self.feed.disconnect()

    def _handle_raw_candle(self, c: Candle):
        """Recebe candle de 1m fechado da fonte e distribui pelo agregador."""
        self.last_price = c.close
        self.aggregator.process_1m_candle(c)
        self.fvg_scanner.register_price_tick(c.close)

    def _handle_candle_closed(self, c: Candle):
        """Recebe qualquer candle fechado dos 7 tempos gráficos."""
        self.structure_engine.process_closed_candle(c)
        self.fvg_scanner.register_candle(c)
        self.fvg_scanner.sync_from_engine(self.structure_engine)

    def _handle_raw_trade(self, t: Trade):
        self.last_price = t.price
        self.flow_analyzer.add_trade(t)
        self.fvg_scanner.register_price_tick(t.price)

    def _handle_raw_book(self, snap: BookSnapshot):
        self.book_analyzer.update_snapshot(snap)

    def evaluate_now(self) -> str:
        """
        Executa a avaliação determinística instantânea e retorna o alerta formatado.
        """
        health = self.feed.get_health()
        now = datetime.now(TZ_BRASILIA)

        sym_label = f"{self.symbol} ({self.spec.name})"
        if not health.is_healthy:
            regimes = self.structure_engine.get_regime_summary()
            alert = format_operational_alert(
                setup=None,
                regimes=regimes,
                source_name=health.source_name,
                delay_ms=health.latency_ms,
                quality_status="DEGRADADO / DESCONECTADO",
                general_status_override="ANÁLISE BLOQUEADA — DADOS INSUFICIENTES OU DESATUALIZADOS",
                symbol_override=sym_label
            )
            self.last_alert = alert
            return alert

        # Sincronizar último preço em tempo real direto da fonte (DDE/Tick)
        if hasattr(self.feed, 'last_price') and self.feed.last_price > 0:
            self.last_price = self.feed.last_price

        # Inicializar contexto estrutural com os extremos da sessão (ABE, MAX, MIN)
        if hasattr(self.feed, 'last_high') and hasattr(self.feed, 'last_low') and hasattr(self.feed, 'last_open'):
            if self.feed.last_high > self.feed.last_low and self.feed.last_low > 0:
                self.structure_engine.seed_session_extremes(
                    self.feed.last_open, self.feed.last_high, self.feed.last_low, now
                )

        # Avaliar setups
        setup, reason = self.setup_engine.evaluate(
            symbol=self.symbol,
            current_price=self.last_price,
            timestamp=now,
            structure_engine=self.structure_engine,
            flow_analyzer=self.flow_analyzer,
            book_analyzer=self.book_analyzer,
            feed_healthy=True
        )

        regimes = self.structure_engine.get_regime_summary()
        quality_str = "SEM CONFIRMAÇÃO DE FLUXO" if not health.is_flow_available else "ÍNTEGRO (FLUXO + ESTRUTURA)"
        flow_summary = self.flow_analyzer.get_window_metrics(seconds=300)
        
        # Rastrear aproximação de FVGs antigos não liquidados nos tempos MTF (10m, 15m, 30m, 60m, 240m)
        fvg_radar_banner = None
        rad = getattr(self.spec, 'approach_radius', 150.0)
        fvg_alerts = self.fvg_scanner.scan_approach_alerts(self.last_price, approach_radius=rad)
        if fvg_alerts:
            fvg_radar_banner = self.fvg_scanner.format_power_shell_alert(fvg_alerts[0], use_color=True)

        if setup is not None:
            # Mapear obstáculos institucionais vs passagem livre no caminho do alvo
            setup.obstacles = self.fvg_scanner.check_target_obstacles(
                direction=setup.direction,
                entry_price=setup.entry_price,
                target_price=setup.target_price
            )

            # FILTRO CENÁRIO 3: Bloquear operação caso haja obstáculo institucional contrário no caminho do alvo
            # (Exceto se for setup de reversão estruturado como CHoCH, Sweep de liquidez ou Defesa Institucional)
            has_fvg_obstacle = any("[ALERTA] OBSTÁCULO INSTITUCIONAL" in obs for obs in setup.obstacles)
            s_name = setup.setup_name.lower()
            is_reversal = any(kw in s_name for kw in ["choch", "sweep", "defesa institucional", "absorção", "falso rompimento"])
            if has_fvg_obstacle and not is_reversal:
                setup.status = SetupStatus.BLOQUEADO

        alert = format_operational_alert(
            setup=setup,
            regimes=regimes,
            source_name=health.source_name,
            delay_ms=health.latency_ms,
            quality_status=quality_str,
            general_status_override="SEM OPERAÇÃO — AGUARDAR" if setup is None else None,
            flow_data=flow_summary,
            symbol_override=sym_label,
            fvg_radar_banner=fvg_radar_banner
        )
        self.last_alert = alert

        # Gravar para persistência e compartilhamento imediato
        try:
            import os
            data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
            os.makedirs(data_dir, exist_ok=True)
            with open(os.path.join(data_dir, "latest_alert.txt"), "w", encoding="utf-8") as f:
                f.write(alert)
            sym_clean = self.spec.symbol_base.lower()
            with open(os.path.join(data_dir, f"latest_alert_{sym_clean}.txt"), "w", encoding="utf-8") as f:
                f.write(alert)
            if setup is not None:
                # Tocar a sequência de 5 apitos APENAS se o setup estiver CONFIRMADO (bloqueados pelo Radar FVG não apitam)
                if setup.status == SetupStatus.CONFIRMADO:
                    entry_key = f"{setup.direction.value}_{setup.entry_price:.2f}_{setup.setup_name}_{setup.stop_price:.2f}_{setup.target_price:.2f}"
                    if self.alerted_entry_key != entry_key:
                        self.alerted_entry_key = entry_key
                        self._trigger_audio_beep_sequence(setup.direction.value)
                else:
                    self.alerted_entry_key = None

                with open(os.path.join(data_dir, "live_alerts.log"), "a", encoding="utf-8") as f:
                    f.write(f"\n[{now.strftime('%d/%m/%Y %H:%M:%S')}] SETUP DISPARADO:\n{alert}\n")
                with open(os.path.join(data_dir, f"live_alerts_{sym_clean}.log"), "a", encoding="utf-8") as f:
                    f.write(f"\n[{now.strftime('%d/%m/%Y %H:%M:%S')}] SETUP DISPARADO:\n{alert}\n")
            else:
                # Mercado em SEM OPERAÇÃO — AGUARDAR: limpa a trava para que o próximo setup toque os 5 apitos
                self.alerted_entry_key = None
        except Exception:
            pass

        return alert

    def _trigger_audio_beep_sequence(self, direction_str: str):
        """
        Emite exatamente uma sequência de 5 apitos rápidos em thread assíncrona
        quando uma nova entrada é gerada.
        Toca os 5 apitos e NÃO repete enquanto a mesma entrada permanecer na tela.
        """
        import threading
        def _play():
            import time
            try:
                import winsound
                freq = 1300 if direction_str == "COMPRA" else 950
                for _ in range(5):
                    try:
                        winsound.Beep(freq, 85)
                    except Exception:
                        try:
                            winsound.MessageBeep(winsound.MB_OK)
                        except Exception:
                            pass
                    time.sleep(0.08)
            except Exception:
                pass

        threading.Thread(target=_play, daemon=True).start()
