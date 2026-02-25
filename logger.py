"""
Módulo de logging estructurado para el agente WhatsApp.
Reemplaza todos los print() por logging JSON para observabilidad en producción.
"""
import logging
import json
import sys
from datetime import datetime


class JSONFormatter(logging.Formatter):
    """Formateador que produce logs en JSON para consumo por herramientas de observabilidad."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def get_logger(name: str) -> logging.Logger:
    """Crea un logger estructurado con formato JSON."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
