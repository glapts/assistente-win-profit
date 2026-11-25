"""
harness/telemetry_logger.py
Gravador determinístico de telemetria em formato JSONL (logs/signals_telemetry.jsonl).
Persiste cada sinal avaliado com timestamp de Brasília (BRT), direção, score ponderado,
vereditos dos 7 agentes, insumos de microestrutura (OrderBook, P_defesa, P_medio_reacao) e snapshot DDE.
"""

import json
import os
import threading
from datetime import datetime
from typing import Dict, Any, Optional
import zoneinfo

TZ_BRASILIA = zoneinfo.ZoneInfo("America/Sao_Paulo")


class TelemetryLogger:
    """
    Gravador assíncrono e thread-safe de telemetria para auditoria e A/B testing do Harness.
    Grava em logs/signals_telemetry.jsonl.
    """

    def __init__(self, log_path: Optional[str] = None):
        if log_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            log_dir = os.path.join(base_dir, "logs")
            os.makedirs(log_dir, exist_ok=True)
            self.log_path = os.path.join(log_dir, "signals_telemetry.jsonl")
        else:
            self.log_path = log_path
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)

        self._lock = threading.Lock()

    def log_evaluation(
        self,
        side: str,
        score_final: float,
        classification: str,
        verdicts: Dict[str, Any],
        book_insights: Dict[str, Any],
        p_defesa: float,
        p_medio_reacao: float,
        dde_summary: Optional[Dict[str, Any]] = None,
        setup_name: Optional[str] = None,
        entry_price: Optional[float] = None
    ) -> bool:
        """
        Registra uma linha JSONL contendo a fotografia analítica completa do momento da decisão.
        """
        now = datetime.now(TZ_BRASILIA)
        record = {
            "timestamp_brt": now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "iso_time": now.isoformat(),
            "side": str(side).upper(),
            "setup_name": setup_name or "N/D",
            "entry_price": entry_price or 0.0,
            "score_final": round(float(score_final), 2),
            "classification": classification,
            "p_defesa": round(float(p_defesa), 2),
            "p_medio_reacao": round(float(p_medio_reacao), 2),
            "book_insights": {
                "spread_pts": book_insights.get("spread_pts", 0.0),
                "voc": book_insights.get("voc", 0.0),
                "vov": book_insights.get("vov", 0.0),
                "imbalance_ratio": book_insights.get("imbalance_ratio", 0.5),
                "is_escora": book_insights.get("is_escora", False),
                "is_blefe": book_insights.get("is_blefe", False),
                "status_tag": book_insights.get("status_tag", "N/D")
            },
            "agents_verdicts": {
                name: {
                    "bias": v.bias if hasattr(v, "bias") else v.get("bias"),
                    "score": round(float(v.score if hasattr(v, "score") else v.get("score", 0.0)), 2),
                    "status_tag": v.status_tag if hasattr(v, "status_tag") else v.get("status_tag"),
                    "reasons": v.reasons if hasattr(v, "reasons") else v.get("reasons", [])
                }
                for name, v in verdicts.items()
            },
            "dde_snapshot": dde_summary or {}
        }

        try:
            with self._lock:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            return True
        except Exception:
            return False
