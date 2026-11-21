"""
core/engine.py
Orquestrador central do Assistente de Análise do Mini-Índice WIN — Profit Pro.
Coordena a coleta, validação, agregação dos 7 tempos, Tape Reading, Book e geração de alertas.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
import time

from core.models import Candle, Trade, BookSnapshot, SignalSetup, SetupStatus, Direction
from core.contract import get_current_win_contract, resolve_symbol, get_asset_spec, TZ_BRASILIA
from core.candle_aggregator import MultiTimeframeCandleAggregator
from analysis.market_structure import MultiTimeframeMarketEngine
from analysis.tape_reading import TapeReadingAnalyzer
from analysis.book_analyzer import BookAnalyzer
from setups.setup_engine import SetupEngine
from analysis.alert_formatter import format_operational_alert
from analysis.fvg_mtf_scanner import FGVMTFScanner
from analysis.sp500_macro_filter import SP500MacroFilter
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
        self.sp500_filter = SP500MacroFilter()
        
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
            if hasattr(self.feed, 'set_sp500_callback'):
                self.feed.set_sp500_callback(self._handle_sp500_tick)
            if hasattr(self.feed, 'set_sp500_symbol'):
                self.feed.set_sp500_symbol(self.sp500_filter.active_symbol)
            self.feed.subscribe_symbol(self.symbol)
        return ok

    def _handle_sp500_tick(self, price: float, timestamp: datetime, symbol: str = ""):
        """Recebe ticks do S&P 500 transmitidos em tempo real pelo feed DDE."""
        self.sp500_filter.register_tick(price, timestamp, symbol)

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
            feed_healthy=True,
            sp500_filter=self.sp500_filter
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

            # Informações detalhadas dos obstáculos no caminho do alvo (Melhorias A, B e C)
            all_obstacles = self.fvg_scanner.get_target_obstacles_info(
                direction=setup.direction,
                entry_price=setup.entry_price,
                target_price=setup.target_price
            )
            closest_obs = self.fvg_scanner.get_closest_obstacle_info(
                direction=setup.direction,
                entry_price=setup.entry_price,
                target_price=setup.target_price
            )

            # Identificar se há obstáculo institucional e se é setup de reversão
            has_fvg_obstacle = bool(all_obstacles) or any("[ALERTA] OBSTÁCULO INSTITUCIONAL" in obs for obs in setup.obstacles)
            s_name = setup.setup_name.lower()
            is_reversal = any(kw in s_name for kw in ["choch", "sweep", "defesa institucional", "absorção", "falso rompimento"])

            if has_fvg_obstacle and not is_reversal:
                # Melhoria C: Hierarquia MTF - Verificar se há obstáculo Macro (60m ou 240m/4h)
                has_macro_obstacle = any(obs.get('is_macro', False) for obs in all_obstacles) or any(
                    ("[ALERTA] OBSTÁCULO INSTITUCIONAL" in obs and ("60m" in obs or "240m" in obs or "4h" in obs))
                    for obs in setup.obstacles
                )

                # Melhoria A: Avaliação de Flow Override institucional
                flow_300 = flow_summary if flow_summary else {}
                delta_val = flow_300.get("delta", 0)
                disp_val = flow_300.get("price_displacement_pts", 0.0)
                flow_pattern = str(flow_300.get("flow_pattern", "")).upper()

                sym_base = getattr(self.spec, 'symbol_base', 'WIN').upper()

                # Calibração determinística por classe de ativo (Opção 2 - Sweet Spot SMC com Teto de Segurança)
                if sym_base == "WIN":
                    delta_thresh = 3000
                    disp_min = 50.0
                    disp_max = 180.0
                elif sym_base == "WDO":
                    delta_thresh = 400
                    disp_min = 4.0
                    disp_max = 18.0
                else:  # Ações / Outros (ex: VALE3)
                    delta_thresh = 3000
                    disp_min = 0.10
                    disp_max = 0.50

                is_dir_buy = (setup.direction == Direction.COMPRA)
                is_dir_sell = (setup.direction == Direction.VENDA)

                # Condições de rompimento de barreira por fluxo (sem absorção contrária)
                flow_override_valid = False
                is_overextended = False

                if is_dir_buy:
                    if delta_val >= delta_thresh:
                        if disp_val > disp_max:
                            is_overextended = True
                        elif disp_min <= disp_val <= disp_max:
                            # Não pode haver agressão de compra sendo absorvida por venda passiva
                            if "ABSORÇÃO VENDEDORA" not in flow_pattern:
                                flow_override_valid = True
                elif is_dir_sell:
                    if delta_val <= -delta_thresh:
                        if disp_val < -disp_max:
                            is_overextended = True
                        elif -disp_max <= disp_val <= -disp_min:
                            # Não pode haver agressão de venda sendo absorvida por compra passiva
                            if "ABSORÇÃO COMPRADORA" not in flow_pattern:
                                flow_override_valid = True

                if has_macro_obstacle:
                    # Melhoria C: Obstáculos Macro (60m e 240m) sempre mantêm bloqueio estrito
                    setup.status = SetupStatus.BLOQUEADO
                    setup.interpretations.append(
                        "⛔ BLOQUEIO MACRO FVG: Zona institucional de 60m/240m mantém bloqueio estrito para evitar armadilhas de swing."
                    )
                elif is_overextended:
                    # Veto SMC: Movimento esticado em Zona Premium / Discount (risco de comprar topo ou vender fundo)
                    setup.status = SetupStatus.BLOQUEADO
                    zone_label = "PREMIUM (Topo Esticado)" if is_dir_buy else "DISCOUNT (Fundo Esticado)"
                    disp_fmt = f"{disp_val:+.0f}" if sym_base == "WIN" else f"{disp_val:+.2f}"
                    unit_lbl = "pts" if sym_base in ("WIN", "WDO") else "reais"
                    setup.interpretations.append(
                        f"⚠️ VETO SMC [ZONA {zone_label}]: Deslocamento excessivo ({disp_fmt} {unit_lbl} > {disp_max:.0f} {unit_lbl}). "
                        f"Risco de comprar topo ou vender fundo esticado. Aguardar pullback técnico."
                    )
                elif flow_override_valid:
                    # Melhoria A: Fluxo institucional massivo no Sweet Spot supera a barreira intraday (Inversion FVG)
                    setup.status = SetupStatus.CONFIRMADO
                    disp_fmt = f"{disp_val:+.0f}" if sym_base == "WIN" else (f"{disp_val:+.1f}" if sym_base == "WDO" else f"{disp_val:+.2f}")
                    unit_lbl = "pts" if sym_base in ("WIN", "WDO") else "reais"
                    setup.interpretations.append(
                        f"⚡ FLOW OVERRIDE ATIVO: Delta institucional ({delta_val:+d}) e deslocamento ({disp_fmt} {unit_lbl}) "
                        f"no Sweet Spot superam barreira intraday, convertendo FVG em Inversion FVG (iFVG)."
                    )
                else:
                    # Sem fluxo suficiente para superar a barreira intraday
                    setup.status = SetupStatus.BLOQUEADO

            # Melhoria B: Alvo Dinâmico Adaptativo (Parcial na borda do FVG)
            # Aplicável se a operação estiver CONFIRMADA e houver um FVG antes do alvo integral
            if setup.status == SetupStatus.CONFIRMADO and closest_obs:
                sym_base = getattr(self.spec, 'symbol_base', 'WIN').upper()
                tick_size = getattr(self.spec, 'tick_size', 5.0)
                min_partial_dist = 80.0 if sym_base == "WIN" else (8.0 if sym_base == "WDO" else 0.20)
                obs_dist = closest_obs.get('distance', 0.0)

                # Exigir que a parcial esteja a pelo menos min_partial_dist da entrada e antes do alvo final
                if min_partial_dist <= obs_dist < setup.target_points:
                    edge_raw = closest_obs.get('edge_price', setup.entry_price)
                    if tick_size > 0:
                        edge_rounded = round(edge_raw / tick_size) * tick_size
                    else:
                        edge_rounded = edge_raw
                    setup.partial_target_price = edge_rounded
                    setup.partial_target_points = abs(edge_rounded - setup.entry_price)

            # Confirmação de segurança: Filtro Macro S&P 500 (Veto Anti-Contramão e Buffer 11:25-11:30)
            macro_res = self.sp500_filter.evaluate_macro_filter(setup.direction, now)
            if not macro_res.is_allowed:
                setup.status = SetupStatus.BLOQUEADO
                setup.macro_status = macro_res.tag
                setup.macro_reason = macro_res.reason
                if macro_res.tag not in setup.invalidation_criteria:
                    setup.invalidation_criteria = f"{macro_res.tag} {macro_res.reason} | {setup.invalidation_criteria}"

            # Confirmação de segurança: Veto de Tape Reading para Absorção Contrária
            flow_pat = flow_summary.get("flow_pattern", "") if isinstance(flow_summary, dict) else ""
            if setup.direction == Direction.COMPRA and "ABSORÇÃO VENDEDORA" in flow_pat.upper():
                setup.status = SetupStatus.BLOQUEADO
                obs_msg = "[VETO TAPE READING] Absorção Vendedora ativa: Compradores absorvidos no Book. Entrada barrada."
                if obs_msg not in setup.obstacles:
                    setup.obstacles.append(obs_msg)
                if any("ABSORÇÃO" in str(x) for x in setup.interpretations) is False:
                    setup.interpretations.append("⛔ " + obs_msg)
            elif setup.direction == Direction.VENDA and "ABSORÇÃO COMPRADORA" in flow_pat.upper():
                setup.status = SetupStatus.BLOQUEADO
                obs_msg = "[VETO TAPE READING] Absorção Compradora ativa: Vendedores absorvidos no Book. Entrada barrada."
                if obs_msg not in setup.obstacles:
                    setup.obstacles.append(obs_msg)
                if any("ABSORÇÃO" in str(x) for x in setup.interpretations) is False:
                    setup.interpretations.append("⛔ " + obs_msg)

        alert = format_operational_alert(
            setup=setup,
            regimes=regimes,
            source_name=health.source_name,
            delay_ms=health.latency_ms,
            quality_status=quality_str,
            general_status_override="SEM OPERAÇÃO — AGUARDAR" if setup is None else None,
            flow_data=flow_summary,
            symbol_override=sym_label,
            fvg_radar_banner=fvg_radar_banner,
            sp500_macro_filter=self.sp500_filter
        )
        self.last_alert = alert

        # Gravar para persistência e compartilhamento imediato
        try:
            import os, sys
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(base_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            with open(os.path.join(data_dir, "latest_alert.txt"), "w", encoding="utf-8") as f:
                f.write(alert)
            sym_clean = self.spec.symbol_base.lower()
            with open(os.path.join(data_dir, f"latest_alert_{sym_clean}.txt"), "w", encoding="utf-8") as f:
                f.write(alert)
            if setup is not None:
                # Chave de rastreabilidade única que inclui status, direção, preços e setup
                entry_key = f"{setup.status.value}_{setup.direction.value}_{setup.entry_price:.2f}_{setup.setup_name}_{setup.stop_price:.2f}_{setup.target_price:.2f}"
                if setup.status == SetupStatus.CONFIRMADO:
                    if self.alerted_entry_key != entry_key:
                        self.alerted_entry_key = entry_key
                        self._trigger_audio_beep_sequence(setup.direction.value, setup.entry_price)
                        log_msg = f"\n[{now.strftime('%d/%m/%Y %H:%M:%S')}] SETUP CONFIRMADO:\n{alert}\n"
                        self._append_with_rotation(os.path.join(data_dir, "live_alerts.log"), log_msg)
                        self._append_with_rotation(os.path.join(data_dir, f"live_alerts_{sym_clean}.log"), log_msg)
                elif setup.status == SetupStatus.BLOQUEADO:
                    # Registrar log apenas uma vez por setup bloqueado (sem apitos e sem repetir a cada 2s)
                    if self.alerted_entry_key != entry_key:
                        self.alerted_entry_key = entry_key
                        log_msg = f"\n[{now.strftime('%d/%m/%Y %H:%M:%S')}] SETUP BLOQUEADO:\n{alert}\n"
                        self._append_with_rotation(os.path.join(data_dir, "live_alerts.log"), log_msg)
                        self._append_with_rotation(os.path.join(data_dir, f"live_alerts_{sym_clean}.log"), log_msg)

                # Registro de auditoria do Filtro Macro S&P 500
                if getattr(setup, 'macro_status', None):
                    if "BLOQUEADO" in str(setup.macro_status):
                        log_macro = f"\n[{now.strftime('%d/%m/%Y %H:%M:%S')}] [FILTRO S&P 500 - BLOQUEIO] {setup.macro_status}: {setup.macro_reason}\n"
                        self._append_with_rotation(os.path.join(data_dir, "live_alerts.log"), log_macro)
                        self._append_with_rotation(os.path.join(data_dir, f"live_alerts_{sym_clean}.log"), log_macro)
                    elif "CONFLUÊNCIA" in str(setup.macro_status):
                        log_macro = f"\n[{now.strftime('%d/%m/%Y %H:%M:%S')}] [FILTRO S&P 500 - CONFLUÊNCIA] {setup.macro_status}: {setup.macro_reason}\n"
                        self._append_with_rotation(os.path.join(data_dir, "live_alerts.log"), log_macro)
                        self._append_with_rotation(os.path.join(data_dir, f"live_alerts_{sym_clean}.log"), log_macro)
            else:
                # Mercado em SEM OPERAÇÃO — AGUARDAR: limpa a trava para que o próximo setup toque os 5 apitos
                self.alerted_entry_key = None
        except Exception:
            pass

        return alert

    @staticmethod
    def _append_with_rotation(file_path: str, content: str, max_bytes: int = 10 * 1024 * 1024, backup_count: int = 3):
        """
        Escreve no log com rotação automática quando o arquivo atinge max_bytes (padrão: 10 MB).
        Mantém até backup_count arquivos (.1, .2, .3) evitando crescimento descontrolado.
        """
        try:
            import os
            content_bytes = len(content.encode("utf-8"))
            if os.path.exists(file_path):
                curr_size = os.path.getsize(file_path)
                if (curr_size + content_bytes) >= max_bytes and curr_size > 0:
                    for i in range(backup_count - 1, 0, -1):
                        sfn = f"{file_path}.{i}"
                        dfn = f"{file_path}.{i + 1}"
                        if os.path.exists(sfn):
                            try:
                                if os.path.exists(dfn):
                                    os.remove(dfn)
                                os.rename(sfn, dfn)
                            except Exception:
                                pass
                    dfn = f"{file_path}.1"
                    try:
                        if os.path.exists(dfn):
                            os.remove(dfn)
                        os.rename(file_path, dfn)
                    except Exception:
                        pass

            with open(file_path, "a", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            pass

    def _trigger_audio_beep_sequence(self, direction_str: str, entry_price: float = 0.0):
        """
        Emite exatamente uma sequência de 5 apitos rápidos em thread assíncrona
        quando uma nova entrada é gerada e anuncia por voz no Windows para execução imediata no SuperDOM.
        Toca e NÃO repete enquanto a mesma entrada permanecer na tela.
        """
        import threading
        def _play():
            import time
            try:
                import winsound
                freq = 1350 if direction_str == "COMPRA" else 900
                for _ in range(5):
                    try:
                        winsound.Beep(freq, 75)
                    except Exception:
                        try:
                            winsound.MessageBeep(winsound.MB_OK)
                        except Exception:
                            pass
                    time.sleep(0.06)

                # Anúncio sonoro por voz (SAPI) para o trader não precisar olhar para o terminal
                try:
                    import subprocess
                    p_num = int(round(entry_price))
                    txt_msg = f"{direction_str}! Preço {p_num}"
                    ps_cmd = f"(New-Object -ComObject SAPI.SpVoice).Speak('{txt_msg}')"
                    subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, timeout=4)
                except Exception:
                    pass
            except Exception:
                pass

        threading.Thread(target=_play, daemon=True).start()
