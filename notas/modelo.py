"""O formato de uma nota: o mesmo para o gabarito, para o que os extratores devolvem e para o
esquema de saída estruturada pedido ao Gemini."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Item(BaseModel):
    descricao: str | None = Field(None, description="Descrição do produto como aparece na nota")
    quantidade: float | None = Field(None, description="Quantidade, com ponto decimal")
    valor_unitario: float | None = Field(None, description="Valor unitário em reais, com ponto decimal")
    valor_total: float | None = Field(None, description="Valor total do item em reais, com ponto decimal")


class Nota(BaseModel):
    """Campos extraídos de uma NF-e (DANFE) ou NFC-e (cupom). Campo ilegível fica nulo."""

    tipo: Literal["NFE", "NFCE"] | None = Field(None, description="NFE para DANFE em A4; NFCE para cupom")
    chave_acesso: str | None = Field(None, description="Chave de acesso: 44 dígitos, só números")
    numero: int | None = Field(None, description="Número da nota, sem zeros à esquerda")
    serie: int | None = Field(None, description="Série da nota")
    data_emissao: date | None = Field(None, description="Data de emissão no formato AAAA-MM-DD")
    emitente_nome: str | None = Field(None, description="Razão social do emitente")
    emitente_cnpj: str | None = Field(None, description="CNPJ do emitente: 14 caracteres, sem pontuação")
    destinatario_documento: str | None = Field(
        None, description="CPF ou CNPJ do destinatário, sem pontuação; nulo se não identificado"
    )
    valor_total: float | None = Field(None, description="Valor total da nota em reais, com ponto decimal")
    itens: list[Item] = Field(default_factory=list, description="Todos os itens, na ordem da nota")


# Os campos avaliados um a um. "itens" é avaliado à parte (quantidade e conteúdo).
CAMPOS = [
    "tipo",
    "chave_acesso",
    "numero",
    "serie",
    "data_emissao",
    "emitente_nome",
    "emitente_cnpj",
    "destinatario_documento",
    "valor_total",
]
