"""Extratores: recebem o caminho de um documento e devolvem uma Nota (e o custo, se houver)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from ..modelo import Nota


@dataclass
class Resultado:
    nota: Nota
    tokens_entrada: int = 0
    tokens_saida: int = 0
    observacoes: list[str] = field(default_factory=list)


class LoteInterrompido(RuntimeError):
    """Erro que vale para todos os documentos seguintes (ex.: cota do dia esgotada): o lote para."""


# Ligado quando a pessoa aperta Ctrl+C: as esperas entre tentativas acordam na hora e desistem.
INTERROMPER = threading.Event()


def esperar(segundos: float) -> None:
    """Espera entre tentativas que pode ser interrompida (time.sleep numa thread não pode)."""
    if INTERROMPER.wait(segundos):
        raise LoteInterrompido("interrompido pelo usuário")
