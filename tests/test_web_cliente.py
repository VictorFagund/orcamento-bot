"""Link do orçamento para o cliente: ver, aprovar, sinal no Pix, pedir alteração."""
from datetime import date, timedelta

import pytest

from app import config, links
from app.calculo import reais, valor_curto, valor_sinal
from app.db import Aceite, Orcamento
from tests.apoio_web import montar


@pytest.fixture
def a(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.respostas_pdf, _ = a.orcamento()
    with a.Sessao() as s:
        a.token = links.criar(s, a.prof(), "cliente", a.orc()).token
        s.commit()
    return a


def test_valor_do_sinal():
    assert valor_sinal(66750, None) == 33375 and valor_sinal(66750, 0) == 66750 and valor_sinal(1000, 30) == 300
    assert valor_curto(24000) == "240" and valor_curto(33375) == "333,75"


def test_pdf_gerado_traz_link_do_cliente(a):
    textos = " ".join(r.texto or "" for r in a.respostas_pdf)
    assert config.BASE_URL + "/o/" + a.token in textos


def test_pagina_mostra_itens_total_e_botao_aprovar(a):
    r = a.web.get(f"/o/{a.token}")
    total = reais(a.orc().total_centavos)
    assert r.status_code == 200 and "Nº 0001" in r.text and total in r.text and "Aprovar orçamento" in r.text


def test_aprovar_grava_aceite_e_avisa_o_prestador(a):
    r = a.web.post(f"/o/{a.token}/aprovar", data={"nome": "João"}, follow_redirects=False)
    assert r.status_code == 303
    orc = a.orc()
    assert orc.status == "aprovado"
    with a.Sessao() as s:
        aceite = s.query(Aceite).one()
        assert (aceite.nome, aceite.revisao) == ("João", 1)
    assert len(a.avisos) == 1
    canal, respostas = a.avisos[0]
    sinal = valor_curto(valor_sinal(orc.total_centavos, None))
    assert canal == "telegram:42" and "João aprovou o orçamento Nº 0001" in respostas[0].texto
    assert respostas[0].botoes == [[("💰 Já recebi o sinal", f"/pago 1 {sinal}")]]


def test_depois_de_aprovar_mostra_pix_do_sinal(a):
    a.web.post(f"/o/{a.token}/aprovar", data={"nome": "João"})
    r = a.web.get(f"/o/{a.token}")
    sinal = reais(valor_sinal(a.orc().total_centavos, None))
    assert f"Sinal de 50%: {sinal}" in r.text and "000201" in r.text and "Aprovar orçamento" not in r.text


def test_aprovar_duas_vezes_nao_duplica(a):
    a.web.post(f"/o/{a.token}/aprovar", data={"nome": "João"})
    a.web.post(f"/o/{a.token}/aprovar", data={"nome": "João"})
    with a.Sessao() as s:
        assert s.query(Aceite).count() == 1
    assert len(a.avisos) == 1


def test_revisao_nova_aparece_no_mesmo_link(a):
    a.bot("/editar 1 o cliente quer pagar 650")
    a.bot("ok")
    r = a.web.get(f"/o/{a.token}")
    assert "rev. 2" in r.text and "R$ 650,00" in r.text
    a.web.post(f"/o/{a.token}/aprovar", data={"nome": "Maria"})
    with a.Sessao() as s:
        assert s.query(Aceite).one().revisao == 2


def test_pedido_de_alteracao_abre_a_revisao(a):
    r = a.web.post(f"/o/{a.token}/alteracao", data={"texto": "Consegue fazer por 700?", "nome": "Maria"},
                   follow_redirects=False)
    assert r.status_code == 303 and "enviado=1" in r.headers["location"]
    _, respostas = a.avisos[0]
    textos = "\n".join(x.texto or "" for x in respostas)
    assert 'Maria pediu uma alteração no orçamento Nº 0001' in textos and "Revisão do orçamento Nº 0001" in textos


def test_pedido_de_alteracao_com_prestador_ocupado_so_avisa(a):
    a.bot("Orçamento pra Dona Maria, trocar 6 tomadas, 2 chuveiros e 15 metros de fiação")  # outro em andamento
    a.web.post(f"/o/{a.token}/alteracao", data={"texto": "Consegue fazer por 700?"})
    _, respostas = a.avisos[0]
    assert len(respostas) == 1 and respostas[0].botoes == [[("✏️ Abrir o orçamento para mudar", "/editar 1")]]


@pytest.mark.parametrize("estado, frase", [("recusado", "foi recusado"), ("pago", "já está pago"),
                                           ("vencido", "venceu em")])
def test_recusado_pago_ou_vencido_nao_deixa_aprovar(a, estado, frase):
    with a.Sessao() as s:
        orc = s.get(Orcamento, a.orc().id)
        if estado == "vencido":
            orc.validade = date.today() - timedelta(days=1)
        else:
            orc.status = estado
        s.commit()
    r = a.web.get(f"/o/{a.token}")
    assert frase in r.text and "Aprovar orçamento" not in r.text
    assert a.web.post(f"/o/{a.token}/aprovar", data={"nome": "João"}).status_code == 409
