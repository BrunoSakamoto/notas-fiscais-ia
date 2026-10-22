"""Extrator com o Gemini: envia o documento (PDF ou imagem) e pede a nota em JSON estruturado.

O esquema de saída é o próprio modelo Pydantic `Nota`, então a resposta já chega validada.
Erros temporários (limite por minuto, servidor ocupado) são repetidos, esperando o tempo que a
API pede quando ela informa. Cota do dia esgotada não adianta repetir: o lote para ali.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from ..modelo import Nota
from . import LoteInterrompido, Resultado

NOME = "gemini"
# Mude a versão sempre que mudar o prompt: o cache guarda resultados por versão.
VERSAO = "1"
MODELO_PADRAO = os.getenv("GEMINI_MODELO", "gemini-3.8-flash")

PROMPT = """Você recebe uma nota fiscal brasileira: um DANFE de NF-e (folha A4) ou um cupom de NFC-e.
Extraia os campos pedidos no esquema, seguindo estas regras:
- chave_acesso: os 44 dígitos, só números, sem espaços.
- emitente_cnpj e destinatario_documento: só os caracteres, sem pontos, barras ou traços.
- numero e serie: como números inteiros, sem zeros à esquerda.
- data_emissao: AAAA-MM-DD.
- valores e quantidades: números com ponto decimal (1.234,56 vira 1234.56).
- itens: todos, na ordem em que aparecem, com a descrição exatamente como impressa.
- Se o consumidor não foi identificado, destinatario_documento é nulo.
- Se um campo não está legível, deixe nulo. Não invente nem calcule valores que não estão impressos."""

_MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
_TEMPORARIOS = {429, 500, 502, 503, 504}


class SemChave(RuntimeError):
    pass


class CotaEsgotada(LoteInterrompido):
    pass


def _detalhes(erro) -> list[dict]:
    corpo = erro.details if isinstance(erro.details, dict) else {}
    return (corpo.get("error") or {}).get("details") or []


def _cota_diaria(erro) -> str | None:
    """O 429 do Gemini diz qual cota estourou; as diárias têm "PerDay" no quotaId."""
    for detalhe in _detalhes(erro):
        for violacao in detalhe.get("violations") or []:
            cota = violacao.get("quotaId", "")
            if "PerDay" in cota:
                limite = violacao.get("quotaValue")
                return f"{cota} (limite {limite})" if limite else cota
    return None


def _espera(erro, tentativa: int) -> float:
    """Usa o retryDelay que a API manda ("36s"); sem ele, espera crescente.

    Modelo sobrecarregado (503) espera bem mais: no plano gratuito cada tentativa conta na cota
    do dia, e repetir depois de 2 s quase sempre bate na mesma sobrecarga.
    """
    for detalhe in _detalhes(erro):
        atraso = re.fullmatch(r"([\d.]+)s", str(detalhe.get("retryDelay", "")))
        if atraso:
            return min(120.0, float(atraso.group(1)) + 1)
    if erro.code == 503:
        return float(min(120, 30 * tentativa))
    return float(min(60, 2**tentativa))


def criar_cliente():
    if not os.getenv("GEMINI_API_KEY"):
        raise SemChave(
            "Defina GEMINI_API_KEY (crie a chave em aistudio.google.com e coloque no arquivo .env)."
        )
    from google import genai

    return genai.Client()


def extrair(caminho: Path, cliente, modelo: str = MODELO_PADRAO, tentativas: int = 5) -> Resultado:
    from google.genai import errors, types

    parte = types.Part.from_bytes(data=caminho.read_bytes(), mime_type=_MIME[caminho.suffix.lower()])
    config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
        response_json_schema=Nota.model_json_schema(),
    )
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = cliente.models.generate_content(model=modelo, contents=[parte, PROMPT], config=config)
            break
        except errors.APIError as erro:
            if erro.code == 429 and (cota := _cota_diaria(erro)):
                raise CotaEsgotada(
                    f"Cota diária do Gemini esgotada: {cota}. Rode de novo depois que ela renovar; "
                    "só os documentos que faltam serão enviados."
                ) from erro
            if erro.code not in _TEMPORARIOS or tentativa == tentativas:
                raise
            time.sleep(_espera(erro, tentativa))

    uso = resposta.usage_metadata
    return Resultado(
        nota=Nota.model_validate_json(resposta.text),
        tokens_entrada=getattr(uso, "prompt_token_count", 0) or 0,
        tokens_saida=getattr(uso, "candidates_token_count", 0) or 0,
    )
