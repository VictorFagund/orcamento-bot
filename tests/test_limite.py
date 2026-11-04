"""Limite gratuito de orçamentos novos por mês e plano piloto."""
from datetime import datetime

import admin
from app import config
from app.db import Orcamento
from tests.apoio_web import PEDIDO, montar


def _encher(a, n):
    """Cria n orçamentos já gerados no mês, direto no banco (rápido)."""
    with a.Sessao() as s:
        prof = s.get(type(a.prof()), a.prof().id)
        for i in range(n):
            s.add(Orcamento(profissional_id=prof.id, numero=100 + i, total_centavos=1000, validade=datetime.now().date()))
        s.commit()


def test_decimo_sexto_orcamento_do_mes_e_bloqueado(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    _encher(a, config.LIMITE_GRATIS)
    _, t = a.bot(PEDIDO)
    assert "15 orçamentos grátis deste mês" in t and a.prof().estado == "OCIOSO"


def test_revisao_nao_conta_no_limite(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.orcamento()
    _encher(a, config.LIMITE_GRATIS - 1)  # 1 real + 14 = limite
    _, t = a.bot("/editar 1 o cliente quer pagar 650")
    assert "Revisão do orçamento Nº 0001" in t  # edição continua liberada
    a.bot("ok")
    _, t = a.bot(PEDIDO)
    assert "orçamentos grátis deste mês" in t


def test_plano_piloto_nao_tem_limite(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    _encher(a, config.LIMITE_GRATIS + 5)
    assert "piloto" in admin.mudar_plano(a.Sessao, "telegram:42", "piloto")
    _, t = a.bot(PEDIDO)
    assert "grátis" not in t
    assert ("telegram:42", "Victor Elétrica", "piloto", config.LIMITE_GRATIS + 5) in admin.listar(a.Sessao)


def test_limite_renova_no_mes_seguinte(tmp_path, monkeypatch):
    a = montar(tmp_path)
    a.cadastrar()
    _encher(a, config.LIMITE_GRATIS)
    agora = datetime.now()
    proximo = (agora.replace(day=28) + __import__("datetime").timedelta(days=5)).replace(day=1, hour=9)
    monkeypatch.setattr(type(a.nucleo), "_agora", staticmethod(lambda: proximo))
    _, t = a.bot(PEDIDO)
    assert "grátis" not in t


def test_admin_plano_invalido(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    assert "Plano desconhecido" in admin.mudar_plano(a.Sessao, "telegram:42", "vip")
    assert "Não achei" in admin.mudar_plano(a.Sessao, "telegram:1", "piloto")
