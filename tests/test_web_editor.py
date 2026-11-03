"""Editor do orçamento pelo navegador."""
import os

import pytest

from app import links
from app.db import Orcamento, Profissional
from tests.apoio_web import PEDIDO, montar


@pytest.fixture
def a(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.orcamento()
    return a


def _token(a, numero=1, canal="telegram:42"):
    url = a.nucleo.link_editor(canal, numero)
    return url.rsplit("/", 1)[1]


def _form(a, token):
    """Lê o formulário como o navegador mandaria (só os campos de item, na ordem)."""
    with a.Sessao() as s:
        link = links.buscar(s, token, "editor")
        orc = s.get(Orcamento, link.orcamento_id) if link.orcamento_id else None
        dados = a.nucleo.dados_editor(s.get(Profissional, link.profissional_id), orc)
    from app.web.editor import _formulario
    f = _formulario(dados)
    return {"cliente_nome": f["cliente"].get("nome") or "", "observacoes": f["observacoes"],
            "desconto_tipo": f["desconto_tipo"], "desconto_valor": f["desconto_valor"],
            **{c: [i[c] for i in f["itens"]] for c in ("descricao", "quantidade", "unidade", "preco", "item_preco_id")}}


def test_pagina_do_editor_abre_com_os_itens(a):
    r = a.web.get(f"/e/{_token(a)}")
    assert r.status_code == 200 and "Orçamento Nº 0001" in r.text and "Salvar e gerar PDF" in r.text


def test_editar_item_gera_revisao_e_manda_pdf_novo(a):
    token = _token(a)
    form = _form(a, token)
    form["preco"][0] = "55,00"
    total_antes = a.orc().total_centavos
    r = a.web.post(f"/e/{token}", data=form)
    assert r.status_code == 200 and "Salvo!" in r.text
    orc = a.orc()
    q = orc.itens[0].quantidade
    assert orc.revisao == 2 and orc.itens[0].preco_unit_centavos == 5500
    assert orc.total_centavos == total_antes + round(q * 5500) - round(q * 4000)
    _, respostas = a.avisos[-1]
    assert any(x.arquivo and x.arquivo.endswith(".pdf") for x in respostas)
    assert any("revisão 2" in (x.texto or "") for x in respostas)


def test_incluir_e_remover_item(a):
    token = _token(a)
    form = _form(a, token)
    for c, v in (("descricao", "Disjuntor 20A"), ("quantidade", "2"), ("unidade", "un"), ("preco", "35"),
                 ("item_preco_id", "")):
        form[c] = form[c][1:] + [v]  # tira o 1º item e põe um novo
    a.web.post(f"/e/{token}", data=form)
    descricoes = [i.descricao for i in a.orc().itens]
    assert "Disjuntor 20A" in descricoes and len(descricoes) == len(form["descricao"])


@pytest.mark.parametrize("campo, valor, erro", [
    ("preco", "abc", "Preço inválido no item 1"),
    ("quantidade", "0", "Quantidade precisa ser maior que zero"),
    ("quantidade", "-2", "Quantidade precisa ser maior que zero"),
    ("descricao", "x" * 5000, "Descrição muito longa (máx. 200)"),
])
def test_valores_invalidos_voltam_com_erro(a, campo, valor, erro):
    token = _token(a)
    form = _form(a, token)
    form[campo][0] = valor
    r = a.web.post(f"/e/{token}", data=form)
    assert r.status_code == 422 and erro in r.text
    assert a.orc().revisao == 1 and a.avisos == []


def test_sem_itens_nao_salva(a):
    token = _token(a)
    form = _form(a, token)
    for c in ("descricao", "quantidade", "unidade", "preco", "item_preco_id"):
        form[c] = []
    r = a.web.post(f"/e/{token}", data=form)
    assert r.status_code == 422 and "O orçamento precisa ter pelo menos um item" in r.text


def test_emoji_na_descricao_nao_quebra_o_pdf(a):
    token = _token(a)
    form = _form(a, token)
    form["descricao"][0] = "Tomada 🔌 nova"
    a.web.post(f"/e/{token}", data=form)
    orc = a.orc()
    assert orc.revisao == 2 and os.path.exists(orc.pdf_path)


def test_link_de_outro_prestador_nao_edita(a):
    a.cadastrar("telegram:99")
    a.orcamento("telegram:99")
    token_a = _token(a)
    with a.Sessao() as s:  # adultera o link de A para apontar para o orçamento de B
        link = links.buscar(s, token_a, "editor")
        link.orcamento_id = a.orc(canal="telegram:99").id
        s.commit()
    assert a.web.get(f"/e/{token_a}").status_code == 404
    assert a.web.post(f"/e/{token_a}", data=_form_vazio()).status_code == 404
    assert a.orc(canal="telegram:99").revisao == 1


def _form_vazio():
    return {"descricao": ["x"], "quantidade": ["1"], "unidade": [""], "preco": ["1"], "item_preco_id": [""]}


def test_editar_rascunho_em_conferencia_gera_orcamento_novo(a):
    a.bot(PEDIDO)
    a.bot("120")
    rs, _ = a.bot("12,50")  # agora em conferência (CONFIRMANDO)
    assert ("🌐 Editar no navegador", "/editarweb") in rs[-1].botoes[2]
    _, t = a.bot("/editarweb")
    token = t.split("/e/")[1].split()[0]
    form = _form(a, token)
    a.web.post(f"/e/{token}", data=form)
    assert a.orc(2).numero == 2 and a.prof().estado == "OCIOSO"
    assert a.web.get(f"/e/{token}").status_code == 200  # o mesmo link passa a editar o Nº 0002


def test_editar_enviado_no_meio_de_outro_rascunho_nao_perde_o_rascunho(a):
    token = _token(a)
    a.bot(PEDIDO)  # começa outro orçamento no chat
    estado, rascunho = a.prof().estado, a.prof().rascunho
    a.web.post(f"/e/{token}", data=_form(a, token))
    assert a.orc().revisao == 2 and a.prof().estado == estado and a.prof().rascunho == rascunho
