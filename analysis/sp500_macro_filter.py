"""
analysis/sp500_macro_filter.py
Filtro de Segurança Macro e Confluência Institucional (S&P 500 / Abertura NYSE 11:30).

Monitora o contrato futuro do S&P 500 da B3 (suporte dinâmico a prefixos WSP e ISP)
em tempo real para:
1. Buffer Pré-Abertura NYSE (11:25 às 11:30): Hard Gate preventivo para bloquear novas
   entradas no WIN nos 5 minutos antes da abertura das bolsas americanas.
2. Veto Anti-Contramão (11:30 em diante): Bloquear COMPRA no WIN se o S&P 500 operar
   em queda ou perder a mínima de NY; bloquear VENDA no WIN se o S&P 500 operar
   em alta ou romper a máxima de NY.
3. Confluência Dupla (11:30 em diante): Priorizar entradas com bônus de +20 pontos no
   Score SMC e tag de destaque [🌎 CONFLUÊNCIA S&P 500 ATIVA].
4. Modo Fail-Safe: Se o feed do S&P 500 estiver desconectado ou sem ticks (>10s),
   mantém o buffer de segurança (11:25-11:30) ativo e opera normalmente no restante do dia.
"""

from dataclasses import dataclass, field
from datetime import datetime, date, time as dt_time, timedelta
from enum import Enum
from typing import Optional, Dict, Any, List, Tuple

from core.contract import TZ_BRASILIA, get_current_sp500_contract
from core.models import Direction, SetupStatus


class SP500Regime(str, Enum):
    PRE_OPEN = "PRE_OPEN"                # 09:00:00 até 11:24:59 (Fase de preparação B3)
    BUFFER_PRE_OPEN = "BUFFER_PRE_OPEN"  # 11:25:00 até 11:29:59 (Hard Gate Preventivo)
    NYSE_OPEN = "NYSE_OPEN"              # 11:30:00 até 17:30:00 (Sessão à vista Wall Street)
    CLOSED = "CLOSED"                    # Fora do pregão


@dataclass
class MacroFilterResult:
    """Resultado detalhado da avaliação do Filtro Macro S&P 500."""
    is_allowed: bool
    reason: str
    is_confluence_boost: bool = False
    score_bonus: int = 0
    tag: str = ""
    regime: SP500Regime = SP500Regime.PRE_OPEN
    nyse_open_price: Optional[float] = None
    nyse_high: Optional[float] = None
    nyse_low: Optional[float] = None
    sp500_current_price: float = 0.0
    sp500_trend: str = "NEUTRO"
    sp500_symbol: str = "WSP"
    is_feed_healthy: bool = True
    displacement_pts: float = 0.0


class SP500MacroFilter:
    """
    Controlador central do Filtro de Segurança Macro e Confluência Institucional S&P 500.
    """

    def __init__(self, preferred_symbol: Optional[str] = None):
        self.preferred_symbol = preferred_symbol
        self.active_symbol: str = (
            preferred_symbol.upper().strip()
            if preferred_symbol
            else get_current_sp500_contract(prefix="WSP")
        )

        # Cotação e integridade
        self.last_price: float = 0.0
        self.last_tick_time: Optional[datetime] = None
        self.day_open: Optional[float] = None
        self.day_high: Optional[float] = None
        self.day_low: Optional[float] = None

        # Sessão de Nova York (>= 11:30:00)
        self.nyse_open_price: Optional[float] = None
        self.nyse_high: Optional[float] = None
        self.nyse_low: Optional[float] = None
        self.nyse_session_date: Optional[date] = None
        self.nyse_displacement: float = 0.0
        self.nyse_ticks: List[Tuple[datetime, float]] = []

        # Horários operacionais oficiais (Horário de Brasília)
        self.time_buffer_start = dt_time(11, 25, 0)
        self.time_nyse_open = dt_time(11, 30, 0)
        self.time_session_end = dt_time(18, 0, 0)
        self.stale_timeout_sec: float = 120.0

    def set_symbol(self, symbol: str):
        """Atualiza dinamicamente o símbolo ativo do S&P 500 (ex: WSPZ26 ou ISPZ26)."""
        if symbol:
            self.active_symbol = symbol.upper().strip()

    def register_tick(
        self,
        price: float,
        timestamp: Optional[datetime] = None,
        symbol: Optional[str] = None
    ):
        """
        Registra um novo tick de preço do S&P 500 recebido do ProfitPro via DDE.
        Atualiza abertura, máxima e mínima do dia e da sessão de NY.
        """
        if price <= 0:
            return

        if timestamp is None:
            now = datetime.now(TZ_BRASILIA)
        elif timestamp.tzinfo is None:
            now = timestamp.replace(tzinfo=TZ_BRASILIA)
        else:
            now = timestamp

        if symbol:
            self.active_symbol = symbol.upper().strip()

        self.last_price = price
        self.last_tick_time = now

        # Inicialização do dia
        if self.day_open is None:
            self.day_open = price
        if self.day_high is None or price > self.day_high:
            self.day_high = price
        if self.day_low is None or price < self.day_low:
            self.day_low = price

        current_date = now.date()
        if self.nyse_session_date != current_date:
            self.nyse_open_price = None
            self.nyse_high = None
            self.nyse_low = None
            self.nyse_session_date = current_date
            self.nyse_ticks.clear()

        # Sessão de Nova York (>= 11:30:00)
        if now.time() >= self.time_nyse_open:
            if self.nyse_open_price is None:
                self.nyse_open_price = price
                self.nyse_high = price
                self.nyse_low = price
            else:
                if self.nyse_high is None or price > self.nyse_high:
                    self.nyse_high = price
                if self.nyse_low is None or price < self.nyse_low:
                    self.nyse_low = price

            self.nyse_displacement = price - self.nyse_open_price
            self.nyse_ticks.append((now, price))
            if len(self.nyse_ticks) > 300:
                self.nyse_ticks.pop(0)

    def is_feed_healthy(self, now: Optional[datetime] = None) -> bool:
        """Verifica se o feed do S&P 500 está ativo e sem ticks stale."""
        if self.last_tick_time is None or self.last_price <= 0:
            return False

        if now is None:
            now = datetime.now(TZ_BRASILIA)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=TZ_BRASILIA)

        diff_sec = (now - self.last_tick_time).total_seconds()
        timeout = getattr(self, 'stale_timeout_sec', 120.0)
        return (0.0 <= diff_sec <= timeout)

    def get_regime(self, now: Optional[datetime] = None) -> SP500Regime:
        """Determina o regime horário operacional atual."""
        if now is None:
            now = datetime.now(TZ_BRASILIA)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=TZ_BRASILIA)

        t = now.time()
        if t < dt_time(9, 0, 0) or t > self.time_session_end:
            return SP500Regime.CLOSED
        elif t < self.time_buffer_start:
            return SP500Regime.PRE_OPEN
        elif self.time_buffer_start <= t < self.time_nyse_open:
            return SP500Regime.BUFFER_PRE_OPEN
        else:
            return SP500Regime.NYSE_OPEN

    def evaluate_macro_filter(
        self,
        direction: Direction,
        timestamp: Optional[datetime] = None
    ) -> MacroFilterResult:
        """
        Executa a avaliação determinística do Filtro Macro para uma direção pretendida no WIN.
        Retorna se a operação é autorizada, se há veto anti-contramão ou confluência dupla.
        """
        if timestamp is None:
            now = datetime.now(TZ_BRASILIA)
        elif timestamp.tzinfo is None:
            now = timestamp.replace(tzinfo=TZ_BRASILIA)
        else:
            now = timestamp

        regime = self.get_regime(now)
        healthy = self.is_feed_healthy(now)

        # ---------------------------------------------------------------------
        # REGRA 1: BUFFER PRÉ-ABERTURA NYSE (11:25:00 até 11:29:59)
        # HARD GATE PREVENTIVO: Ativo mesmo em modo Fail-Safe
        # ---------------------------------------------------------------------
        if regime == SP500Regime.BUFFER_PRE_OPEN:
            return MacroFilterResult(
                is_allowed=False,
                reason=(
                    "BUFFER PRÉ-ABERTURA NYSE (11:25 às 11:30): Entradas bloqueadas preventivamente "
                    "nos 5 minutos antes da abertura de Wall Street para evitar stops por volatilidade."
                ),
                is_confluence_boost=False,
                score_bonus=0,
                tag="[⛔ BLOQUEADO: BUFFER PRÉ-NYSE]",
                regime=regime,
                sp500_current_price=self.last_price,
                sp500_symbol=self.active_symbol,
                is_feed_healthy=healthy
            )

        # ---------------------------------------------------------------------
        # REGRA 2: SESSÃO INSTITUCIONAL GLOBAL NYSE (11:30:00 em diante)
        # Prioridade máxima de segurança: enquanto o S&P estiver em tendência
        # confirmada pós-abertura, o veto anti-contramão é mantido por memória
        # mesmo em pausas transitórias de ticks na B3 (tolerância até 300s).
        # ---------------------------------------------------------------------
        if regime == SP500Regime.NYSE_OPEN:
            diff_tick = (now - self.last_tick_time).total_seconds() if self.last_tick_time else 9999.0
            if self.nyse_open_price is not None and diff_tick <= 300.0:
                ny_open = self.nyse_open_price
                curr = self.last_price
                ny_high = self.nyse_high if self.nyse_high is not None else curr
                ny_low = self.nyse_low if self.nyse_low is not None else curr
                disp = curr - ny_open

                # A. VETO ANTI-CONTRAMÃO (Blindado com Memória Institucional de NY)
                # Bloqueio de COMPRA no WIN se S&P estiver abaixo da abertura de NY com deslocamento vendedor ou perdendo a mínima
                if direction == Direction.COMPRA and (curr < ny_open or (curr <= ny_low and disp < 0)):
                    return MacroFilterResult(
                        is_allowed=False,
                        reason=(
                            f"VETO ANTI-CONTRAMÃO: S&P 500 operando em queda em NY (Preço: {curr:.2f} < "
                            f"Open NY: {ny_open:.2f} | Mínima NY: {ny_low:.2f} | Deslocamento: {disp:+.2f} pts). "
                            "Bloqueio estrito de COMPRA no WIN mantido por memória institucional."
                        ),
                        is_confluence_boost=False,
                        score_bonus=0,
                        tag="[⛔ BLOQUEADO: VETO S&P 500 ANTI-CONTRAMÃO]",
                        regime=regime,
                        nyse_open_price=ny_open,
                        nyse_high=ny_high,
                        nyse_low=ny_low,
                        sp500_current_price=curr,
                        sp500_trend="BAIXA",
                        sp500_symbol=self.active_symbol,
                        is_feed_healthy=healthy,
                        displacement_pts=disp
                    )

                # Bloqueio de VENDA no WIN se S&P estiver acima da abertura de NY com deslocamento comprador ou rompendo a máxima
                if direction == Direction.VENDA and (curr > ny_open or (curr >= ny_high and disp > 0)):
                    return MacroFilterResult(
                        is_allowed=False,
                        reason=(
                            f"VETO ANTI-CONTRAMÃO: S&P 500 operando em alta em NY (Preço: {curr:.2f} > "
                            f"Open NY: {ny_open:.2f} | Máxima NY: {ny_high:.2f} | Deslocamento: {disp:+.2f} pts). "
                            "Bloqueio estrito de VENDA no WIN mantido por memória institucional."
                        ),
                        is_confluence_boost=False,
                        score_bonus=0,
                        tag="[⛔ BLOQUEADO: VETO S&P 500 ANTI-CONTRAMÃO]",
                        regime=regime,
                        nyse_open_price=ny_open,
                        nyse_high=ny_high,
                        nyse_low=ny_low,
                        sp500_current_price=curr,
                        sp500_trend="ALTA",
                        sp500_symbol=self.active_symbol,
                        is_feed_healthy=healthy,
                        displacement_pts=disp
                    )

                # B. BOOST DE CONFLUÊNCIA DUPLA
                if direction == Direction.COMPRA and curr >= (ny_high - 1.0) and disp >= 0:
                    return MacroFilterResult(
                        is_allowed=True,
                        reason=(
                            f"CONFLUÊNCIA DUPLA: WIN Compra + S&P 500 em alta em NY (Preço: {curr:.2f} >= "
                            f"Máxima NY: {ny_high:.2f} | Open NY: {ny_open:.2f} | Deslocamento: {disp:+.2f} pts). "
                            "Alinhamento institucional pleno (+20 Score SMC)."
                        ),
                        is_confluence_boost=True,
                        score_bonus=20,
                        tag="[🌎 CONFLUÊNCIA S&P 500 ATIVA]",
                        regime=regime,
                        nyse_open_price=ny_open,
                        nyse_high=ny_high,
                        nyse_low=ny_low,
                        sp500_current_price=curr,
                        sp500_trend="ALTA",
                        sp500_symbol=self.active_symbol,
                        is_feed_healthy=healthy,
                        displacement_pts=disp
                    )

                if direction == Direction.VENDA and curr <= (ny_low + 1.0) and disp <= 0:
                    return MacroFilterResult(
                        is_allowed=True,
                        reason=(
                            f"CONFLUÊNCIA DUPLA: WIN Venda + S&P 500 em queda em NY (Preço: {curr:.2f} <= "
                            f"Mínima NY: {ny_low:.2f} | Open NY: {ny_open:.2f} | Deslocamento: {disp:+.2f} pts). "
                            "Alinhamento institucional pleno (+20 Score SMC)."
                        ),
                        is_confluence_boost=True,
                        score_bonus=20,
                        tag="[🌎 CONFLUÊNCIA S&P 500 ATIVA]",
                        regime=regime,
                        nyse_open_price=ny_open,
                        nyse_high=ny_high,
                        nyse_low=ny_low,
                        sp500_current_price=curr,
                        sp500_trend="BAIXA",
                        sp500_symbol=self.active_symbol,
                        is_feed_healthy=healthy,
                        displacement_pts=disp
                    )

                trend_desc = "ALTA" if disp > 0 else ("BAIXA" if disp < 0 else "NEUTRO")
                return MacroFilterResult(
                    is_allowed=True,
                    reason=f"S&P 500 alinhado em NY (Open: {ny_open:.2f} | Preço: {curr:.2f} | {disp:+.2f} pts). Operação liberada.",
                    is_confluence_boost=False,
                    score_bonus=0,
                    tag="",
                    regime=regime,
                    nyse_open_price=ny_open,
                    nyse_high=ny_high,
                    nyse_low=ny_low,
                    sp500_current_price=curr,
                    sp500_trend=trend_desc,
                    sp500_symbol=self.active_symbol,
                    is_feed_healthy=healthy,
                    displacement_pts=disp
                )

        # ---------------------------------------------------------------------
        # REGRA 3: FAIL-SAFE — Feed offline ou sem ticks recentes fora do buffer
        # ---------------------------------------------------------------------
        if not healthy:
            return MacroFilterResult(
                is_allowed=True,
                reason=(
                    f"S&P 500: OFFLINE (FAIL-SAFE) — Feed {self.active_symbol} ausente ou sem ticks "
                    f"recentes (>{getattr(self, 'stale_timeout_sec', 120.0):.0f}s). Motor WIN operando normalmente em modo autônomo."
                ),
                is_confluence_boost=False,
                score_bonus=0,
                tag="[⚠️ S&P 500 OFFLINE (FAIL-SAFE)]",
                regime=regime,
                sp500_current_price=self.last_price,
                sp500_symbol=self.active_symbol,
                is_feed_healthy=False
            )

        # ---------------------------------------------------------------------
        # REGRA 4: FASE DE PREPARAÇÃO B3 (09:00:00 até 11:24:59)
        # ---------------------------------------------------------------------
        if regime == SP500Regime.PRE_OPEN:
            day_ref = self.day_open or self.last_price
            disp = self.last_price - day_ref
            trend = "ALTA" if disp > 0 else ("BAIXA" if disp < 0 else "NEUTRO")
            return MacroFilterResult(
                is_allowed=True,
                reason=(
                    f"FASE DE PREPARAÇÃO B3: S&P 500 ({self.active_symbol}) em {self.last_price:.2f} "
                    f"({disp:+.2f} pts na sessão prévia). Operações normais liberadas no WIN."
                ),
                is_confluence_boost=False,
                score_bonus=0,
                tag="",
                regime=regime,
                sp500_current_price=self.last_price,
                sp500_trend=trend,
                sp500_symbol=self.active_symbol,
                is_feed_healthy=True,
                displacement_pts=disp
            )

        # Fora do horário de pregão
        return MacroFilterResult(
            is_allowed=True,
            reason="Fora do horário regular da sessão americana.",
            is_confluence_boost=False,
            score_bonus=0,
            tag="",
            regime=regime,
            sp500_current_price=self.last_price,
            sp500_symbol=self.active_symbol,
            is_feed_healthy=healthy
        )

    def get_summary_text(self) -> str:
        """Gera texto compacto de 1 linha para exibição no dashboard."""
        healthy = self.is_feed_healthy()
        regime = self.get_regime()
        p = self.last_price

        if regime == SP500Regime.BUFFER_PRE_OPEN:
            if not healthy and p <= 0:
                return f"{self.active_symbol}: OFFLINE | [⛔ BUFFER PRÉ-NYSE ATIVO 11:25-11:30]"
            return f"{self.active_symbol}: {p:.2f} | [⛔ BUFFER PRÉ-NYSE ATIVO (11:25-11:30)]"

        elif regime == SP500Regime.NYSE_OPEN and self.nyse_open_price is not None:
            open_ny = self.nyse_open_price
            disp = p - open_ny
            trend = "ALTA" if disp > 0 else ("BAIXA" if disp < 0 else "NEUTRO")
            stale_tag = " [SLOW TICKS]" if not healthy else ""
            return f"{self.active_symbol} (NY): {p:.2f} (Open: {open_ny:.2f} | {disp:+.2f} pts - {trend}){stale_tag}"

        if not healthy:
            return f"{self.active_symbol}: OFFLINE (FAIL-SAFE)"

        if regime == SP500Regime.PRE_OPEN:
            ref = self.day_open or p
            disp = p - ref
            return f"{self.active_symbol} (Pré-NY): {p:.2f} ({disp:+.2f} pts)"
        else:
            return f"{self.active_symbol}: {p:.2f}"
