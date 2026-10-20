import json

from notas import avaliacao, lote
from notas.extratores import Resultado
from notas.modelo import Nota


def _gabarito(con) -> dict[str, Nota]:
    linhas = con.execute("select documento, nota from gabarito").fetchall()
    return {doc: Nota.model_validate_json(n) for doc, n in linhas}


def test_cache_nao_repete_documento_ja_extraido(con, conjunto):
    chamadas = []

    def extrator(caminho):
        chamadas.append(caminho.name)
        return Resultado(Nota())

    lote.processar(con, conjunto / "documentos", "falso", "1", extrator)
    lote.processar(con, conjunto / "documentos", "falso", "1", extrator)
    assert len(chamadas) == 12

    lote.processar(con, conjunto / "documentos", "falso", "2", extrator)  # versão nova do prompt
    assert len(chamadas) == 24


def test_erro_num_documento_nao_para_o_lote_e_e_refeito_depois(con, conjunto):
    gabarito = _gabarito(con)
    arquivos = dict(con.execute("select arquivo, documento from gabarito").fetchall())
    tentativas = {"n": 0}

    def instavel(caminho):
        tentativas["n"] += 1
        if caminho.name == "nota-003.jpg" and tentativas["n"] < 13:
            raise TimeoutError("rede caiu")
        return Resultado(gabarito[arquivos[caminho.name]])

    primeira = lote.processar(con, conjunto / "documentos", "instavel", "1", instavel)
    assert primeira["erros"] == 1 and primeira["processados"] == 11
    segunda = lote.processar(con, conjunto / "documentos", "instavel", "1", instavel)
    assert segunda == {"processados": 1, "erros": 0, "ja_feitos": 11}


def test_extrator_perfeito_tem_100_por_cento(con, conjunto):
    gabarito = _gabarito(con)
    arquivos = dict(con.execute("select arquivo, documento from gabarito").fetchall())
    lote.processar(con, conjunto / "documentos", "perfeito", "1", lambda c: Resultado(gabarito[arquivos[c.name]]))

    avaliacao.avaliar(con)

    _, _, docs, doc100, campos, itens, _, nao_lidas, *_ = con.execute(avaliacao.RESUMO).fetchone()
    assert (docs, doc100, campos, itens, nao_lidas) == (12, 1.0, 1.0, 1.0, 0)
    assert con.execute(avaliacao.VALIDACAO).fetchone() == ("perfeito", 0, 0, 12, 0)


def test_validacao_pega_cnpj_lido_errado(con, conjunto):
    gabarito = _gabarito(con)
    arquivos = dict(con.execute("select arquivo, documento from gabarito").fetchall())

    def erra_um_digito(caminho):
        nota = gabarito[arquivos[caminho.name]]
        cnpj = nota.emitente_cnpj
        return Resultado(nota.model_copy(update={"emitente_cnpj": cnpj[:5] + str((int(cnpj[5]) + 1) % 10) + cnpj[6:]}))

    lote.processar(con, conjunto / "documentos", "erra", "1", erra_um_digito)
    avaliacao.avaliar(con)

    _, com_erro, pegos, _, falsos = con.execute(avaliacao.VALIDACAO).fetchone()
    assert com_erro == 12 and pegos == 12 and falsos == 0
    problemas = json.loads(con.execute("select problemas from extracoes limit 1").fetchone()[0])
    assert "CNPJ do emitente inválido" in problemas


def test_nota_nao_lida_nao_ganha_ponto_nem_em_campo_vazio(con, conjunto):
    lote.processar(con, conjunto / "documentos", "cego", "1", lambda c: Resultado(Nota()))
    avaliacao.avaliar(con)

    _, _, docs, doc100, campos, *_resto = con.execute(avaliacao.RESUMO).fetchone()
    assert campos == 0.0 and doc100 == 0.0
    assert con.execute("select count(*) from avaliacao_documentos where not lida").fetchone()[0] == 12
