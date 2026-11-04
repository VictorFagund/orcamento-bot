"""Termos de uso, privacidade e apagar a conta."""
import os

from app import links
from app.db import Aceite, Cliente, ItemPreco, Link, Orcamento, Profissional
from tests.apoio_web import CADASTRO, PEDIDO, montar


def test_cadastro_pede_aceite_antes_de_liberar(tmp_path):
    a = montar(tmp_path)
    for m in CADASTRO:
        rs, t = a.bot(m)
    assert "Termos de uso" in t and "/termos" in t and rs[-1].botoes == [[("✅ Li e aceito", "aceito")]]
    _, t = a.bot(PEDIDO)  # tenta pular o aceite
    assert "aceitar os termos" in t and a.prof().estado == "CADASTRO_TERMOS"
    _, t = a.bot("aceito")
    assert "Cadastro pronto" in t and a.prof().termos_aceitos_em is not None


def test_cliente_antigo_aceita_no_primeiro_orcamento(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.orcamento()
    with a.Sessao() as s:  # conta criada antes de os termos existirem
        s.query(Profissional).one().termos_aceitos_em = None
        s.commit()
    _, t = a.bot(PEDIDO)
    assert "Termos de uso" in t
    _, t = a.bot("aceito")
    assert "mandar o orçamento de novo" in t
    _, t = a.bot(PEDIDO)
    assert "ainda não está na sua tabela" in t or "Confira o orçamento" in t


def test_apagar_conta_remove_tudo_e_arquivos(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.orcamento()
    a.bot(foto=b"\xff\xd8\xff fake jpeg")
    pdf, logo = a.orc().pdf_path, a.prof().logo_path
    with a.Sessao() as s:
        links.criar(s, a.prof(), "editor", a.orc())
        s.commit()
    rs, t = a.bot("/apagarconta")
    assert "Tem certeza?" in t and rs[0].botoes == [[("🗑️ Apagar tudo", "/apagarconta confirmar")]]
    assert os.path.exists(pdf)  # sem confirmar, nada some
    _, t = a.bot("/apagarconta confirmar")
    assert "apaguei tudo" in t
    with a.Sessao() as s:
        for modelo in (Profissional, Orcamento, Cliente, ItemPreco, Aceite):
            assert s.query(modelo).count() == 0, modelo
        assert s.query(Link).filter(Link.tipo != "cliente").count() == 0
    assert not os.path.exists(pdf) and not os.path.exists(logo)


def test_link_de_conta_apagada_mostra_indisponivel(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    respostas, _ = a.orcamento()
    url = next(r.texto for r in respostas if r.texto and "/o/" in r.texto)
    token = url.split("/o/")[1].split()[0]
    a.bot("/apagarconta confirmar")
    r = a.web.get(f"/o/{token}")
    assert r.status_code == 410 and "Este orçamento não está mais disponível" in r.text


def test_paginas_de_termos_e_privacidade_abrem(tmp_path):
    a = montar(tmp_path)
    t, p = a.web.get("/termos"), a.web.get("/privacidade")
    assert t.status_code == 200 and "Termos de uso" in t.text and "/apagarconta" in t.text
    assert p.status_code == 200 and "provedor de IA" in p.text and "30 dias" in p.text


def test_depois_de_apagar_pode_comecar_de_novo(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.bot("/apagarconta confirmar")
    _, t = a.bot("/start")
    assert "qual o seu nome" in t
