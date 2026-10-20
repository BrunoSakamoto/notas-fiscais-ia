"""Linha de base sem IA: lê o texto do PDF e aplica expressões regulares.

Funciona bem quando o PDF tem texto e o leiaute é o esperado, e não lê imagem nenhuma. É
justamente essa a comparação que interessa: o que a IA acrescenta sobre uma solução simples.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pdfplumber

from ..documentos import so_digitos
from ..modelo import Item, Nota
from . import Resultado

NOME = "regras"
VERSAO = "1"

_NUM = r"\d{1,3}(?:\.\d{3})*,\d{2,4}"
_CNPJ = r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}"
_CPF = r"\d{3}\.\d{3}\.\d{3}-\d{2}"


def _numero(texto: str) -> float:
    return float(texto.replace(".", "").replace(",", "."))


def _data(texto: str):
    return datetime.strptime(texto, "%d/%m/%Y").date()


def _chave(texto: str) -> str | None:
    m = re.search(r"(?:\d{4} ){10}\d{4}", texto)
    return so_digitos(m.group()) if m else None


def _danfe(t: str) -> Nota:
    linhas = t.splitlines()
    emit = re.search(r"RECEBEMOS DE (.+?) OS PRODUTOS", t)
    numero = re.search(r"Nº ([\d.]+)\s+SÉRIE (\d+)", t)
    docs = re.findall(rf"{_CNPJ}|{_CPF}", t)
    data = re.search(r"(\d{2}/\d{2}/\d{4})", t[t.find("DESTINAT"):]) if "DESTINAT" in t else None

    total = None
    for i, linha in enumerate(linhas):
        if "VALOR TOTAL DA NOTA" in linha.upper() and i + 1 < len(linhas):
            valores = re.findall(_NUM, linhas[i + 1])
            total = _numero(valores[-1]) if valores else None

    itens = []
    padrao = re.compile(rf"^\d{{4}} (.+?) \d{{8}} \d{{4}} \S+ ({_NUM}) ({_NUM}) ({_NUM})$")
    for linha in linhas:
        if m := padrao.match(linha.strip()):
            itens.append(Item(descricao=m[1], quantidade=_numero(m[2]),
                              valor_unitario=_numero(m[3]), valor_total=_numero(m[4])))
    return Nota(
        tipo="NFE",
        chave_acesso=_chave(t),
        numero=int(numero[1].replace(".", "")) if numero else None,
        serie=int(numero[2]) if numero else None,
        data_emissao=_data(data[1]) if data else None,
        emitente_nome=emit[1].strip() if emit else None,
        emitente_cnpj=so_digitos(docs[0]) if docs else None,
        destinatario_documento=so_digitos(docs[1]) if len(docs) > 1 else None,
        valor_total=total,
        itens=itens,
    )


def _nfce(t: str) -> Nota:
    linhas = [linha.strip() for linha in t.splitlines() if linha.strip()]
    cab = re.search(r"NFC-e nº (\d+)\s+Série (\d+)\s+(\d{2}/\d{2}/\d{4})", t)
    cnpj = re.search(rf"CNPJ: ({_CNPJ})", t)
    cpf = re.search(rf"CPF: ({_CPF})", t)
    total = re.search(rf"VALOR A PAGAR R\$\s*({_NUM})", t)

    itens = []
    for i, linha in enumerate(linhas[:-1]):
        if m := re.match(r"^\d{3} \d+\s+(.+)$", linha):
            if v := re.match(rf"^({_NUM}) \S+ X ({_NUM})\s+({_NUM})$", linhas[i + 1]):
                itens.append(Item(descricao=m[1], quantidade=_numero(v[1]),
                                  valor_unitario=_numero(v[2]), valor_total=_numero(v[3])))
    return Nota(
        tipo="NFCE",
        chave_acesso=_chave(t),
        numero=int(cab[1]) if cab else None,
        serie=int(cab[2]) if cab else None,
        data_emissao=_data(cab[3]) if cab else None,
        emitente_nome=linhas[0] if linhas else None,
        emitente_cnpj=so_digitos(cnpj[1]) if cnpj else None,
        destinatario_documento=so_digitos(cpf[1]) if cpf else None,
        valor_total=_numero(total[1]) if total else None,
        itens=itens,
    )


def extrair(caminho: Path) -> Resultado:
    if caminho.suffix.lower() != ".pdf":
        return Resultado(Nota(), observacoes=["imagem: regras só leem PDF com texto"])
    with pdfplumber.open(caminho) as pdf:
        texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
    if not texto.strip():
        return Resultado(Nota(), observacoes=["PDF sem camada de texto"])
    nota = _danfe(texto) if "DANFE" in texto else _nfce(texto)
    return Resultado(nota)
