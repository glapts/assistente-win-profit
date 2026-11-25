"""
core/agents/orchestrator.py
Agente Orquestrador ("O Gestor de Mesa").
Consolida os pareceres dos Agentes Especialistas (Macro, Cesta/DI e Sentinela),
calcula o Score de Confiança consolidado, resolve conflitos, verifica TTLs e atualiza
atomicamente o arquivo 'data/runtime_state.json' com versionamento estruturado.
"""

import os
import json
import tempfile
from datetime import datetime
from typing import Dict, Any, Optional

from core.agents.macro_agent import MacroAgent
from core.agents.basket_agent import BasketAgent
from core.agents.sentinel_agent import SentinelAgent
from core.harness.contracts import (
    RuntimeStateContract,
    ExecutionMode,
    TradingDirection,
    CircuitBreakerState,
    MacroRegimeState,
    BasketRegimeState
)


class Orchestrator:
    def __init__(
        self,
        macro_agent: Optional[MacroAgent] = None,
        basket_agent: Optional[BasketAgent] = None,
        sentinel_agent: Optional[SentinelAgent] = None,
        output_state_path: str = "data/runtime_state.json",
        execution_mode: ExecutionMode = ExecutionMode.COPILOT,
        ttl_seconds: float = 120.0
    ):
        self.macro_agent = macro_agent or MacroAgent()
        self.basket_agent = basket_agent or BasketAgent()
        self.sentinel_agent = sentinel_agent or SentinelAgent()
        
        self.output_state_path = output_state_path
        self.execution_mode = execution_mode
        self.ttl_seconds = ttl_seconds
        self.daily_stops_count = 0
        self.max_daily_stops = 2
        self.state_version = 0

    def record_stop_loss(self):
        """Registra um stop acionado no dia para o Circuit Breaker."""
        self.daily_stops_count += 1
        print(f"[ORQUESTRADOR] Stop registrado! Total hoje: {self.daily_stops_count}/{self.max_daily_stops}")
        self.run_cycle()

    def run_cycle(self, current_time: Optional[datetime] = None) -> RuntimeStateContract:
        """
        Executa um ciclo completo de consolidação de inteligência dos agentes,
        valida frescor dos dados e grava o runtime_state.json atualizado.
        """
        now = current_time or datetime.now()
        self.state_version += 1

        # 1. Coleta parecer de cada especialista
        op_macro = self.macro_agent.evaluate(now)
        op_basket = self.basket_agent.evaluate(now)
        op_sentinel = self.sentinel_agent.evaluate(now)

        # 2. Validação de TTL e integridade dos pareceres
        macro_stale = op_macro.is_expired(now) or op_macro.data_quality == "STALE"
        basket_stale = op_basket.is_expired(now) or op_basket.data_quality == "STALE"
        data_quality = "INTEGRITY_OK"

        if macro_stale or basket_stale:
            data_quality = "DEGRADED"

        # 2.1 Sincroniza stops persistidos em disco (data/circuit_breaker.json)
        cb_file = os.path.join(os.path.dirname(os.path.abspath(self.output_state_path)), "circuit_breaker.json")
        if os.path.exists(cb_file):
            try:
                with open(cb_file, "r", encoding="utf-8") as f:
                    cb_data = json.load(f)
                    self.daily_stops_count = max(self.daily_stops_count, cb_data.get("daily_stops_count", 0))
            except Exception:
                pass

        # 3. Resolução de Travas Rígidas (Lockouts de Segurança)
        is_circuit_breaker_active = self.daily_stops_count >= self.max_daily_stops
        is_lockout_active = (
            op_sentinel.lockout or
            op_macro.lockout or
            op_basket.lockout or
            is_circuit_breaker_active
        )

        trading_enabled = not is_lockout_active

        # 3.1 Detector de Descolamento Macro (Prevalência de Commodities / Blue Chips)
        # Se o S&P 500 gerar veto de compra, mas as Blue Chips domésticas estiverem fortes:
        # Vale >= +2.0%, Petrobras >= +1.5% e (Dólar < 0.0% ou DI1F29 <= 0.0 bps)
        vale_pct = self.basket_agent.stocks.get("VALE3", 0.0)
        petr_pct = self.basket_agent.stocks.get("PETR4", 0.0)
        di29_bps = self.basket_agent.di_rates.get("DI1F29", 0.0)
        dxy_pct = getattr(self.macro_agent, "dxy_change_pct", 0.0)

        is_decoupled = (
            op_macro.veto_buy and
            not op_basket.veto_buy and
            vale_pct >= 2.0 and
            petr_pct >= 1.5 and
            (di29_bps <= 0.0 or dxy_pct <= 0.0)
        )

        macro_veto_buy = False if is_decoupled else op_macro.veto_buy

        # 4. Resolução de Direção Permitida (Vetos Cruzados)
        veto_buy = macro_veto_buy or op_basket.veto_buy or op_sentinel.veto_buy
        veto_sell = op_macro.veto_sell or op_basket.veto_sell or op_sentinel.veto_sell

        if veto_buy and veto_sell:
            allowed_dir = TradingDirection.NONE
        elif veto_buy:
            allowed_dir = TradingDirection.SHORT_ONLY
        elif veto_sell:
            allowed_dir = TradingDirection.LONG_ONLY
        else:
            allowed_dir = TradingDirection.BOTH

        # Coleta de vetos e travas ativas
        active_vetos = []
        if is_circuit_breaker_active:
            active_vetos.append(f"CIRCUIT BREAKER: Limite diário de stops atingido ({self.daily_stops_count}/{self.max_daily_stops}).")
        if op_sentinel.lockout and op_sentinel.reason:
            active_vetos.append(f"SENTINELA: {op_sentinel.reason}")
        if op_macro.lockout and op_macro.reason:
            active_vetos.append(f"MACRO: {op_macro.reason}")
        if op_basket.lockout and op_basket.reason:
            active_vetos.append(f"CESTA/HORÁRIO: {op_basket.reason}")

        if is_decoupled:
            active_vetos.append(
                f"DESCOLAMENTO MACRO ATIVO: Força de Blue Chips (VALE3 {vale_pct:+.2f}%, PETR4 {petr_pct:+.2f}%) "
                f"e alívio doméstico anulam veto externo do S&P 500 ({self.macro_agent.sp500_change_pct:+.2f}%)."
            )

        if not is_lockout_active:
            if veto_buy and veto_sell:
                active_vetos.append("VETO DUPLO: Compras e Vendas vetadas simultaneamente.")
            elif veto_buy:
                reasons = [op.reason for op in [op_macro, op_basket, op_sentinel] if op.veto_buy and op.reason]
                active_vetos.append(f"VETO DE COMPRA: {'; '.join(reasons) if reasons else 'Veto de compra ativo'}")
            elif veto_sell:
                reasons = [op.reason for op in [op_macro, op_basket, op_sentinel] if op.veto_sell and op.reason]
                active_vetos.append(f"VETO DE VENDA: {'; '.join(reasons) if reasons else 'Veto de venda ativo'}")

        # 5. Cálculo Ponderado do Score de Confiança
        # Pesos: Macro (0.35) + Cesta/DI (0.45) + Sentinela (0.20)
        base_confidence = (
            op_macro.confidence * 0.35 +
            op_basket.confidence * 0.45 +
            op_sentinel.confidence * 0.20
        )

        # Penalidade por conflito direto entre Macro e Cesta
        if (op_macro.bias == "BULLISH" and op_basket.bias == "BEARISH") or \
           (op_macro.bias == "BEARISH" and op_basket.bias == "BULLISH"):
            base_confidence -= 0.20

        # Penalidade por dados degradados
        if data_quality == "DEGRADED":
            base_confidence -= 0.15

        confidence_score = max(0.10, min(1.0, round(base_confidence, 2)))

        if is_lockout_active:
            confidence_score = 0.0

        # 6. Montagem do Contrato RuntimeStateContract
        macro_state = MacroRegimeState(
            status=op_macro.bias,
            sp500_bias="BULLISH" if self.macro_agent.sp500_change_pct > 0 else "BEARISH",
            di_curve_bias="STRESSED" if self.basket_agent.di_rates.get("DI1F31", 0) > 5 else "STABLE",
            dxy_bias="BULLISH" if self.macro_agent.dxy_change_pct > 0 else "BEARISH",
            event_lockout=op_macro.lockout,
            lockout_reason=op_macro.reason if op_macro.lockout else None
        )

        basket_state = BasketRegimeState(
            synthetic_ibov_alignment="ALIGNED" if not op_basket.veto_buy else "DIVERGENT",
            vale3_petr4_status="POSITIVE" if not op_basket.veto_buy else "NEGATIVE"
        )

        circuit_breaker = CircuitBreakerState(
            daily_stops_count=self.daily_stops_count,
            max_daily_stops=self.max_daily_stops,
            lockout_active=is_circuit_breaker_active
        )

        runtime_state = RuntimeStateContract(
            timestamp=now.isoformat(),
            state_version=self.state_version,
            ttl_seconds=self.ttl_seconds,
            data_quality=data_quality,
            execution_mode=self.execution_mode,
            trading_enabled=trading_enabled,
            allowed_direction=allowed_dir,
            min_fvg_timeframe=15,
            risk_mode="CONSERVATIVE" if confidence_score < 0.75 else "NORMAL",
            confidence_score=confidence_score,
            circuit_breaker=circuit_breaker,
            macro_regime=macro_state,
            basket_regime=basket_state,
            active_vetos=active_vetos
        )

        # 7. Gravação Atômica do Arquivo (Evita colisão de leitura no Harness)
        self._write_state_atomic(runtime_state)

        return runtime_state

    def _write_state_atomic(self, state: RuntimeStateContract):
        """Grava o JSON usando arquivo temporário e replace atômico."""
        try:
            target_path = os.path.abspath(self.output_state_path)
            temp_dir = os.path.dirname(target_path)
            os.makedirs(temp_dir, exist_ok=True)
            
            with tempfile.NamedTemporaryFile("w", dir=temp_dir, delete=False, encoding="utf-8") as tf:
                json.dump(state.model_dump(), tf, indent=2, ensure_ascii=False)
                temp_name = tf.name
            
            # Substituição atômica no sistema de arquivos do Windows
            os.replace(temp_name, target_path)
        except Exception as e:
            print(f"[ORQUESTRADOR ERRO] Falha ao gravar {self.output_state_path}: {e}")
