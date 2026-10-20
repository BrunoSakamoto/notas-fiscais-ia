"""Extrator com o Gemini: envia o documento (PDF ou imagem) e pede a nota em JSON estruturado.

O esquema de saída é o próprio modelo Pydantic `Nota`, então a resposta já chega validada.
Erros temporários (limite de requisições, servidor ocupado) são repetidos com espera crescente.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from ..modelo import Nota
from . import Resultado

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
            if erro.code not in _TEMPORARIOS or tentativa == tentativas:
                raise
            time.sleep(min(60, 2**tentativa))

    uso = resposta.usage_metadata
    return Resultado(
        nota=Nota.model_validate_json(resposta.text),
        tokens_entrada=getattr(uso, "prompt_token_count", 0) or 0,
        tokens_saida=getattr(uso, "candidates_token_count", 0) or 0,
    )
