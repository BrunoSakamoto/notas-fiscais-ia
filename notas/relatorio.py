"""Relatório HTML da avaliação: um arquivo só, sem dependências, para abrir no navegador."""

from __future__ import annotations

import html
from datetime import datetime

import duckdb

from . import avaliacao

_NOMES = {"pdf": "PDF digital", "foto_boa": "Foto boa", "foto_ruim": "Foto ruim",
          "regras": "Regras (sem IA)", "gemini": "Gemini"}


def _pct(x) -> str:
    return "–" if x is None else f"{x * 100:.1f}%".replace(".", ",")


def _barra(x) -> str:
    largura = 0 if x is None else max(0.0, min(1.0, x)) * 100
    return f'<span class="barra"><span style="width:{largura:.1f}%"></span></span>'


def _nome(v: str) -> str:
    return html.escape(_NOMES.get(v, v))


def gerar(con: duckdb.DuckDBPyConnection, custo_milhao_entrada: float | None = None,
          custo_milhao_saida: float | None = None) -> str:
    resumo = con.execute(avaliacao.RESUMO).fetchall()
    variantes = con.execute(avaliacao.POR_VARIANTE).fetchall()
    campos = con.execute(avaliacao.POR_CAMPO).fetchall()
    validacao = con.execute(avaliacao.VALIDACAO).fetchall()
    erros = con.execute(avaliacao.ERROS).fetchall()

    linhas_resumo = []
    for ext, versao, docs, doc100, acampos, aitens, falhas, nao_lidas, t_in, t_out, seg in resumo:
        custo = ""
        if t_in and custo_milhao_entrada is not None and custo_milhao_saida is not None:
            total = t_in / 1e6 * custo_milhao_entrada + (t_out or 0) / 1e6 * custo_milhao_saida
            custo = f"US$ {total:.4f} (US$ {total / docs * 1000:.2f} por mil notas)"
        tokens = f"{(t_in or 0):,} entrada, {(t_out or 0):,} saída".replace(",", ".") if t_in else "–"
        linhas_resumo.append(
            f"<tr><th>{_nome(ext)} <small>v{html.escape(versao)}</small></th><td>{docs}</td>"
            f"<td>{_barra(doc100)} {_pct(doc100)}</td><td>{_pct(acampos)}</td><td>{_pct(aitens)}</td>"
            f"<td>{nao_lidas}</td><td>{_pct(falhas)}</td><td>{tokens}</td><td>{custo or '–'}</td>"
            f"<td>{seg:.2f} s</td></tr>".replace(f"{seg:.2f} s", f"{seg:.2f} s".replace(".", ","))
        )

    linhas_var = "".join(
        f"<tr><th>{_nome(e)}</th><td>{_nome(v)}</td><td>{d}</td><td>{_barra(campos_ok)} {_pct(campos_ok)}</td>"
        f"<td>{_pct(doc100)}</td></tr>"
        for e, v, d, doc100, campos_ok in variantes
    )

    extratores = sorted({e for e, _, _ in campos})
    nomes_campos = sorted({c for _, c, _ in campos})
    mapa = {(e, c): a for e, c, a in campos}
    cab_campos = "".join(f"<th>{_nome(e)}</th>" for e in extratores)
    linhas_campos = "".join(
        f"<tr><th>{html.escape(c)}</th>" + "".join(f"<td>{_pct(mapa.get((e, c)))}</td>" for e in extratores) + "</tr>"
        for c in nomes_campos
    )

    linhas_val = "".join(
        f"<tr><th>{_nome(e)}</th><td>{pegos} de {com_erro}</td><td>{_pct(pegos / com_erro if com_erro else None)}</td>"
        f"<td>{falsos} de {corretos}</td></tr>"
        for e, com_erro, pegos, corretos, falsos in validacao
    )

    linhas_erros = "".join(
        f"<tr><td>{_nome(e)}</td><td>{html.escape(d)}</td><td>{_nome(v)}</td><td>{html.escape(c)}</td>"
        f"<td>{html.escape(str(esp))}</td><td>{html.escape(str(obt))}</td></tr>"
        for e, d, v, c, esp, obt in erros[:300]
    )

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Avaliação da extração de notas fiscais</title>
<style>
  body {{ font: 15px/1.5 system-ui, sans-serif; color: #1b1f24; background: #fafaf7; margin: 0; }}
  main {{ max-width: 72rem; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}
  h1 {{ font-size: 1.9rem; margin: 0 0 .25rem; }} h2 {{ font-size: 1.2rem; margin: 2.5rem 0 .75rem; }}
  p {{ max-width: 60ch; color: #4a5260; }}
  table {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }}
  th, td {{ padding: .45rem .6rem; border-bottom: 1px solid #e3e3dc; text-align: left; vertical-align: middle; }}
  thead th {{ font-size: .8rem; color: #59606c; font-weight: 600; }}
  tbody th {{ font-weight: 600; }} small {{ color: #7a808a; font-weight: 400; }}
  .barra {{ display: inline-block; width: 90px; height: 8px; background: #e7e7df; vertical-align: middle; margin-right: .4rem; }}
  .barra span {{ display: block; height: 100%; background: #2f6f4f; }}
  .rolagem {{ overflow-x: auto; }}
  summary {{ cursor: pointer; font-weight: 600; margin-bottom: .75rem; }}
</style></head><body><main>
<h1>Extração de notas fiscais: avaliação</h1>
<p>Gerado em {datetime.now():%d/%m/%Y %H:%M}. Cada extração é comparada com o gabarito campo a campo.
"100% certos" é a fração de notas em que todos os campos e todos os itens bateram.</p>

<h2>Resumo por extrator</h2>
<div class="rolagem"><table><thead><tr><th>Extrator</th><th>Notas</th><th>100% certas</th><th>Campos certos</th>
<th>Itens certos</th><th>Não lidas</th><th>Falhas</th><th>Tokens</th><th>Custo</th><th>Tempo (mediana)</th></tr></thead>
<tbody>{"".join(linhas_resumo)}</tbody></table></div>

<h2>Por tipo de documento</h2>
<div class="rolagem"><table><thead><tr><th>Extrator</th><th>Documento</th><th>Notas</th><th>Campos certos</th><th>100% certas</th></tr></thead>
<tbody>{linhas_var}</tbody></table></div>

<h2>Acerto por campo</h2>
<div class="rolagem"><table><thead><tr><th>Campo</th>{cab_campos}</tr></thead><tbody>{linhas_campos}</tbody></table></div>

<h2>A validação pega os erros?</h2>
<p>A validação confere dígitos verificadores, a coerência da chave de acesso com o resto da nota e se os itens somam o total,
sem olhar o gabarito. Uma nota sinalizada vai para revisão humana.</p>
<div class="rolagem"><table><thead><tr><th>Extrator</th><th>Notas com erro sinalizadas</th><th>Taxa</th><th>Notas certas sinalizadas à toa</th></tr></thead>
<tbody>{linhas_val}</tbody></table></div>

<h2>Erros de leitura</h2>
<p>Campos lidos errado em notas que o extrator conseguiu ler. As notas não lidas aparecem só na contagem do resumo.</p>
<details><summary>Ver os {len(erros)} campos com erro</summary>
<div class="rolagem"><table><thead><tr><th>Extrator</th><th>Nota</th><th>Documento</th><th>Campo</th><th>Esperado</th><th>Obtido</th></tr></thead>
<tbody>{linhas_erros or '<tr><td colspan="6">Nenhum erro.</td></tr>'}</tbody></table></div>
</details>
</main></body></html>"""
