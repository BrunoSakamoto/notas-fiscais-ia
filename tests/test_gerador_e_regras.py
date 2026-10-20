import json

from notas.extratores import regras
from notas.modelo import Nota
from notas.validacao import validar


def _registros(conjunto):
    return [json.loads(linha) for linha in (conjunto / "gabarito.jsonl").read_text().splitlines()]


def test_todas_as_combinacoes_de_especie_e_versao(conjunto):
    combinacoes = {(r["nota"]["tipo"], r["variante"]) for r in _registros(conjunto)}
    assert combinacoes == {(t, v) for t in ("NFE", "NFCE") for v in ("pdf", "foto_boa", "foto_ruim")}


def test_gabarito_passa_na_propria_validacao(conjunto):
    """Se o gerador produzisse nota fiscal inválida, a avaliação inteira ficaria sem sentido."""
    for r in _registros(conjunto):
        assert validar(Nota.model_validate(r["nota"])) == [], r["id"]


def test_regras_acertam_os_pdfs_e_nao_leem_fotos(conjunto):
    for r in _registros(conjunto):
        resultado = regras.extrair(conjunto / "documentos" / r["arquivo"])
        if r["variante"] == "pdf":
            assert resultado.nota == Nota.model_validate(r["nota"]), r["id"]
        else:
            assert resultado.nota == Nota() and resultado.observacoes
