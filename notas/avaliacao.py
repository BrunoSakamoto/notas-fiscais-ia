"""Compara cada extração com o gabarito, campo a campo, e mede a validação.

Regras de comparação (as mesmas para todos os extratores):
  - textos: sem acento, em maiúsculas e com espaços normalizados;
  - CNPJ, CPF e chave: só os caracteres, sem pontuação;
  - valores: diferença de até 1 centavo; quantidades: até 0,001;
  - itens: a lista inteira tem de bater, item a item, na ordem.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date

import duckdb

from .modelo import CAMPOS, Nota

DDL = """
create or replace table avaliacao_campos (
    documento varchar, extrator varchar, versao varchar, variante varchar, tipo varchar,
    campo varchar, correto boolean, esperado varchar, obtido varchar
);
create or replace table avaliacao_documentos (
    documento varchar, extrator varchar, versao varchar, variante varchar, tipo varchar,
    campos_corretos integer, campos_total integer, itens_corretos boolean,
    documento_correto boolean, sinalizado boolean, falhou boolean, lida boolean,
    tokens_entrada integer, tokens_saida integer, segundos double
);
"""


def _texto(v) -> str:
    s = unicodedata.normalize("NFKD", str(v)).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def igual(campo: str, esperado, obtido) -> bool:
    if esperado is None or obtido is None:
        return esperado is None and obtido is None
    if campo in ("chave_acesso", "emitente_cnpj", "destinatario_documento"):
        # só a pontuação sai: o CNPJ alfanumérico (2026) tem letras que precisam ficar
        sem_pontuacao = lambda v: re.sub(r"[^0-9A-Za-z]", "", str(v)).upper()  # noqa: E731
        return sem_pontuacao(esperado) == sem_pontuacao(obtido)
    if campo == "valor_total":
        return abs(float(esperado) - float(obtido)) <= 0.011
    if isinstance(esperado, date) or campo == "data_emissao":
        return str(esperado) == str(obtido)
    if campo in ("numero", "serie"):
        return int(esperado) == int(obtido)
    return _texto(esperado) == _texto(obtido)


def itens_iguais(esperado: Nota, obtido: Nota) -> bool:
    if len(esperado.itens) != len(obtido.itens):
        return False
    for e, o in zip(esperado.itens, obtido.itens, strict=True):
        if None in (o.quantidade, o.valor_unitario, o.valor_total, o.descricao):
            return False
        if _texto(e.descricao) != _texto(o.descricao):
            return False
        if abs(e.quantidade - o.quantidade) > 0.001:
            return False
        if abs(e.valor_unitario - o.valor_unitario) > 0.011 or abs(e.valor_total - o.valor_total) > 0.011:
            return False
    return True


def avaliar(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(DDL)
    linhas = con.execute(
        """
        select e.documento, e.extrator, e.versao, g.variante, g.nota, e.nota, e.erro, e.problemas,
               e.tokens_entrada, e.tokens_saida, e.segundos
        from extracoes e join gabarito g using (documento)
        """
    ).fetchall()
    campos, documentos = [], []
    for doc, extrator, versao, variante, gab, ext, erro, problemas, t_in, t_out, seg in linhas:
        esperado = Nota.model_validate_json(gab)
        obtido = Nota.model_validate_json(ext) if ext else Nota()
        # Extração vazia é nota que o extrator não leu: não ganha ponto nem nos campos que
        # deveriam mesmo ficar vazios (ex.: consumidor não identificado).
        lida = obtido != Nota()
        acertos = 0
        for campo in CAMPOS:
            e, o = getattr(esperado, campo), getattr(obtido, campo)
            ok = lida and igual(campo, e, o)
            acertos += ok
            campos.append((doc, extrator, versao, variante, esperado.tipo, campo, ok,
                           None if e is None else str(e), None if o is None else str(o)))
        itens_ok = lida and itens_iguais(esperado, obtido)
        campos.append((doc, extrator, versao, variante, esperado.tipo, "itens", itens_ok,
                       f"{len(esperado.itens)} itens", f"{len(obtido.itens)} itens"))
        sinalizado = bool(json.loads(problemas or "[]")) or erro is not None
        documentos.append((doc, extrator, versao, variante, esperado.tipo, acertos, len(CAMPOS), itens_ok,
                           acertos == len(CAMPOS) and itens_ok, sinalizado, erro is not None, lida,
                           t_in, t_out, seg))
    if campos:
        con.executemany("insert into avaliacao_campos values (?, ?, ?, ?, ?, ?, ?, ?, ?)", campos)
        con.executemany("insert into avaliacao_documentos values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        documentos)


# ---------------------------------------------------------------- resumos (SQL)

RESUMO = """
select extrator, versao,
       count(*)                                              as documentos,
       avg(documento_correto::int)                           as documentos_100,
       sum(campos_corretos) / sum(campos_total)              as acerto_campos,
       avg(itens_corretos::int)                              as acerto_itens,
       avg(falhou::int)                                      as falhas,
       count(*) filter (where not lida)                      as nao_lidas,
       sum(tokens_entrada)                                   as tokens_entrada,
       sum(tokens_saida)                                     as tokens_saida,
       median(segundos)                                      as segundos_mediana
from avaliacao_documentos
group by all order by extrator, versao
"""

POR_VARIANTE = """
select extrator, variante, count(*) as documentos,
       avg(documento_correto::int) as documentos_100,
       sum(campos_corretos) / sum(campos_total) as acerto_campos
from avaliacao_documentos
group by extrator, variante order by extrator, case variante when 'pdf' then 1 when 'foto_boa' then 2 else 3 end
"""

POR_CAMPO = """
select extrator, campo, avg(correto::int) as acerto
from avaliacao_campos
group by all order by extrator, campo
"""

# A validação serve se pega os documentos errados sem alarmar demais os certos.
VALIDACAO = """
select extrator,
       count(*) filter (where not documento_correto)                        as com_erro,
       count(*) filter (where not documento_correto and sinalizado)         as erros_pegos,
       count(*) filter (where documento_correto)                            as corretos,
       count(*) filter (where documento_correto and sinalizado)             as alarmes_falsos
from avaliacao_documentos
group by all order by extrator
"""

# Erros de leitura de verdade: notas que o extrator leu, mas leu algum campo errado.
ERROS = """
select c.extrator, c.documento, c.variante, c.campo, c.esperado, c.obtido
from avaliacao_campos c
join avaliacao_documentos d using (documento, extrator, versao)
where not c.correto and d.lida
order by c.extrator, c.documento, c.campo
"""
