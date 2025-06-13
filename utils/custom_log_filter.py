import logging
from typing import Optional

class RequestContextFilter(logging.Filter):
    """
    Um filtro de log que adiciona informações de contexto da requisição (método, endpoint, status_code)
    aos registros de log.
    """
    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self.method: Optional[str] = None
        self.endpoint: Optional[str] = None
        self.status_code: Optional[int] = None

    def filter(self, record: logging.LogRecord) -> bool:
        """
        Adiciona os atributos personalizados (method, endpoint, status_code) ao LogRecord
        se eles estiverem definidos no filtro.
        """
        record.method = getattr(self, 'method', 'N/A')
        record.endpoint = getattr(self, 'endpoint', 'N/A')
        record.status_code = getattr(self, 'status_code', 'N/A')
        return True

# Crie uma instância global do filtro
request_context_filter = RequestContextFilter()