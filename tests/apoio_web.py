"""Ambiente comum dos testes do site: banco temporário, núcleo com IA simulada, um profissional cadastrado."""
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db import Orcamento, Profissional, iniciar_banco
from app.nucleo import Mensagem, Nucleo
from app.web import criar_app
from tests.test_fluxo import IAFalsa

CANAL = "telegram:42"
CADASTRO = ["oi", "Victor Elétrica", "Eletricista", "pular", "Realeza", "pular", "CPF 529.982.247-25", "pular",
            "tomada 40, chuveiro 120"]
PEDIDO = "Orçamento pra Dona Maria, trocar 6 tomadas, 2 chuveiros e 15 metros de fiação"


def montar(tmp_path, ia=None):
    Sessao = iniciar_banco(f"sqlite:///{tmp_path}/web.db")
    nucleo = Nucleo(Sessao, ia or IAFalsa(), pasta_arquivos=str(tmp_path / "arq"))
    avisos = []
    cliente = TestClient(criar_app(Sessao, nucleo, lambda canal, respostas: avisos.append((canal, respostas))))

    def bot(texto=None, canal=CANAL, **kw):
        rs = nucleo.processar(canal, Mensagem(texto=texto, **kw))
        return rs, "\n".join(r.texto for r in rs if r.texto)

    def cadastrar(canal=CANAL):
        for m in CADASTRO:
            bot(m, canal=canal)
        return bot("aceito", canal=canal)  # aceite dos termos (a partir da Task 7); antes disso, é ignorado

    def orcamento(canal=CANAL):
        bot(PEDIDO, canal=canal)
        bot("120", canal=canal)
        bot("12,50", canal=canal)
        return bot("ok", canal=canal)

    def prof(canal=CANAL):
        with Sessao() as s:
            return s.query(Profissional).filter_by(canal_id=canal).one()

    def orc(numero=1, canal=CANAL):
        with Sessao() as s:
            p = s.query(Profissional).filter_by(canal_id=canal).one()
            o = s.query(Orcamento).filter_by(profissional_id=p.id, numero=numero).one()
            _ = (o.itens, o.cliente, o.pagamentos)
            return o

    return SimpleNamespace(Sessao=Sessao, nucleo=nucleo, web=cliente, avisos=avisos, bot=bot,
                           cadastrar=cadastrar, orcamento=orcamento, prof=prof, orc=orc)
