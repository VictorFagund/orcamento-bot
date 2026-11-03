"""Testa a montagem das chamadas à IA real, com o cliente da OpenAI simulado (sem rede)."""
import json
from types import SimpleNamespace

import pytest

from app import config
from app.ia import IAOpenAI


class ClienteFalso:
    def __init__(self, resposta: dict):
        self.chamadas = []
        self.resposta = resposta
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._transcrever))

    def _create(self, **kw):
        self.chamadas.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.resposta)))])

    def _transcrever(self, **kw):
        self.chamadas.append(kw)
        return SimpleNamespace(text="  trocar duas tomadas  ")


@pytest.fixture
def ia():
    ia = IAOpenAI(api_key="teste")
    ia.cliente = ClienteFalso({"intencao": "orcamento", "itens": [{"descricao": "Tomada", "quantidade": 2}]})
    return ia


TABELA = [{"id": 1, "descricao": "Troca de tomada", "unidade": "un", "sinonimos": ["tomada"]}]
RASCUNHO = {"cliente": {"nome": "Maria"}, "observacoes": None, "desconto": None,
            "itens": [{"descricao": "Troca de tomada", "quantidade": 2, "unidade": "un", "item_preco_id": 1,
                       "preco_centavos": 4000, "origem": "tabela"},
                      {"descricao": "Fiação", "quantidade": 1, "unidade": "m", "item_preco_id": None,
                       "preco_centavos": 30000, "origem": "informado"}]}


def test_precos_da_tabela_nunca_vao_para_a_ia(ia):
    ia.interpretar("são 3 tomadas", TABELA, rascunho=RASCUNHO)
    enviado = ia.cliente.chamadas[0]["messages"][1]["content"]
    assert "4000" not in enviado and "40.0" not in enviado and '"preco_centavos"' not in enviado
    assert '"preco_informado": 300.0' in enviado  # só o valor que o próprio profissional falou


def test_modo_schema_e_modo_compativel(ia, monkeypatch):
    monkeypatch.setattr(config, "IA_MODO_JSON", "schema")
    ia.interpretar("oi", TABELA)
    assert ia.cliente.chamadas[-1]["response_format"]["type"] == "json_schema"
    monkeypatch.setattr(config, "IA_MODO_JSON", "objeto")
    ia.interpretar("oi", TABELA)
    chamada = ia.cliente.chamadas[-1]
    assert chamada["response_format"] == {"type": "json_object"} and "JSON Schema" in chamada["messages"][0]["content"]


def test_resposta_incompleta_e_completada(ia):
    r = ia.interpretar("x", TABELA)
    assert r["cliente"] == {"nome": None, "endereco": None, "telefone": None} and r["valor_pago"] is None
    assert r["itens"][0]["item_preco_id"] is None and r["itens"][0]["quantidade"] == 2


def test_transcricao_em_portugues(ia):
    assert ia.transcrever(b"audio") == "trocar duas tomadas"
    assert ia.cliente.chamadas[-1]["language"] == "pt"


def test_sem_chave_avisa_claramente():
    with pytest.raises(RuntimeError, match="IA_API_KEY"):
        IAOpenAI(api_key="")
