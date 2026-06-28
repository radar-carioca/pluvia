"""Configuração de logging com Rich para o pacote pluvia.

Mantém uma instância de ``Console`` compartilhada entre o ``RichHandler``
do logging e os componentes de progresso da infraestrutura. Isso garante
que as mensagens de log e a barra de progresso não se sobrescrevam no
terminal — o Rich coordena as duas saídas internamente.
"""

from __future__ import annotations

import logging

from rich.console import Console

# Console singleton compartilhado por toda a infraestrutura do pacote.
# Usado tanto pelo Progress quanto pelo RichHandler para que o Rich
# consiga coordenar as duas saídas sem conflito.
console = Console()


def setup_logging(level: int = logging.INFO) -> None:
    """Configura o logging do pacote pluvia com saída via Rich.

    Registra um ``RichHandler`` no logger ``"pluvia"``, usando o ``Console``
    compartilhado com os componentes de progresso. Deve ser chamado uma vez
    na inicialização da aplicação, antes de qualquer operação do pacote.

    Parameters
    ----------
    level : int, optional
        Nível de log, por exemplo ``logging.DEBUG`` ou ``logging.WARNING``.
        Padrão: ``logging.INFO``.

    Examples
    --------
    Uso básico::

        import logging
        import pluvia

        pluvia.setup_logging()                        # INFO
        pluvia.setup_logging(level=logging.DEBUG)     # verbose
    """
    from rich.logging import RichHandler

    handler = RichHandler(
        console=console,
        rich_tracebacks=True,
        show_path=False,
        log_time_format="[%X]",
    )

    pluvia_logger = logging.getLogger("pluvia")
    pluvia_logger.setLevel(level)
    # Evita duplicação com handlers do logger raiz (ex: basicConfig)
    pluvia_logger.propagate = False

    if not any(isinstance(h, RichHandler) for h in pluvia_logger.handlers):
        pluvia_logger.addHandler(handler)
