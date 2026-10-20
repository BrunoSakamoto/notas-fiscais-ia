from pathlib import Path

import pytest

from notas import gerador, lote


@pytest.fixture(scope="session")
def conjunto(tmp_path_factory) -> Path:
    """12 notas: as duas espécies (NF-e e NFC-e) nas três versões, duas de cada combinação."""
    pasta = tmp_path_factory.mktemp("notas")
    gerador.gerar_conjunto(pasta, quantidade_notas=12, semente=7)
    return pasta


@pytest.fixture
def con(conjunto, tmp_path):
    with lote.conectar(tmp_path / "r.duckdb") as c:
        lote.carregar_gabarito(c, conjunto / "gabarito.jsonl")
        yield c
