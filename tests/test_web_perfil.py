"""Perfil e tabela de preços pelo navegador."""
from datetime import datetime, timedelta

import pytest

from app import links
from tests.apoio_web import montar


@pytest.fixture
def a(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    _, t = a.bot("/perfilweb")
    a.token = t.split("/p/")[1].split()[0]
    return a


def _form(a, **mudar):
    prof = a.prof()
    with a.Sessao() as s:
        itens = sorted(s.get(type(prof), prof.id).itens_preco, key=lambda i: i.id)
        tabela = [(str(i.id), i.descricao, i.unidade or "", i.tipo or "servico", f"{i.preco_centavos / 100:.2f}".replace(".", ","))
                  for i in itens]
    form = {"nome": prof.nome, "profissao": prof.profissao or "", "telefone": "", "cidade": prof.cidade or "",
            "pagamento": "", "pix": prof.pix_chave or "", "sinal": "", "modelo": "moderno", "cor": "azul",
            "condicoes": "", "item_id": [t[0] for t in tabela], "item_descricao": [t[1] for t in tabela],
            "item_unidade": [t[2] for t in tabela], "item_tipo": [t[3] for t in tabela], "item_preco": [t[4] for t in tabela]}
    form.update(mudar)
    return form


def test_perfil_tem_botao_para_o_navegador(a):
    rs, _ = a.bot("/perfil")
    assert ("🌐 Editar tudo no navegador", "/perfilweb") in rs[0].botoes[0]
    assert a.web.get(f"/p/{a.token}").status_code == 200


def test_salvar_perfil_completo(a):
    r = a.web.post(f"/p/{a.token}", data=_form(a, nome="Elétrica Silva", cidade="Realeza - PR", sinal="30",
                                               cor="verde", modelo="simples", pagamento="Pix ou cartão",
                                               condicoes="Garantia: 90 dias\nPrazo: 2 dias"))
    assert r.status_code == 200 and "Salvo!" in r.text
    p = a.prof()
    assert (p.nome, p.cidade, p.sinal_percentual, p.cor_pdf, p.modelo_pdf, p.pagamento_padrao) == (
        "Elétrica Silva", "Realeza - PR", 30, "verde", "simples", "Pix ou cartão")
    assert p.condicoes_padrao == [{"rotulo": "Garantia", "texto": "90 dias"}, {"rotulo": "Prazo", "texto": "2 dias"}]


def test_pix_ambigua_volta_com_erro(a):
    r = a.web.post(f"/p/{a.token}", data=_form(a, pix="46999990000"))
    assert r.status_code == 422 and "podem ser CPF ou celular" in r.text
    assert a.prof().pix_chave == "52998224725"  # nada mudou


@pytest.mark.parametrize("sinal", ["150", "-5", "abc"])
def test_sinal_fora_de_0_a_100_e_recusado(a, sinal):
    r = a.web.post(f"/p/{a.token}", data=_form(a, sinal=sinal))
    assert r.status_code == 422 and "O sinal precisa ser de 0 a 100%" in r.text


def test_editar_incluir_e_remover_item_da_tabela(a):
    form = _form(a)
    primeiro = form["item_id"][0]
    form["item_preco"][1] = "130"
    form["item_tipo"][1] = "peca"
    form["item_remover"] = [primeiro]
    for campo, valor in (("item_id", ""), ("item_descricao", "Disjuntor 20A"), ("item_unidade", "un"),
                         ("item_tipo", "peca"), ("item_preco", "35")):
        form[campo] = form[campo] + [valor]
    a.web.post(f"/p/{a.token}", data=form)
    with a.Sessao() as s:
        prof = s.get(type(a.prof()), a.prof().id)
        itens = {i.descricao: (i.preco_centavos, i.tipo) for i in prof.itens_preco}
    assert len(itens) == 2 and itens["Disjuntor 20A"] == (3500, "peca")
    assert (13000, "peca") in itens.values()


def test_preco_invalido_na_tabela_nao_salva_nada(a):
    form = _form(a, nome="Outro Nome")
    form["item_preco"][0] = "dez reais"
    r = a.web.post(f"/p/{a.token}", data=form)
    assert r.status_code == 422 and "Preço inválido" in r.text and a.prof().nome == "Victor Elétrica"


def test_token_de_perfil_vencido_da_404(a, monkeypatch):
    monkeypatch.setattr(links, "agora", lambda: datetime.now() + timedelta(days=8))
    assert a.web.get(f"/p/{a.token}").status_code == 404
