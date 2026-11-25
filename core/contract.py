"""
core/contract.py
Definições normativas e regras contratuais da B3 para Mini-Índice (WIN), Mini-Dólar (WDO) e Ações (VALE3).
"""

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Optional
import zoneinfo

TZ_BRASILIA = zoneinfo.ZoneInfo("America/Sao_Paulo")

# Meses de vencimento do índice futuro (meses pares)
EXPIRY_MONTHS = {
    2: "G",  # Fevereiro
    4: "J",  # Abril
    6: "M",  # Junho
    8: "Q",  # Agosto
    10: "V", # Outubro
    12: "Z"  # Dezembro
}

# Meses de vencimento do dólar futuro (todos os meses)
EXPIRY_MONTHS_DOL = {
    1: "F",  # Janeiro
    2: "G",  # Fevereiro
    3: "H",  # Março
    4: "J",  # Abril
    5: "K",  # Maio
    6: "M",  # Junho
    7: "N",  # Julho
    8: "Q",  # Agosto
    9: "U",  # Setembro
    10: "V", # Outubro
    11: "X", # Novembro
    12: "Z"  # Dezembro
}

MONTH_TO_CODE = EXPIRY_MONTHS
CODE_TO_MONTH = {v: k for k, v in EXPIRY_MONTHS.items()}


@dataclass(frozen=True)
class AssetSpec:
    symbol_base: str                 # "WIN", "WDO", "VALE3"
    name: str                        # Nome descritivo do ativo
    point_value: float               # Valor financeiro por unidade/ponto
    tick_size: float                 # Passo mínimo de cotação da B3
    default_stop_points: float       # Stop padrão em pontos/reais
    default_target_points: float     # Alvo padrão em pontos/reais
    min_fvg_size: float              # Tamanho mínimo do Fair Value Gap
    min_displacement_body: float     # Mínimo de corpo para deslocamento
    ce_body_low: float               # Mínimo de corpo para C.E. em tempos menores (1m/2m)
    ce_body_high: float              # Mínimo de corpo para C.E. em tempos maiores (5m+)
    decimals: int                    # Casas decimais para exibição
    contract_size: int = 1           # Tamanho padrão do lote/contrato
    trading_start: str = "09:00:00"  # Horário regular de abertura
    trading_end: str = "18:25:00"    # Horário de encerramento do pregão
    approach_radius: float = 150.0   # Raio padrão de aproximação para radar FVG


WIN_SPEC = AssetSpec(
    symbol_base="WIN",
    name="Mini-Índice B3",
    point_value=0.20,
    tick_size=5.0,
    default_stop_points=250.0,
    default_target_points=400.0,
    min_fvg_size=10.0,
    min_displacement_body=50.0,
    ce_body_low=180.0,
    ce_body_high=220.0,
    decimals=0,
    contract_size=1,
    trading_start="09:00:00",
    trading_end="18:25:00",
    approach_radius=150.0
)

WDO_SPEC = AssetSpec(
    symbol_base="WDO",
    name="Mini-Dólar B3",
    point_value=10.00,
    tick_size=0.5,
    default_stop_points=5.0,
    default_target_points=8.0,
    min_fvg_size=1.0,
    min_displacement_body=2.0,
    ce_body_low=4.0,
    ce_body_high=6.0,
    decimals=2,
    contract_size=1,
    trading_start="09:00:00",
    trading_end="18:25:00",
    approach_radius=5.0
)

VALE3_SPEC = AssetSpec(
    symbol_base="VALE3",
    name="Vale S.A. (Ações B3)",
    point_value=1.00,
    tick_size=0.01,
    default_stop_points=0.35,
    default_target_points=0.56,
    min_fvg_size=0.05,
    min_displacement_body=0.15,
    ce_body_low=0.25,
    ce_body_high=0.35,
    decimals=2,
    contract_size=100,
    trading_start="10:00:00",
    trading_end="17:55:00",
    approach_radius=0.30
)

EQUITY_DEFAULT_SPEC = AssetSpec(
    symbol_base="ACAO",
    name="Ações B3",
    point_value=1.00,
    tick_size=0.01,
    default_stop_points=0.35,
    default_target_points=0.56,
    min_fvg_size=0.05,
    min_displacement_body=0.15,
    ce_body_low=0.25,
    ce_body_high=0.35,
    decimals=2,
    contract_size=100,
    trading_start="10:00:00",
    trading_end="17:55:00",
    approach_radius=0.30
)


@dataclass(frozen=True)
class WINContractSpec:
    symbol_base: str = "WIN"
    point_value: float = 0.20        # R$ 0,20 por ponto por contrato
    tick_size: float = 5.0           # Passo mínimo de 5 pontos
    contract_size: int = 1           # 1 minicontrato
    trading_start: str = "09:00:00"  # Horário regular de abertura
    trading_end: str = "18:25:00"    # Horário de encerramento do pregão


def get_wednesday_nearest_15th(year: int, month: int) -> date:
    """
    Regra oficial B3 para o vencimento do Índice Futuro (IND/WIN):
    Quarta-feira mais próxima do dia 15 do mês de vencimento.
    """
    target = date(year, month, 15)
    weekday = target.weekday() # 0=Monday, 2=Wednesday
    diff = 2 - weekday
    candidate = target + timedelta(days=diff)
    return candidate


def get_current_win_contract(dt: Optional[datetime] = None) -> str:
    """
    Retorna o ticker negociável ativo do mini-índice para a data fornecida.
    Ex: WINZ26, WING27, etc.
    """
    if dt is None:
        dt = datetime.now(TZ_BRASILIA)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_BRASILIA)

    current_date = dt.date()
    year = dt.year
    month = dt.month

    for y in [year, year + 1]:
        for m in sorted(EXPIRY_MONTHS.keys()):
            if y == year and m < month:
                continue
            exp_date = get_wednesday_nearest_15th(y, m)
            if current_date <= exp_date:
                year_code = str(y)[-2:]
                month_code = EXPIRY_MONTHS[m]
                return f"WIN{month_code}{year_code}"

    return "WINZ26"


def get_first_business_day(year: int, month: int) -> date:
    """Retorna o primeiro dia útil do mês (regra de vencimento do Dólar Futuro)."""
    d = date(year, month, 1)
    while d.weekday() >= 5:  # 5=Sábado, 6=Domingo
        d += timedelta(days=1)
    return d


def get_current_wdo_contract(dt: Optional[datetime] = None) -> str:
    """
    Retorna o ticker negociável ativo do mini-dólar (WDO) para a data fornecida.
    O Dólar Futuro vence no 1º dia útil do mês de vencimento.
    Portanto, ao longo do mês M, negocia-se o contrato que vence no início do mês M+1.
    Ex: Em Novembro/2026, negocia-se WDOZ26 (vencimento no 1º dia útil de Dezembro).
    """
    if dt is None:
        dt = datetime.now(TZ_BRASILIA)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_BRASILIA)

    current_date = dt.date()
    year = dt.year
    month = dt.month

    # O contrato do mês atual vence no primeiro dia útil deste mês
    curr_first_bd = get_first_business_day(year, month)
    if current_date <= curr_first_bd:
        # Ainda negocia o contrato do mês atual
        target_month = month
        target_year = year
    else:
        # Já rola para o próximo mês
        if month == 12:
            target_month = 1
            target_year = year + 1
        else:
            target_month = month + 1
            target_year = year

    month_code = EXPIRY_MONTHS_DOL[target_month]
    year_code = str(target_year)[-2:]
    return f"WDO{month_code}{year_code}"


def resolve_symbol(symbol: Optional[str] = None) -> str:
    """Resolve código genérico (WIN, WDO, VALE3) para o contrato/ticker exato ativo."""
    if not symbol:
        return get_current_win_contract()
    
    sym = symbol.strip().upper()
    if sym in ("WIN", "IND"):
        return get_current_win_contract()
    elif sym in ("WDO", "DOL"):
        return get_current_wdo_contract()
    return sym


def get_asset_spec(symbol: str) -> AssetSpec:
    """Retorna as especificações de microestrutura e risco do ativo."""
    sym = (symbol or "").strip().upper()
    if sym.startswith("WIN") or sym.startswith("IND"):
        return WIN_SPEC
    elif sym.startswith("WDO") or sym.startswith("DOL"):
        return WDO_SPEC
    elif sym.startswith("VALE"):
        return VALE3_SPEC
    else:
        # Default para ações (PETR4, BBAS3, etc.) ou derivativos
        return EQUITY_DEFAULT_SPEC


def validate_price_tick(price: float, tick_size: float = 5.0) -> bool:
    """Valida se o preço respeita o tick mínimo."""
    remainder = round(price % tick_size, 4)
    return remainder == 0.0 or abs(remainder - tick_size) < 1e-4


def round_to_tick(price: float, tick_size: float = 5.0) -> float:
    """Ajusta o preço para o tick mais próximo."""
    if tick_size <= 0:
        return price
    return round(round(price / tick_size) * tick_size, 4)


def calculate_financial_risk(points: float, num_contracts: int = 1, point_value: float = 0.20) -> float:
    """Calcula o valor financeiro em R$ para uma dada variação em pontos."""
    return points * point_value * num_contracts

