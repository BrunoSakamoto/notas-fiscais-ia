"""Extratores: recebem o caminho de um documento e devolvem uma Nota (e o custo, se houver)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..modelo import Nota


@dataclass
class Resultado:
    nota: Nota
    tokens_entrada: int = 0
    tokens_saida: int = 0
    observacoes: list[str] = field(default_factory=list)
