"""Dígitos verificadores dos documentos fiscais: CNPJ, CPF e chave de acesso da NF-e/NFC-e.

São as mesmas regras que a Receita e as Sefaz usam. Servem para gerar notas válidas e,
principalmente, para validar o que um extrator devolveu sem precisar do gabarito.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PESOS_CNPJ_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_PESOS_CNPJ_2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]


def so_digitos(texto: str | None) -> str:
    return re.sub(r"\D", "", texto or "")


def _valor_cnpj(c: str) -> int:
    # Desde julho de 2026 o CNPJ pode ter letras nas 12 primeiras posições; cada caractere
    # vale (código ASCII - 48), o que mantém os dígitos com o valor de sempre.
    return ord(c) - 48


def _dv_cnpj(base: str, pesos: list[int]) -> str:
    resto = sum(_valor_cnpj(c) * p for c, p in zip(base, pesos, strict=True)) % 11
    return "0" if resto < 2 else str(11 - resto)


def cnpj_valido(cnpj: str | None) -> bool:
    c = re.sub(r"[^0-9A-Za-z]", "", cnpj or "").upper()
    if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", c) or len(set(c)) == 1:
        return False
    d1 = _dv_cnpj(c[:12], _PESOS_CNPJ_1)
    d2 = _dv_cnpj(c[:12] + d1, _PESOS_CNPJ_2)
    return c[12:] == d1 + d2


def completar_cnpj(base12: str) -> str:
    d1 = _dv_cnpj(base12, _PESOS_CNPJ_1)
    return base12 + d1 + _dv_cnpj(base12 + d1, _PESOS_CNPJ_2)


def _dv_cpf(base: str) -> str:
    peso = len(base) + 1
    resto = sum(int(c) * (peso - i) for i, c in enumerate(base)) % 11
    return "0" if resto < 2 else str(11 - resto)


def cpf_valido(cpf: str | None) -> bool:
    c = so_digitos(cpf)
    if len(c) != 11 or len(set(c)) == 1:
        return False
    d1 = _dv_cpf(c[:9])
    return c[9:] == d1 + _dv_cpf(c[:9] + d1)


def completar_cpf(base9: str) -> str:
    d1 = _dv_cpf(base9)
    return base9 + d1 + _dv_cpf(base9 + d1)


def dv_chave(chave43: str) -> str:
    """Módulo 11 com pesos de 2 a 9, da direita para a esquerda."""
    soma, peso = 0, 2
    for c in reversed(chave43):
        soma += int(c) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


@dataclass(frozen=True)
class Chave:
    """As partes da chave de acesso de 44 dígitos."""

    uf: str
    ano_mes: str  # AAMM da emissão
    cnpj: str
    modelo: str  # 55 = NF-e, 65 = NFC-e
    serie: int
    numero: int
    tipo_emissao: str
    codigo: str
    dv: str


def montar_chave(uf: str, ano_mes: str, cnpj: str, modelo: str, serie: int, numero: int, codigo: str) -> str:
    base = f"{uf}{ano_mes}{cnpj}{modelo}{serie:03d}{numero:09d}1{codigo}"
    assert len(base) == 43, base
    return base + dv_chave(base)


def ler_chave(chave: str | None) -> Chave | None:
    c = so_digitos(chave)
    if len(c) != 44:
        return None
    return Chave(c[0:2], c[2:6], c[6:20], c[20:22], int(c[22:25]), int(c[25:34]), c[34], c[35:43], c[43])


def chave_valida(chave: str | None) -> bool:
    c = so_digitos(chave)
    return len(c) == 44 and dv_chave(c[:43]) == c[43]
