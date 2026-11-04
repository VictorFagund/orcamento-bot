"""Eventos de uso e métricas do beta."""
from datetime import date, datetime, timedelta

import metricas
from app import eventos
from app.db import Evento
from tests.apoio_web import montar


def _ev(s, prof, tipo, quando, **dados):
    s.add(Evento(profissional_id=prof, tipo=tipo, dados=dados or None, criado_em=quando))


def test_metricas_com_dados_sinteticos(tmp_path):
    a = montar(tmp_path)
    hoje = datetime.now().replace(hour=12)
    with a.Sessao() as s:
        for p in (1, 2, 3):
            _ev(s, p, "cadastro_concluido", hoje - timedelta(days=15))
        _ev(s, 1, "orcamento_gerado", hoje - timedelta(days=14), orcamento_id=10, revisao=1)
        _ev(s, 1, "orcamento_gerado", hoje - timedelta(days=2), orcamento_id=11, revisao=1)
        _ev(s, 2, "correcao", hoje - timedelta(days=3))
        _ev(s, 2, "orcamento_gerado", hoje - timedelta(days=3), orcamento_id=20, revisao=1)
        _ev(s, 2, "orcamento_gerado", hoje - timedelta(days=1), orcamento_id=20, revisao=2)  # revisão não conta
        _ev(s, 1, "link_aberto", hoje - timedelta(days=1), orcamento_id=11)
        _ev(s, 1, "aprovado_link", hoje - timedelta(days=1), orcamento_id=11)
        s.commit()
    m = metricas.calcular(a.Sessao, date.today() - timedelta(days=30), date.today())
    assert (m["cadastrados"], m["ativados"], m["retidos"]) == (3, 2, 1)
    assert (m["ativacao_pct"], m["retencao_pct"]) == (66.7, 33.3)
    assert m["orcamentos"] == 3 and m["orcamentos_por_prestador"] == 1.5
    assert m["sem_correcao_pct"] == 66.7  # 2 de 3 saíram sem correção
    assert (m["links_abertos_pct"], m["aprovados_link_pct"]) == (33.3, 33.3)


def test_fluxo_real_registra_os_eventos(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    respostas, _ = a.orcamento()
    token = next(r.texto for r in respostas if r.texto and "/o/" in r.texto).split("/o/")[1].split()[0]
    a.web.get(f"/o/{token}")
    a.web.post(f"/o/{token}/aprovar", data={"nome": "João"})
    with a.Sessao() as s:
        tipos = [e.tipo for e in s.query(Evento).order_by(Evento.id)]
    assert tipos[:2] == ["cadastro_concluido", "orcamento_gerado"]
    assert "link_aberto" in tipos and "aprovado_link" in tipos


def test_link_aberto_varias_vezes_no_dia_conta_uma(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    respostas, _ = a.orcamento()
    token = next(r.texto for r in respostas if r.texto and "/o/" in r.texto).split("/o/")[1].split()[0]
    for _ in range(3):
        a.web.get(f"/o/{token}")
    with a.Sessao() as s:
        assert s.query(Evento).filter_by(tipo="link_aberto").count() == 1


def test_apagar_conta_remove_eventos(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.orcamento()
    a.bot("/apagarconta confirmar")
    with a.Sessao() as s:
        assert s.query(Evento).count() == 0


def test_falha_da_ia_vira_evento(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.nucleo.ia.interpretar = lambda *x, **k: (_ for _ in ()).throw(ConnectionError("caiu"))
    _, t = a.bot("Orçamento pra alguém")
    assert "Ops" in t
    with a.Sessao() as s:
        ev = s.query(Evento).filter_by(tipo="falha_ia").one()
        assert ev.dados == {"erro": "ConnectionError"}


def test_evento_desconhecido_e_recusado(tmp_path):
    a = montar(tmp_path)
    with a.Sessao() as s:
        try:
            eventos.registrar(s, 1, "qualquer_coisa")
        except ValueError:
            return
    raise AssertionError("deveria recusar")
