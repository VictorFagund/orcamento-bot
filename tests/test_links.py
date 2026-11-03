"""Links secretos do site."""
from datetime import datetime, timedelta

from app import links
from tests.apoio_web import montar


def test_link_cliente_e_reaproveitado(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.orcamento()
    with a.Sessao() as s:
        prof, orc = a.prof(), a.orc()
        l1 = links.criar(s, prof, "cliente", orc)
        l2 = links.criar(s, prof, "cliente", orc)
        assert l1.token == l2.token and l1.expira_em is None
        assert links.url(l1).endswith(f"/o/{l1.token}")


def test_link_editor_expira_em_7_dias(tmp_path, monkeypatch):
    a = montar(tmp_path)
    a.cadastrar()
    with a.Sessao() as s:
        link = links.criar(s, a.prof(), "editor")
        restante = link.expira_em - datetime.now()
        assert timedelta(days=6.9) < restante < timedelta(days=7.1)
        assert links.buscar(s, link.token, "editor") is not None
        monkeypatch.setattr(links, "agora", lambda: datetime.now() + timedelta(days=8))
        assert links.buscar(s, link.token, "editor") is None


def test_buscar_com_tipo_errado_devolve_none(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    with a.Sessao() as s:
        link = links.criar(s, a.prof(), "perfil")
        assert links.buscar(s, link.token, "editor") is None
        assert links.buscar(s, "naoexiste", "perfil") is None


def test_token_invalido_mostra_pagina_amigavel(tmp_path):
    r = montar(tmp_path).web.get("/e/naoexiste")
    assert r.status_code == 404 and "Link inválido ou vencido" in r.text
