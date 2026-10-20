"""Validação independente do extrator: confere a nota contra as regras fiscais, sem gabarito.

Se a validação aponta um problema, a nota vai para revisão humana. A avaliação mede quantos
erros reais a validação consegue pegar sozinha e quantos alarmes falsos ela dá.
"""

from __future__ import annotations

from .documentos import chave_valida, cnpj_valido, cpf_valido, ler_chave, so_digitos
from .modelo import Nota

TOLERANCIA = 0.02  # centavos de arredondamento


def validar(n: Nota) -> list[str]:
    problemas: list[str] = []
    obrigatorios = {"chave_acesso": n.chave_acesso, "numero": n.numero, "data_emissao": n.data_emissao,
                    "emitente_cnpj": n.emitente_cnpj, "valor_total": n.valor_total}
    problemas += [f"{campo} ausente" for campo, valor in obrigatorios.items() if valor in (None, "")]
    if not n.itens:
        problemas.append("nenhum item")

    if n.chave_acesso:
        if not chave_valida(n.chave_acesso):
            problemas.append("chave de acesso com dígito verificador inválido")
        elif (c := ler_chave(n.chave_acesso)) is not None:
            # a chave carrega CNPJ, modelo, série, número e mês: tudo tem de bater com o resto da nota
            if n.emitente_cnpj and so_digitos(n.emitente_cnpj) != c.cnpj:
                problemas.append("CNPJ do emitente diferente do que está na chave")
            if n.numero is not None and n.numero != c.numero:
                problemas.append("número diferente do que está na chave")
            if n.serie is not None and n.serie != c.serie:
                problemas.append("série diferente da que está na chave")
            if n.tipo and {"NFE": "55", "NFCE": "65"}[n.tipo] != c.modelo:
                problemas.append("tipo de nota diferente do modelo na chave")
            if n.data_emissao and n.data_emissao.strftime("%y%m") != c.ano_mes:
                problemas.append("mês de emissão diferente do que está na chave")

    if n.emitente_cnpj and not cnpj_valido(n.emitente_cnpj):
        problemas.append("CNPJ do emitente inválido")
    if n.destinatario_documento:
        doc = so_digitos(n.destinatario_documento)
        if not (cpf_valido(doc) if len(doc) == 11 else cnpj_valido(doc)):
            problemas.append("CPF/CNPJ do destinatário inválido")

    if n.itens and n.valor_total is not None and all(i.valor_total is not None for i in n.itens):
        soma = sum(i.valor_total for i in n.itens)
        if abs(soma - n.valor_total) > TOLERANCIA:
            problemas.append(f"soma dos itens ({soma:.2f}) diferente do total ({n.valor_total:.2f})")
    for pos, i in enumerate(n.itens, start=1):
        if None not in (i.quantidade, i.valor_unitario, i.valor_total):
            if abs(i.quantidade * i.valor_unitario - i.valor_total) > max(TOLERANCIA, i.valor_total * 0.001):
                problemas.append(f"item {pos}: quantidade x valor unitário não bate com o total")
    return problemas
