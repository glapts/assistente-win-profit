"""
core/smc/scalper_glaucio.py
========================================================================================
MÓDULO: ScalperGlaucio
Especializado em Microestrutura SMC de 1 Minuto no Mini-Índice B3 (WIN).
Rastreia FVGs e iFVGs com numeração espelhada do Profit Pro e gatilhos no 50% CE.
========================================================================================
Regras Operacionais:
1. Numeração de Candles:
   - Candle #1 = Primeiro candle negociado do dia (09:00 ou pós-leilão).
   - Identifica trincas formadoras (ex: "Candles 4, 5 e 6: FVG formado").
   - Gatilho armado para execução no Candle seguinte (ex: Candle #7).
2. Geometria do Gap:
   - Aceita gaps a partir de 5.0 pontos (1 tick de desbalanceamento na B3).
   - Cálculo exato do 50% CE (Consequent Encroachment) arredondado para o tick (5 pts).
3. Filtro de Tendência do Dia:
   - Tendência de ALTA  (Preço > VWAP/Abertura) -> Emite exclusivamente LONG (Verde).
   - Tendência de BAIXA (Preço < VWAP/Abertura) -> Emite exclusivamente SHORT (Vermelho).
4. iFVG (Inverted FVG):
   - Transição automática após fechamento através da zona estrutural.
   - Gatilho no reteste do 50% CE da zona invertida.
5. Gestão de Risco:
   - Alvo Fixo: +100.0 pontos.
   - Stop Fixo: -150.0 pontos.
========================================================================================
"""

from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict, Callable
import sys
import os

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

from core.contract import round_to_tick


def format_price_br(val: float) -> str:
    """Formata preço no padrão B3 com separador de milhar por ponto (ex: 183.240)."""
    return f"{val:,.0f}".replace(",", ".")


# Cores ANSI para Terminal PowerShell
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_GREEN = "\033[92m"
ANSI_RED = "\033[91m"
ANSI_YELLOW = "\033[93m"
ANSI_CYAN = "\033[96m"
ANSI_MAGENTA = "\033[95m"
ANSI_WHITE = "\033[97m"
ANSI_BG_GREEN = "\033[42m\033[30m"
ANSI_BG_RED = "\033[41m\033[97m"


@dataclass
class CandleM1:
    """Representação de um candle fechado de 1 minuto."""
    candle_id: int
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class FVGZone:
    """Estrutura e estado de um FVG de 1 minuto."""
    id: str
    candle_ids: List[int]       # [c1_id, c2_id, c3_id]
    side: str                   # 'BUY' (Bullish FVG) ou 'SELL' (Bearish FVG)
    created_at: datetime
    gap_bottom: float
    gap_top: float
    gap_size: float
    ce_50: float
    target_price: float
    stop_price: float
    candle_times: List[str] = field(default_factory=list)  # ['10:42', '10:43', '10:44']
    is_mitigated: bool = False
    mitigated_at: Optional[datetime] = None
    is_inverted: bool = False
    inverted_at: Optional[datetime] = None
    ifvg_side: Optional[str] = None     # 'SELL' se era BUY; 'BUY' se era SELL
    ifvg_mitigated: bool = False


@dataclass
class ScalperSignal:
    """Sinal disparado pelo módulo ScalperGlaucio."""
    timestamp: datetime
    signal_type: str            # 'FVG_DIRECT' ou 'IFVG_INVERTED'
    direction: str              # 'LONG' ou 'SHORT'
    fvg_id: str
    candle_ids: List[int]
    trigger_candle_id: int      # Próximo candle (onde pendura no SuperDOM)
    ce_50: float
    target_price: float
    stop_price: float
    gap_size: float
    trend_day: str              # 'ALTA' ou 'BAIXA'
    description: str
    candle_times: List[str] = field(default_factory=list)  # ['10:42', '10:43', '10:44']
    trigger_candle_time: str = ""                         # '10:45'


class ScalperGlaucio:
    """
    Motor determinístico de scalping SMC de 1 minuto com foco em execução no SuperDOM.
    """

    def __init__(
        self,
        min_gap_pts: float = 5.0,
        target_pts: float = 100.0,
        stop_pts: float = 150.0,
        filter_trend: bool = True,
        beep_on_signal: bool = True,
        on_signal_callback: Optional[Callable[[ScalperSignal], None]] = None,
        market_open_time: Optional[time] = None
    ):
        self.min_gap_pts = min_gap_pts
        self.target_pts = target_pts
        self.stop_pts = stop_pts
        self.filter_trend = filter_trend
        self.beep_on_signal = beep_on_signal
        self.on_signal_callback = on_signal_callback
        self._user_market_open_time = market_open_time
        self.market_open_time = market_open_time
        self._fallback_open_time = time(9, 3)
        self._candle_counter_override: Optional[int] = None

        # Estado da Sessão
        self.current_date: Optional[date] = None
        self.candles_history: List[CandleM1] = []
        
        # Métrica de Tendência Diária
        self.day_open: Optional[float] = None
        self.cum_pv: float = 0.0
        self.cum_vol: float = 0.0
        self.vwap: Optional[float] = None
        self.trend_day: str = "INDEFINIDA"

        # Zonas ativas monitoradas
        self.active_fvgs: List[FVGZone] = []
        self.active_ifvgs: List[FVGZone] = []
        self.signals_history: List[ScalperSignal] = []

    def get_candle_index(self, dt: datetime) -> int:
        """
        Cálculo determinístico do índice de candle baseado na hora real de abertura ($T_{open}$).
        Fórmula: (Hora * 60 + Minuto) - (Hora_Abertura * 60 + Minuto_Abertura) + 1
        """
        open_t = self.market_open_time or self._fallback_open_time
        cur_min = dt.hour * 60 + dt.minute
        open_min = open_t.hour * 60 + open_t.minute
        return max(1, cur_min - open_min + 1)

    @property
    def candle_counter(self) -> int:
        if self._candle_counter_override is not None:
            return self._candle_counter_override
        if not self.candles_history:
            return 0
        return self.candles_history[-1].candle_id

    @candle_counter.setter
    def candle_counter(self, val: int):
        self._candle_counter_override = val

    def reset_session(self, session_date: date):
        """Reinicia o estado para um novo dia de negociação."""
        self.current_date = session_date
        self._candle_counter_override = None
        self.market_open_time = self._user_market_open_time
        self.candles_history.clear()
        self.day_open = None
        self.cum_pv = 0.0
        self.cum_vol = 0.0
        self.vwap = None
        self.trend_day = "INDEFINIDA"
        self.active_fvgs.clear()
        self.active_ifvgs.clear()

    def update_trend(self, candle: CandleM1):
        """Atualiza a VWAP e a tendência do pregão."""
        if self.day_open is None:
            self.day_open = candle.open

        typical_price = (candle.high + candle.low + candle.close) / 3.0
        vol = candle.volume if candle.volume > 0 else 1.0

        self.cum_pv += typical_price * vol
        self.cum_vol += vol
        self.vwap = self.cum_pv / self.cum_vol

        # Classificação da Tendência do Dia
        if candle.close > self.vwap and candle.close >= self.day_open:
            self.trend_day = "ALTA"
        elif candle.close < self.vwap and candle.close <= self.day_open:
            self.trend_day = "BAIXA"
        elif candle.close > self.vwap:
            self.trend_day = "ALTA"
        elif candle.close < self.vwap:
            self.trend_day = "BAIXA"
        else:
            self.trend_day = "INDEFINIDA"

    def on_candle_closed(
        self,
        timestamp: datetime,
        open_price: float,
        high_price: float,
        low_price: float,
        close_price: float,
        volume: float = 0.0,
        candle_id: Optional[int] = None
    ) -> List[ScalperSignal]:
        """
        Recebe um candle de 1 minuto fechado e processa formação de FVGs e gatilhos de iFVGs.
        Retorna lista de novos sinais emitidos no fechamento deste candle.
        """
        # Checagem de troca de dia
        candle_date = timestamp.date()
        if self.current_date is None or candle_date != self.current_date:
            self.reset_session(candle_date)

        # Determinação determinística da abertura caso não fixada previamente
        if self.market_open_time is None:
            if time(9, 0) <= timestamp.time() <= time(9, 15):
                self.market_open_time = timestamp.time().replace(second=0, microsecond=0)
            else:
                self.market_open_time = self._fallback_open_time

        # Índice determinístico do candle sincronizado com Profit Pro
        cid = candle_id if candle_id is not None else self.get_candle_index(timestamp)
        candle = CandleM1(
            candle_id=cid,
            timestamp=timestamp,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume
        )
        self.candles_history.append(candle)
        self.update_trend(candle)

        signals_emitted: List[ScalperSignal] = []

        # 1. Checar mitigações e inversões nas zonas abertas existentes
        self._check_existing_zones(candle, signals_emitted)

        # 2. Avaliar se este candle fecha uma nova trinca de FVG (Candles i-2, i-1, i)
        if len(self.candles_history) >= 3:
            new_fvg = self._detect_new_fvg()
            if new_fvg:
                self.active_fvgs.append(new_fvg)
                # Verifica se o sinal é permitido pelo filtro de tendência
                sig = self._evaluate_fvg_signal(new_fvg)
                if sig:
                    signals_emitted.append(sig)
                    self.signals_history.append(sig)
                    self._render_signal_terminal(sig)
                    if self.on_signal_callback:
                        self.on_signal_callback(sig)

        return signals_emitted

    def _detect_new_fvg(self) -> Optional[FVGZone]:
        """Avalia os últimos 3 candles para detectar novo FVG."""
        c1 = self.candles_history[-3]
        c2 = self.candles_history[-2]
        c3 = self.candles_history[-1]

        c_times = [
            c1.timestamp.strftime("%H:%M"),
            c2.timestamp.strftime("%H:%M"),
            c3.timestamp.strftime("%H:%M")
        ]

        # --- BULLISH FVG (COMPRA) ---
        # Condição: Mínima de C3 > Máxima de C1 (Gap aberto)
        if c3.low > c1.high:
            gap_size = c3.low - c1.high
            if gap_size >= self.min_gap_pts:
                gap_bottom = c1.high
                gap_top = c3.low
                raw_ce = (gap_top + gap_bottom) / 2.0
                ce_50 = round_to_tick(raw_ce, 5.0)
                target = round_to_tick(ce_50 + self.target_pts, 5.0)
                stop = round_to_tick(ce_50 - self.stop_pts, 5.0)

                fvg_id = f"FVG_BUY_C{c1.candle_id}_C{c3.candle_id}_{c3.timestamp.strftime('%H%M')}"
                return FVGZone(
                    id=fvg_id,
                    candle_ids=[c1.candle_id, c2.candle_id, c3.candle_id],
                    side="BUY",
                    created_at=c3.timestamp,
                    gap_bottom=gap_bottom,
                    gap_top=gap_top,
                    gap_size=gap_size,
                    ce_50=ce_50,
                    target_price=target,
                    stop_price=stop,
                    candle_times=c_times
                )

        # --- BEARISH FVG (VENDA) ---
        # Condição: Máxima de C3 < Mínima de C1 (Gap aberto)
        elif c3.high < c1.low:
            gap_size = c1.low - c3.high
            if gap_size >= self.min_gap_pts:
                gap_top = c1.low
                gap_bottom = c3.high
                raw_ce = (gap_top + gap_bottom) / 2.0
                ce_50 = round_to_tick(raw_ce, 5.0)
                target = round_to_tick(ce_50 - self.target_pts, 5.0)
                stop = round_to_tick(ce_50 + self.stop_pts, 5.0)

                fvg_id = f"FVG_SELL_C{c1.candle_id}_C{c3.candle_id}_{c3.timestamp.strftime('%H%M')}"
                return FVGZone(
                    id=fvg_id,
                    candle_ids=[c1.candle_id, c2.candle_id, c3.candle_id],
                    side="SELL",
                    created_at=c3.timestamp,
                    gap_bottom=gap_bottom,
                    gap_top=gap_top,
                    gap_size=gap_size,
                    ce_50=ce_50,
                    target_price=target,
                    stop_price=stop,
                    candle_times=c_times
                )

        return None

    def _evaluate_fvg_signal(self, fvg: FVGZone) -> Optional[ScalperSignal]:
        """Aplica filtro de tendência e formata o sinal com notação dupla."""
        next_candle_id = fvg.candle_ids[-1] + 1
        next_candle_time = (fvg.created_at + timedelta(minutes=1)).strftime("%H:%M")
        c_times = fvg.candle_times if fvg.candle_times else [fvg.created_at.strftime("%H:%M")] * 3

        c_times_str = f"[{c_times[0]}, {c_times[1]} e {c_times[2]}]" if len(c_times) >= 3 else f"[{fvg.created_at.strftime('%H:%M')}]"
        c_ids_str = f"(Barras #{fvg.candle_ids[0]}, #{fvg.candle_ids[1]} e #{fvg.candle_ids[2]})"
        estrutura_str = f"Candles {c_times_str} {c_ids_str}"

        if fvg.side == "BUY":
            direction = "LONG"
            if self.filter_trend and self.trend_day == "BAIXA":
                # Tendência de baixa veta novas compras diretas
                return None
            desc = f"{estrutura_str}: FVG Formado (Compra no 50% CE: {format_price_br(fvg.ce_50)})"
        else:
            direction = "SHORT"
            if self.filter_trend and self.trend_day == "ALTA":
                # Tendência de alta veta novas vendas diretas
                return None
            desc = f"{estrutura_str}: FVG Formado (Venda no 50% CE: {format_price_br(fvg.ce_50)})"

        return ScalperSignal(
            timestamp=fvg.created_at,
            signal_type="FVG_DIRECT",
            direction=direction,
            fvg_id=fvg.id,
            candle_ids=fvg.candle_ids,
            trigger_candle_id=next_candle_id,
            ce_50=fvg.ce_50,
            target_price=fvg.target_price,
            stop_price=fvg.stop_price,
            gap_size=fvg.gap_size,
            trend_day=self.trend_day,
            description=desc,
            candle_times=c_times,
            trigger_candle_time=next_candle_time
        )

    def _check_existing_zones(self, candle: CandleM1, signals: List[ScalperSignal]):
        """Monitora toque em 50% CE e inversões para iFVG."""
        # Monitora FVGs Diretos Ativos
        for fvg in list(self.active_fvgs):
            if fvg.is_mitigated or fvg.is_inverted:
                continue

            # Toque no 50% CE
            if fvg.side == "BUY" and candle.low <= fvg.ce_50:
                fvg.is_mitigated = True
                fvg.mitigated_at = candle.timestamp
            elif fvg.side == "SELL" and candle.high >= fvg.ce_50:
                fvg.is_mitigated = True
                fvg.mitigated_at = candle.timestamp

            # Checagem de Inversão (Rompimento do FVG por fechamento de corpo)
            if fvg.side == "BUY" and candle.close < fvg.gap_bottom:
                fvg.is_inverted = True
                fvg.inverted_at = candle.timestamp
                fvg.ifvg_side = "SELL"  # Vira resistência
                self.active_ifvgs.append(fvg)
                self._emit_ifvg_signal(fvg, candle, signals)
            elif fvg.side == "SELL" and candle.close > fvg.gap_top:
                fvg.is_inverted = True
                fvg.inverted_at = candle.timestamp
                fvg.ifvg_side = "BUY"   # Vira suporte
                self.active_ifvgs.append(fvg)
                self._emit_ifvg_signal(fvg, candle, signals)

    def _emit_ifvg_signal(self, fvg: FVGZone, candle: CandleM1, signals: List[ScalperSignal]):
        """Gera sinal de iFVG no momento da inversão de polaridade com notação dupla."""
        next_candle_id = candle.candle_id + 1
        next_candle_time = (candle.timestamp + timedelta(minutes=1)).strftime("%H:%M")
        c_times = fvg.candle_times if fvg.candle_times else [candle.timestamp.strftime("%H:%M")] * 3

        c_times_str = f"[{c_times[0]}, {c_times[1]} e {c_times[2]}]" if len(c_times) >= 3 else f"[{candle.timestamp.strftime('%H:%M')}]"
        c_ids_str = f"(Barras #{fvg.candle_ids[0]}, #{fvg.candle_ids[1]} e #{fvg.candle_ids[2]})"
        estrutura_str = f"Candles {c_times_str} {c_ids_str}"

        if fvg.ifvg_side == "SELL":
            direction = "SHORT"
            if self.filter_trend and self.trend_day == "ALTA":
                return
            target = round_to_tick(fvg.ce_50 - self.target_pts, 5.0)
            stop = round_to_tick(fvg.ce_50 + self.stop_pts, 5.0)
            desc = f"{estrutura_str}: iFVG INVERTIDO para VENDA (Reteste no 50% CE: {format_price_br(fvg.ce_50)})"
        else:
            direction = "LONG"
            if self.filter_trend and self.trend_day == "BAIXA":
                return
            target = round_to_tick(fvg.ce_50 + self.target_pts, 5.0)
            stop = round_to_tick(fvg.ce_50 - self.stop_pts, 5.0)
            desc = f"{estrutura_str}: iFVG INVERTIDO para COMPRA (Reteste no 50% CE: {format_price_br(fvg.ce_50)})"

        sig = ScalperSignal(
            timestamp=candle.timestamp,
            signal_type="IFVG_INVERTED",
            direction=direction,
            fvg_id=fvg.id,
            candle_ids=fvg.candle_ids,
            trigger_candle_id=next_candle_id,
            ce_50=fvg.ce_50,
            target_price=target,
            stop_price=stop,
            gap_size=fvg.gap_size,
            trend_day=self.trend_day,
            description=desc,
            candle_times=c_times,
            trigger_candle_time=next_candle_time
        )
        signals.append(sig)
        self.signals_history.append(sig)
        self._render_signal_terminal(sig)
        if self.on_signal_callback:
            self.on_signal_callback(sig)

    def _render_signal_terminal(self, sig: ScalperSignal):
        """Renderiza o alerta formatado no terminal PowerShell com notação dupla, ANSI Colors e Beep."""
        if self.beep_on_signal and HAS_WINSOUND:
            try:
                winsound.Beep(1200, 250)
            except Exception:
                pass

        time_str = sig.timestamp.strftime("%H:%M:%S")
        ce_fmt = format_price_br(sig.ce_50)
        target_fmt = format_price_br(sig.target_price)
        stop_fmt = format_price_br(sig.stop_price)
        target_diff = abs(sig.target_price - sig.ce_50)
        stop_diff = abs(sig.stop_price - sig.ce_50)

        # Notação Dupla com Numeração de Candles em Cor Destacada (Amarelo Ouro)
        if len(sig.candle_times) >= 3:
            c_times_str = f"[{sig.candle_times[0]}, {sig.candle_times[1]} e {sig.candle_times[2]}]"
        else:
            c_times_str = f"[{time_str}]"

        if len(sig.candle_ids) >= 3:
            c1_num = f"{ANSI_YELLOW}{ANSI_BOLD}#{sig.candle_ids[0]}{ANSI_RESET}"
            c2_num = f"{ANSI_YELLOW}{ANSI_BOLD}#{sig.candle_ids[1]}{ANSI_RESET}"
            c3_num = f"{ANSI_YELLOW}{ANSI_BOLD}#{sig.candle_ids[2]}{ANSI_RESET}"
            c_ids_str = f"(Barras {c1_num}, {c2_num} e {c3_num})"
        else:
            c_ids_str = f"(Barra {ANSI_YELLOW}{ANSI_BOLD}#{sig.candle_ids[0]}{ANSI_RESET})" if sig.candle_ids else ""

        estrutura_display = f"Candles {c_times_str} {c_ids_str}: FVG Formado"

        if sig.direction == "LONG":
            color = ANSI_GREEN
            bg_badge = ANSI_BG_GREEN
            badge_text = " >>> LONG (COMPRA) <<< "
            order_action = "COMPRA"
        else:
            color = ANSI_RED
            bg_badge = ANSI_BG_RED
            badge_text = " >>> SHORT (VENDA) <<< "
            order_action = "VENDA"

        # Preço formatado com pontuação de milhar e cor destacada (Azul Ciano) na frase do SuperDOM
        price_highlight = f"{ANSI_CYAN}{ANSI_BOLD}{ce_fmt}{ANSI_RESET}{ANSI_YELLOW}{ANSI_BOLD}"
        trigger_time_display = f"DAS {sig.trigger_candle_time} " if sig.trigger_candle_time else ""
        trigger_id_colored = f"{ANSI_CYAN}{ANSI_BOLD}#{sig.trigger_candle_id}{ANSI_RESET}{ANSI_YELLOW}{ANSI_BOLD}"
        action_superdom = f"PENDURAR {order_action} LIMITADA EM {price_highlight} NO CANDLE {trigger_time_display}({trigger_id_colored})"

        print(f"\n{color}{'='*88}{ANSI_RESET}")
        print(f"{color}{ANSI_BOLD}[ScalperGlaucio] - SINAL SMC 1-MINUTO | TENDÊNCIA DO DIA: [{sig.trend_day}]{ANSI_RESET}")
        print(f"{color}{'-'*88}{ANSI_RESET}")
        print(f"{bg_badge}{ANSI_BOLD}{badge_text}{ANSI_RESET} | Horário: {time_str} | Tipo: {sig.signal_type}")
        print(f"  * {ANSI_BOLD}ESTRUTURA      :{ANSI_RESET} {estrutura_display}")
        print(f"  * {ANSI_CYAN}{ANSI_BOLD}GATILHO 50% CE{ANSI_RESET}{ANSI_BOLD} :{ANSI_RESET} {color}{ANSI_BOLD}{ce_fmt}{ANSI_RESET} (Ponto de Equilíbrio)")
        print(f"  * {ANSI_BOLD}FAIXA DO GAP   :{ANSI_RESET} Amplitude de {sig.gap_size:.0f} pts")
        print(f"  * {ANSI_BOLD}GESTÃO DE RISCO:{ANSI_RESET} Alvo: {target_fmt} (+{target_diff:.0f} pts) | Stop: {stop_fmt} (-{stop_diff:.0f} pts)")
        print(f"{color}{'-'*88}{ANSI_RESET}")
        print(f"{ANSI_YELLOW}{ANSI_BOLD}>>> AÇÃO SUPERDOM: {action_superdom} <<<{ANSI_RESET}")
        print(f"{color}{'='*88}{ANSI_RESET}\n")
        sys.stdout.flush()
