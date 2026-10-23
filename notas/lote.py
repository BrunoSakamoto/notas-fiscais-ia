"""Processa todos os documentos com um extrator e grava no DuckDB.

Cada (documento, extrator, versão) é extraído uma vez só: rodar de novo pula o que já foi
feito, o que torna a execução retomável e não gasta cota da API à toa. Mudar o prompt exige
mudar a VERSAO do extrator, e aí tudo é reprocessado para a versão nova.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb

from .extratores import INTERROMPER, LoteInterrompido, Resultado
from .validacao import validar

log = logging.getLogger(__name__)

DDL = """
create table if not exists extracoes (
    documento       varchar not null,
    extrator        varchar not null,
    versao          varchar not null,
    modelo          varchar,
    nota            json,
    erro            varchar,
    problemas       json,
    observacoes     json,
    tokens_entrada  integer,
    tokens_saida    integer,
    segundos        double,
    extraido_em     timestamp default current_timestamp,
    primary key (documento, extrator, versao)
);
create table if not exists gabarito (
    documento  varchar primary key,
    arquivo    varchar not null,
    variante   varchar not null,
    nota       json not null
);
"""


def conectar(banco: Path) -> duckdb.DuckDBPyConnection:
    banco.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(banco))
    con.execute(DDL)
    return con


def carregar_gabarito(con: duckdb.DuckDBPyConnection, arquivo: Path) -> int:
    registros = [json.loads(linha) for linha in arquivo.read_text(encoding="utf-8").splitlines() if linha]
    con.execute("delete from gabarito")
    con.executemany(
        "insert into gabarito values (?, ?, ?, ?)",
        [(r["id"], r["arquivo"], r["variante"], json.dumps(r["nota"], ensure_ascii=False)) for r in registros],
    )
    return len(registros)


def processar(
    con: duckdb.DuckDBPyConnection,
    pasta: Path,
    extrator: str,
    versao: str,
    funcao,
    modelo: str | None = None,
    paralelo: int = 1,
    refazer: bool = False,
) -> dict[str, int]:
    """Roda `funcao(caminho) -> Resultado` nos documentos pendentes. As chamadas podem ser
    paralelas (rede); a gravação acontece sempre na thread principal (o DuckDB tem um escritor)."""
    if refazer:
        con.execute("delete from extracoes where extrator = ? and versao = ?", [extrator, versao])
    pendentes = con.execute(
        """
        select g.documento, g.arquivo from gabarito g
        where not exists (
            select 1 from extracoes e
            where e.documento = g.documento and e.extrator = ? and e.versao = ? and e.erro is null
        )
        order by g.documento
        """,
        [extrator, versao],
    ).fetchall()
    contagem = {"processados": 0, "erros": 0, "ja_feitos": _total(con) - len(pendentes), "interrompido": None}

    parar = threading.Event()  # visto pelas threads: depois de uma interrupção, ninguém mais chama a API

    class _Pulado(Exception):
        pass

    def tarefa(documento: str, arquivo: str):
        if parar.is_set():
            raise _Pulado
        inicio = time.perf_counter()
        try:
            return documento, funcao(pasta / arquivo), None, time.perf_counter() - inicio
        except LoteInterrompido:
            parar.set()
            raise
        except Exception as erro:  # noqa: BLE001 - o erro de um documento não pode parar o lote
            return documento, None, f"{type(erro).__name__}: {erro}", time.perf_counter() - inicio

    INTERROMPER.clear()
    total = len(pendentes)
    feitos = 0
    with ThreadPoolExecutor(max_workers=max(1, paralelo)) as executor:
        futuros = [executor.submit(tarefa, d, a) for d, a in pendentes]
        try:
            for futuro in as_completed(futuros):
                try:
                    documento, resultado, erro, segundos = futuro.result()
                except _Pulado:
                    continue
                except LoteInterrompido as motivo:
                    # Nada é gravado: este documento e os seguintes ficam pendentes para a próxima execução.
                    contagem["interrompido"] = str(motivo)
                    log.warning("lote interrompido: %s", motivo)
                    continue
                _gravar(con, documento, extrator, versao, modelo, resultado, erro, segundos)
                contagem["erros" if erro else "processados"] += 1
                feitos += 1
                log.info(
                    "[%d/%d] %s %s %s (%.0f s)", feitos, total, extrator, documento,
                    "ERRO " + erro if erro else "ok", segundos,
                )
        except KeyboardInterrupt:
            # Ctrl+C: ninguém mais começa, as esperas acordam e o que já foi gravado fica.
            parar.set()
            INTERROMPER.set()
            for f in futuros:
                f.cancel()
            log.warning("interrompendo: aguardando a chamada em andamento terminar (no máximo 2 min)...")
            contagem["interrompido"] = "cancelado pelo usuário; o que já foi extraído está salvo"
    return contagem


def _total(con: duckdb.DuckDBPyConnection) -> int:
    return con.execute("select count(*) from gabarito").fetchone()[0]


def _gravar(con, documento, extrator, versao, modelo, resultado: Resultado | None, erro, segundos):
    nota_json = resultado.nota.model_dump_json() if resultado else None
    problemas = validar(resultado.nota) if resultado else []
    con.execute(
        "insert or replace into extracoes "
        "(documento, extrator, versao, modelo, nota, erro, problemas, observacoes, "
        " tokens_entrada, tokens_saida, segundos) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            documento, extrator, versao, modelo, nota_json, erro,
            json.dumps(problemas, ensure_ascii=False),
            json.dumps(resultado.observacoes if resultado else [], ensure_ascii=False),
            resultado.tokens_entrada if resultado else None,
            resultado.tokens_saida if resultado else None,
            segundos,
        ],
    )
