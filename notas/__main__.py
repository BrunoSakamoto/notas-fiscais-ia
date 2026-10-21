"""Linha de comando.

    python -m notas gerar --quantidade 60     # notas sintéticas + gabarito
    python -m notas extrair regras            # linha de base, sem IA
    python -m notas extrair gemini            # precisa de GEMINI_API_KEY (.env)
    python -m notas avaliar                   # compara com o gabarito e gera relatorio.html
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from . import avaliacao, gerador, lote, relatorio
from .extratores import gemini, regras

RAIZ = Path(os.getenv("NOTAS_DIR", "dados"))
BANCO = RAIZ / "resultados.duckdb"


def _carregar_env(arquivo: Path = Path(".env")) -> None:
    """Lê um .env simples (CHAVE=valor) sem dependência extra; variáveis já definidas vencem."""
    if arquivo.exists():
        for linha in arquivo.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                chave, valor = linha.split("=", 1)
                os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def _float_env(nome: str) -> float | None:
    valor = os.getenv(nome)
    return float(valor) if valor else None


def main(argv: list[str] | None = None) -> None:
    _carregar_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    p = argparse.ArgumentParser(prog="notas", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)
    g = sub.add_parser("gerar", help="gera notas sintéticas com gabarito")
    g.add_argument("--quantidade", type=int, default=60)
    g.add_argument("--semente", type=int, default=2026)
    e = sub.add_parser("extrair", help="extrai os campos de todas as notas")
    e.add_argument("extrator", choices=["regras", "gemini"])
    e.add_argument("--modelo", default=gemini.MODELO_PADRAO, help="modelo do Gemini")
    e.add_argument("--paralelo", type=int, default=4, help="chamadas simultâneas ao Gemini")
    e.add_argument("--refazer", action="store_true", help="ignora o cache e extrai tudo de novo")
    sub.add_parser("avaliar", help="compara com o gabarito e gera relatorio.html")
    args = p.parse_args(argv)

    if args.comando == "gerar":
        arquivo = gerador.gerar_conjunto(RAIZ, args.quantidade, args.semente)
        with lote.conectar(BANCO) as con:
            n = lote.carregar_gabarito(con, arquivo)
        print(f"{n} notas em {RAIZ / 'documentos'}; gabarito em {arquivo}")

    elif args.comando == "extrair":
        with lote.conectar(BANCO) as con:
            if con.execute("select count(*) from gabarito").fetchone()[0] == 0:
                sys.exit("Nenhuma nota carregada. Rode antes: python -m notas gerar")
            if args.extrator == "regras":
                feito = lote.processar(con, RAIZ / "documentos", regras.NOME, regras.VERSAO, regras.extrair)
            else:
                try:
                    cliente = gemini.criar_cliente()
                except gemini.SemChave as erro:
                    sys.exit(str(erro))
                feito = lote.processar(
                    con, RAIZ / "documentos", gemini.NOME, f"{gemini.VERSAO}-{args.modelo}",
                    lambda caminho: gemini.extrair(caminho, cliente, args.modelo),
                    modelo=args.modelo, paralelo=args.paralelo, refazer=args.refazer,
                )
        print(f"{feito['processados']} extraídas, {feito['erros']} com erro, {feito['ja_feitos']} já estavam no cache")
        if feito["interrompido"]:
            sys.exit(f"Parou antes do fim. {feito['interrompido']}")

    elif args.comando == "avaliar":
        with lote.conectar(BANCO) as con:
            avaliacao.avaliar(con)
            html = relatorio.gerar(con, _float_env("CUSTO_MILHAO_ENTRADA"), _float_env("CUSTO_MILHAO_SAIDA"))
            print(con.sql(avaliacao.RESUMO))
            print(con.sql(avaliacao.POR_VARIANTE))
        destino = RAIZ / "relatorio.html"
        destino.write_text(html, encoding="utf-8")
        print(f"Relatório: {destino}")


if __name__ == "__main__":
    main()
