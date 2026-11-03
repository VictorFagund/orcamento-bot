"""Testes de robustez: o que acontece quando a IA erra, devolve lixo, cai, ou o usuário manda coisas estranhas.

A IA real VAI errar de vez em quando. O sistema precisa continuar correto (nunca cobrar errado) e nunca travar.
"""
import pytest

from app.db import ItemPreco, Orcamento, iniciar_banco
from app.nucleo import Mensagem, Nucleo


def vazio(**extra):
    base = {"intencao": "outro", "numero_orcamento": None,
            "cliente": {"nome": None, "endereco": None, "telefone": None},
            "itens": [], "precos": [], "observacoes": None,
            "desconto_percentual": None, "desconto_valor": None, "total_desejado": None, "valor_pago": None}
    return {**base, **extra}


def orcamento(itens, **extra):
    return vazio(intencao="orcamento", cliente={"nome": "Cliente Teste", "endereco": None, "telefone": None},
                 itens=itens, **extra)


def item(descricao, quantidade=1, item_preco_id=None, preco_informado=None, unidade="un"):
    return {"descricao": descricao, "quantidade": quantidade, "unidade": unidade,
            "item_preco_id": item_preco_id, "preco_informado": preco_informado}


class IAProgramada:
    """Devolve exatamente o que o teste mandar para cada mensagem (ou levanta erro)."""

    def __init__(self):
        self.respostas = {}
        self.transcricao = ""

    def transcrever(self, audio, nome_arquivo="audio.ogg"):
        if isinstance(self.transcricao, Exception):
            raise self.transcricao
        return self.transcricao

    def interpretar(self, texto, tabela, rascunho=None, contexto=""):
        r = self.respostas.get(texto, vazio())
        if isinstance(r, Exception):
            raise r
        return r(tabela) if callable(r) else r


@pytest.fixture
def ambiente(tmp_path):
    ia = IAProgramada()
    Sessao = iniciar_banco(f"sqlite:///{tmp_path}/r.db")
    nucleo = Nucleo(Sessao, ia, pasta_arquivos=str(tmp_path / "arq"))

    def enviar(texto=None, canal="t:1", **kw):
        rs = nucleo.processar(canal, Mensagem(texto=texto, **kw))
        return rs, "\n".join(r.texto for r in rs if r.texto)

    def cadastrar(canal="t:1"):
        ia.respostas["tabela"] = vazio(intencao="tabela_precos", precos=[
            {"descricao": "Troca de tomada", "unidade": "un", "preco": 40, "sinonimos": []},
            {"descricao": "Instalação de chuveiro", "unidade": "un", "preco": 120, "sinonimos": []}])
        for m in ["oi", "Prof", "Eletricista", "pular", "pular", "pular", "pular", "pular", "tabela"]:
            enviar(m, canal=canal)
        with Sessao() as s:
            return {i.descricao: i.id for i in s.query(ItemPreco).all() if i.profissional.canal_id == canal}

    enviar.ia, enviar.Sessao, enviar.cadastrar = ia, Sessao, cadastrar
    return enviar


# ---------------------------------------------------------------- IA devolvendo coisas erradas

def test_encaminhada_classificada_como_orcamento_vira_pedido_de_mudanca(ambiente):
    ids = ambiente.cadastrar()
    ambiente.ia.respostas["x"] = orcamento([item("Troca de tomada", 2, ids["Troca de tomada"])])
    ambiente("x")
    ambiente("ok")
    # o gpt-oss às vezes diz "orcamento" (sem itens) para "consegue por 600?" encaminhado pelo cliente
    ambiente.ia.respostas["[Mensagem ENCAMINHADA do cliente Maria] Consegue por 600?"] = vazio(
        intencao="orcamento", total_desejado=600)
    _, t = ambiente("Consegue por 600?", encaminhada_de="Maria")
    assert "Em qual orçamento" in t, t


def test_quantidade_em_texto_ou_invalida_nao_trava(ambiente):
    ids = ambiente.cadastrar()
    ambiente.ia.respostas["x"] = orcamento([item("Troca de tomada", "3", ids["Troca de tomada"]),
                                            item("Instalação de chuveiro", "dois", ids["Instalação de chuveiro"])])
    _, t = ambiente("x")
    assert "Ops" not in t, t
    assert "Total:" in t


def test_quantidade_negativa_ou_zero_e_ignorada(ambiente):
    ids = ambiente.cadastrar()
    ambiente.ia.respostas["x"] = orcamento([item("Troca de tomada", -5, ids["Troca de tomada"]),
                                            item("Instalação de chuveiro", 0, ids["Instalação de chuveiro"]),
                                            item("Troca de tomada", 2, ids["Troca de tomada"])])
    _, t = ambiente("x")
    assert "Total: R$ 80,00" in t


def test_preco_informado_negativo_ou_zero_nao_vira_preco(ambiente):
    ids = ambiente.cadastrar()
    ambiente.ia.respostas["x"] = orcamento([item("Troca de tomada", 2, ids["Troca de tomada"], preco_informado=-40),
                                            item("Instalação de chuveiro", 1, ids["Instalação de chuveiro"],
                                                 preco_informado=0)])
    _, t = ambiente("x")
    assert "Total: R$ 200,00" in t  # usa a tabela: 2*40 + 120


def test_id_de_item_de_outro_profissional_e_ignorado(ambiente):
    ids_a = ambiente.cadastrar("t:A")
    ambiente.cadastrar("t:B")
    # A IA (por erro) aponta para o id do item do profissional A na conversa do B
    ambiente.ia.respostas["x"] = orcamento([item("Serviço X", 1, ids_a["Troca de tomada"])])
    _, t = ambiente("x", canal="t:B")
    assert '"Serviço X" ainda não está na sua tabela' in t  # não usa o preço de outro profissional


def test_desconto_maior_que_o_total_nao_deixa_negativo(ambiente):
    ids = ambiente.cadastrar()
    ambiente.ia.respostas["x"] = orcamento([item("Troca de tomada", 1, ids["Troca de tomada"])], desconto_valor=500)
    _, t = ambiente("x")
    assert "Total: R$ 0,00" in t
    ambiente.ia.respostas["y"] = orcamento([item("Troca de tomada", 1, ids["Troca de tomada"])],
                                           desconto_percentual=150)
    ambiente("cancelar")
    _, t = ambiente("y")
    assert "Total: R$ 40,00" in t  # 150% é absurdo: ignorado


def test_resposta_da_ia_faltando_campos(ambiente):
    ids = ambiente.cadastrar()
    ambiente.ia.respostas["x"] = {"intencao": "orcamento",
                                  "itens": [{"descricao": "Troca de tomada", "item_preco_id": ids["Troca de tomada"]}]}
    _, t = ambiente("x")
    assert "Ops" not in t, t
    assert "Total: R$ 40,00" in t


def test_descricao_vazia_vira_item(ambiente):
    ambiente.cadastrar()
    ambiente.ia.respostas["x"] = orcamento([item("", 1)])
    _, t = ambiente("x")
    assert "Ops" not in t, t


def test_ia_fora_do_ar_nao_perde_o_estado(ambiente):
    ids = ambiente.cadastrar()
    ambiente.ia.respostas["x"] = orcamento([item("Troca de tomada", 2, ids["Troca de tomada"])])
    ambiente("x")  # rascunho em conferência
    ambiente.ia.respostas["corrige"] = ConnectionError("timeout")
    _, t = ambiente("corrige")
    assert "Ops" in t  # avisa o problema
    _, t = ambiente("ok")  # o rascunho continua lá
    assert "Orçamento Nº 0001 pronto" in t


def test_transcricao_vazia_ou_com_erro(ambiente):
    ambiente.cadastrar()
    ambiente.ia.transcricao = ""
    _, t = ambiente(audio=b"x")
    assert "Me mande um texto ou um áudio" in t
    ambiente.ia.transcricao = ConnectionError("falhou")
    _, t = ambiente(audio=b"x")
    assert "Ops" in t


# ---------------------------------------------------------------- usuário mandando coisas estranhas

def test_valores_digitados_estranhos_ao_perguntar_preco(ambiente):
    ambiente.cadastrar()
    ambiente.ia.respostas["x"] = orcamento([item("Serviço novo", 1)])
    ambiente("x")
    for lixo in ["", "abc", "-50", "0", "????"]:
        _, t = ambiente(lixo or " ")
        assert "Ops" not in t, (lixo, t)
    _, t = ambiente("R$ 1.234,56")
    assert "Total: R$ 1.234,56" in t


def test_mensagem_gigante_e_emoji(ambiente):
    _, t = ambiente("oi")
    _, t = ambiente("🔌⚡ Elétrica do Zé " + "x" * 5000)
    assert "Ops" not in t, t
    with ambiente.Sessao() as s:
        from app.db import Profissional
        assert len(s.query(Profissional).one().nome) <= 120


def test_comandos_com_argumentos_errados(ambiente):
    ambiente.cadastrar()
    for cmd in ["/pago", "/pago abc", "/pago 999", "/editar", "/editar 999", "/pdf -1", "/recibo 1",
                "/cobrar 1", "/retorno", "/retorno 99 6", "/retorno 1 abc", "/remover 0", "/adiar x",
                "/aprovado", "/comandoquenaoexiste", "/pix 123"]:
        _, t = ambiente(cmd)
        assert "Ops" not in t, (cmd, t)


def test_profissionais_isolados(ambiente):
    ids_a = ambiente.cadastrar("t:A")
    ids_b = ambiente.cadastrar("t:B")
    ambiente.ia.respostas["xa"] = orcamento([item("Troca de tomada", 1, ids_a["Troca de tomada"])])
    ambiente.ia.respostas["xb"] = orcamento([item("Troca de tomada", 1, ids_b["Troca de tomada"])])
    ambiente("xa", canal="t:A")
    _, ta = ambiente("ok", canal="t:A")
    ambiente("xb", canal="t:B")
    _, tb = ambiente("ok", canal="t:B")
    assert "Nº 0001" in ta and "Nº 0001" in tb  # numeração independente
    _, t = ambiente("/pago 1", canal="t:B")
    from app.db import Profissional
    with ambiente.Sessao() as s:
        canal = {p.id: p.canal_id for p in s.query(Profissional).all()}
        status = {canal[o.profissional_id]: o.status for o in s.query(Orcamento).all()}
    assert status == {"t:A": "enviado", "t:B": "pago"}  # B não mexe no orçamento de A


def test_pagamento_maior_que_o_saldo_avisa(ambiente):
    ids = ambiente.cadastrar()
    ambiente.ia.respostas["x"] = orcamento([item("Troca de tomada", 1, ids["Troca de tomada"])])
    ambiente("x")
    ambiente("ok")
    _, t = ambiente("/pago 1 100")
    assert "maior que o saldo" in t and "quitado" in t


@pytest.mark.parametrize("entrada,esperado", [
    (3, 3), ("3", 3), ("2,5", 2.5), ("duas", 2), ("meia dúzia", 6), ("Três", 3), (None, 1), ("", 1),
    ("umas tantas", 1), (0, 0), (-2, -2),
])
def test_quantidade(entrada, esperado):
    from app.calculo import quantidade
    assert quantidade(entrada) == esperado


@pytest.mark.parametrize("texto", ["-50", "- 50", "R$ -10"])
def test_valor_negativo_digitado_e_recusado(texto):
    from app.calculo import ler_valor
    assert ler_valor(texto) is None
