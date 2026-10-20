import pytest

from notas.documentos import chave_valida, cnpj_valido, cpf_valido, ler_chave, montar_chave


@pytest.mark.parametrize("cnpj, ok", [
    ("11.222.333/0001-81", True),
    ("11.222.333/0001-82", False),
    ("11111111111111", False),           # todos iguais passam no cálculo, mas não existem
    ("12.ABC.345/01DE-35", True),        # alfanumérico, exemplo oficial da Receita (2026)
    ("12.ABC.345/01DE-36", False),
])
def test_cnpj(cnpj, ok):
    assert cnpj_valido(cnpj) is ok


@pytest.mark.parametrize("cpf, ok", [("111.444.777-35", True), ("111.444.777-36", False), ("000.000.000-00", False)])
def test_cpf(cpf, ok):
    assert cpf_valido(cpf) is ok


def test_chave_monta_e_desmonta():
    chave = montar_chave("35", "2610", "11222333000181", "65", 2, 4321, "87654321")
    assert len(chave) == 44 and chave_valida(chave)
    partes = ler_chave(chave)
    assert (partes.cnpj, partes.modelo, partes.serie, partes.numero) == ("11222333000181", "65", 2, 4321)


def test_um_digito_trocado_invalida_a_chave():
    chave = montar_chave("35", "2610", "11222333000181", "55", 1, 99, "00000001")
    trocada = chave[:10] + str((int(chave[10]) + 1) % 10) + chave[11:]
    assert not chave_valida(trocada)
