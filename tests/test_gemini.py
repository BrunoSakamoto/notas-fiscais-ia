"""O extrator Gemini com um cliente falso: testa o pedido montado e o tratamento de erros, sem rede."""

from types import SimpleNamespace

import pytest
from google.genai import errors

from notas.extratores import gemini
from notas.modelo import Nota

RESPOSTA = Nota(tipo="NFCE", numero=10, valor_total=5.5).model_dump_json()


class ClienteFalso:
    def __init__(self, falhas: list | None = None):
        self.falhas = list(falhas or [])
        self.chamadas = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.chamadas.append(SimpleNamespace(model=model, contents=contents, config=config))
        if self.falhas:
            falha = self.falhas.pop(0)
            codigo, detalhes = falha if isinstance(falha, tuple) else (falha, [])
            corpo = {"code": codigo, "message": "falha simulada", "details": detalhes}
            raise errors.ClientError(codigo, {"error": corpo})
        uso = SimpleNamespace(prompt_token_count=1200, candidates_token_count=180)
        return SimpleNamespace(text=RESPOSTA, usage_metadata=uso)


ESPERAS: list[float] = []


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch):
    ESPERAS.clear()
    monkeypatch.setattr(gemini, "esperar", ESPERAS.append)


def _cota(quota_id: str, atraso: str = "36s"):
    """Formato do 429 do Gemini: QuotaFailure com a cota estourada e RetryInfo com a espera."""
    return (429, [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": quota_id, "quotaValue": "20"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": atraso},
    ])


def test_pedido_leva_arquivo_esquema_e_temperatura_zero(tmp_path):
    arquivo = tmp_path / "n.jpg"
    arquivo.write_bytes(b"\xff\xd8 imagem")
    cliente = ClienteFalso()

    resultado = gemini.extrair(arquivo, cliente, modelo="modelo-teste")

    chamada = cliente.chamadas[0]
    assert chamada.model == "modelo-teste"
    assert chamada.contents[0].inline_data.mime_type == "image/jpeg"
    assert chamada.contents[1] == gemini.PROMPT
    assert chamada.config.response_mime_type == "application/json"
    assert chamada.config.response_json_schema == Nota.model_json_schema()
    assert chamada.config.temperature == 0
    assert resultado.nota.numero == 10 and resultado.tokens_entrada == 1200 and resultado.tokens_saida == 180


def test_limite_de_requisicoes_e_repetido(tmp_path):
    arquivo = tmp_path / "n.pdf"
    arquivo.write_bytes(b"%PDF-1.4")
    cliente = ClienteFalso(falhas=[429, 503])

    resultado = gemini.extrair(arquivo, cliente)

    assert len(cliente.chamadas) == 3 and resultado.nota.valor_total == 5.5
    assert ESPERAS == [2.0, 60.0]  # sobrecarga (503) espera mais que o resto


def test_erro_definitivo_nao_e_repetido(tmp_path):
    arquivo = tmp_path / "n.pdf"
    arquivo.write_bytes(b"%PDF-1.4")
    cliente = ClienteFalso(falhas=[400])

    with pytest.raises(errors.ClientError):
        gemini.extrair(arquivo, cliente)
    assert len(cliente.chamadas) == 1


def test_sem_chave_explica_o_que_fazer(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(gemini.SemChave, match="GEMINI_API_KEY"):
        gemini.criar_cliente()


def test_limite_por_minuto_espera_o_que_a_api_pede(tmp_path):
    arquivo = tmp_path / "n.pdf"
    arquivo.write_bytes(b"%PDF-1.4")
    cliente = ClienteFalso(falhas=[_cota("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "12.5s")])

    gemini.extrair(arquivo, cliente)

    assert len(cliente.chamadas) == 2 and ESPERAS == [13.5]


def test_cota_diaria_esgotada_nao_e_repetida(tmp_path):
    arquivo = tmp_path / "n.pdf"
    arquivo.write_bytes(b"%PDF-1.4")
    cliente = ClienteFalso(falhas=[_cota("GenerateRequestsPerDayPerProjectPerModel-FreeTier")])

    with pytest.raises(gemini.CotaEsgotada, match="PerDay.*limite 20"):
        gemini.extrair(arquivo, cliente)
    assert len(cliente.chamadas) == 1 and ESPERAS == []


def test_ctrl_c_acorda_a_espera_e_interrompe(tmp_path):
    from notas.extratores import INTERROMPER, LoteInterrompido, esperar

    INTERROMPER.set()
    try:
        with pytest.raises(LoteInterrompido, match="interrompido"):
            esperar(60)  # retorna na hora, sem esperar os 60 s
    finally:
        INTERROMPER.clear()


def test_cliente_tem_timeout(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "chave-falsa")
    cliente = gemini.criar_cliente()
    assert cliente._api_client._http_options.timeout == gemini.TIMEOUT_MS
