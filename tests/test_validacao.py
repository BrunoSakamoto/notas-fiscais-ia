from datetime import date

from notas.documentos import montar_chave
from notas.modelo import Item, Nota
from notas.validacao import validar

CNPJ = "11222333000181"


def _nota(**mudancas) -> Nota:
    base = Nota(
        tipo="NFE", chave_acesso=montar_chave("35", "2610", CNPJ, "55", 1, 1234, "12345678"),
        numero=1234, serie=1, data_emissao=date(2026, 10, 5), emitente_nome="X", emitente_cnpj=CNPJ,
        destinatario_documento="11144477735", valor_total=30.0,
        itens=[Item(descricao="A", quantidade=2, valor_unitario=10.0, valor_total=20.0),
               Item(descricao="B", quantidade=1, valor_unitario=10.0, valor_total=10.0)],
    )
    return base.model_copy(update=mudancas)


def test_nota_correta_nao_tem_problemas():
    assert validar(_nota()) == []


def test_numero_lido_errado_contradiz_a_chave():
    assert "número diferente do que está na chave" in validar(_nota(numero=1284))


def test_cnpj_com_digito_trocado():
    problemas = validar(_nota(emitente_cnpj="11222333000191"))
    assert "CNPJ do emitente inválido" in problemas
    assert "CNPJ do emitente diferente do que está na chave" in problemas


def test_total_que_nao_fecha_com_os_itens():
    assert any("soma dos itens" in p for p in validar(_nota(valor_total=33.0)))


def test_mes_da_emissao_contradiz_a_chave():
    assert "mês de emissão diferente do que está na chave" in validar(_nota(data_emissao=date(2026, 11, 5)))


def test_campo_obrigatorio_ausente():
    assert "chave_acesso ausente" in validar(_nota(chave_acesso=None))
