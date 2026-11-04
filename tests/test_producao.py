"""Coisas de produção: banco compartilhado entre bot e site, e alertas de erro."""
import logging
import threading

from app import config
from app.avisos import AlertaTelegram
from app.db import Evento, iniciar_banco


def test_dois_processos_escrevem_sem_travar(tmp_path):
    url = f"sqlite:///{tmp_path}/compartilhado.db"
    bot, site = iniciar_banco(url), iniciar_banco(url)  # duas "conexões de processo" separadas
    erros = []

    def escrever(Sessao, prof):
        try:
            for i in range(200):
                with Sessao() as s:
                    s.add(Evento(profissional_id=prof, tipo="link_aberto", dados={"i": i}))
                    s.commit()
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    t1 = threading.Thread(target=escrever, args=(bot, 1))
    t2 = threading.Thread(target=escrever, args=(site, 2))
    t1.start(); t2.start(); t1.join(); t2.join()
    assert erros == []
    with bot() as s:
        assert s.query(Evento).count() == 400


def _registro(msg="Falha ao processar mensagem de 42"):
    try:
        raise ConnectionError("Timed out")
    except ConnectionError:
        import sys
        return logging.LogRecord("bot", logging.ERROR, __file__, 1, msg, None, sys.exc_info())


def test_alerta_repetido_e_segurado_por_10_minutos(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", "123")
    enviados, relogio = [], [1000.0]
    alerta = AlertaTelegram(enviar=enviados.append, relogio=lambda: relogio[0])
    alerta.emit(_registro())
    alerta.emit(_registro())  # mesmo erro logo em seguida: não repete
    relogio[0] += 601
    alerta.emit(_registro())
    alerta.emit(_registro("Outro erro"))
    assert len(enviados) == 3 and "ConnectionError: Timed out" in enviados[0]


def test_sem_admin_chat_id_nao_envia(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", "")
    enviados = []
    AlertaTelegram(enviar=enviados.append).emit(_registro())
    assert enviados == []


def test_alerta_que_falha_nao_derruba_nada(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_CHAT_ID", "123")

    def quebra(_):
        raise RuntimeError("sem internet")
    AlertaTelegram(enviar=quebra).emit(_registro())  # não levanta
