"""Garante que a bateria de avaliação da IA (avaliar_ia.py) mede certo, antes de usá-la com a IA real."""
import json

import avaliar_ia

CASOS = json.load(open(avaliar_ia.CASOS, encoding="utf-8"))


class IAPerfeita:
    """Responde exatamente o esperado de cada caso."""

    def interpretar(self, texto, tabela, rascunho=None, contexto=""):
        e = next(c["esperado"] for c in CASOS["casos"] if c["mensagem"] == texto)
        itens = []
        for i in e.get("itens", []):
            ids = i["id"] if isinstance(i["id"], list) else [i["id"]]
            itens.append({"descricao": i.get("contem") or "item", "quantidade": i["qtd"], "unidade": None,
                          "item_preco_id": next((x for x in ids if x is not None), None),
                          "preco_informado": i.get("preco")})
        return {"intencao": e.get("intencao", "tabela_precos"), "numero_orcamento": e.get("numero_orcamento"),
                "cliente": {"nome": e.get("cliente_nome"), "endereco": e.get("endereco"), "telefone": e.get("telefone")},
                "itens": itens, "precos": [{"descricao": p["contem"], "unidade": None, "preco": p["preco"],
                                            "sinonimos": []} for p in e.get("precos", [])],
                "observacoes": "obs" if e.get("observacoes") else None,
                "desconto_percentual": e.get("desconto_percentual"), "desconto_valor": e.get("desconto_valor"),
                "total_desejado": e.get("total_desejado"), "valor_pago": e.get("valor_pago")}


class IAMuda:
    def interpretar(self, *a, **k):
        return {"intencao": "outro", "itens": [], "precos": []}


class IAInventaPreco(IAPerfeita):
    def interpretar(self, *a, **k):
        r = super().interpretar(*a, **k)
        for i in r["itens"]:
            i["preco_informado"] = i["preco_informado"] or 99
        return r


class IAQueCai:
    def interpretar(self, *a, **k):
        raise TimeoutError("sem resposta")


def test_ia_perfeita_tira_100():
    r = avaliar_ia.rodar(IAPerfeita(), CASOS, saida=lambda *_: None)["resumo"]
    assert r["casos_ok"] == r["casos"] == len(CASOS["casos"]) and r["precos_inventados"] == 0


def test_ia_que_nao_entende_nada_vai_mal():
    r = avaliar_ia.rodar(IAMuda(), CASOS, saida=lambda *_: None)["resumo"]
    assert r["casos_ok"] <= 2  # só acerta os casos em que a resposta certa é "outro"


def test_preco_inventado_e_detectado():
    r = avaliar_ia.rodar(IAInventaPreco(), CASOS, saida=lambda *_: None)["resumo"]
    assert r["precos_inventados"] >= 10


def test_falha_da_ia_vira_erro_no_relatorio_sem_parar():
    r = avaliar_ia.rodar(IAQueCai(), CASOS, saida=lambda *_: None)
    assert r["resumo"]["casos_ok"] == 0 and "TimeoutError" in r["resultados"][0]["falhas"][0]
