"""Página do orçamento para o cliente final: ver, aprovar, pagar o sinal e pedir alteração."""
from datetime import datetime

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from .. import links
from ..db import Aceite, Orcamento, Profissional
from . import pagina, visao

rotas = APIRouter()


def _carregar(s, token):
    link = links.buscar(s, token, "cliente")
    if link is None:
        raise HTTPException(404)
    if link.orcamento_id is None:
        raise HTTPException(410)  # a conta foi apagada
    orc = s.get(Orcamento, link.orcamento_id)
    prof = s.get(Profissional, link.profissional_id)
    if orc is None or prof is None:
        raise HTTPException(410)
    return link, prof, orc


@rotas.get("/o/{token}")
def ver(request: Request, token: str, enviado: str | None = None):
    with request.app.state.Sessao() as s:
        _, prof, orc = _carregar(s, token)
        aceite = s.scalar(select(Aceite).where(Aceite.orcamento_id == orc.id, Aceite.revisao == (orc.revisao or 1)))
        return pagina(request, "orcamento.html", **visao.orcamento(prof, orc), token=token,
                      aceite=aceite, enviado=enviado == "1")


@rotas.post("/o/{token}/aprovar")
def aprovar(request: Request, token: str, nome: str = Form("")):
    nome = " ".join(nome.split())[:120]
    with request.app.state.Sessao() as s:
        _, prof, orc = _carregar(s, token)
        revisao = orc.revisao or 1
        ja = s.scalar(select(Aceite).where(Aceite.orcamento_id == orc.id, Aceite.revisao == revisao))
        if ja is None:
            if visao.situacao(orc) != "aberto":
                raise HTTPException(409, "Este orçamento não pode mais ser aprovado.")
            if not nome:
                raise HTTPException(400, "Digite seu nome para aprovar.")
            s.add(Aceite(orcamento_id=orc.id, revisao=revisao, nome=nome,
                         ip=request.client.host if request.client else None,
                         navegador=(request.headers.get("user-agent") or "")[:300]))
            orc.status, orc.aprovado_em, orc.cobrancas = "aprovado", datetime.now(), 0
            respostas = request.app.state.nucleo.aprovado_pelo_cliente(s, prof, orc, nome)
            s.commit()
            request.app.state.avisar(prof.canal_id, respostas)
    return RedirectResponse(f"/o/{token}", status_code=303)


@rotas.post("/o/{token}/alteracao")
def alteracao(request: Request, token: str, texto: str = Form(""), nome: str = Form("")):
    texto = texto.strip()[:1000]
    if not texto:
        raise HTTPException(400, "Escreva o que você quer mudar.")
    with request.app.state.Sessao() as s:
        _, prof, orc = _carregar(s, token)
        quem = " ".join(nome.split())[:120] or (orc.cliente.nome if orc.cliente else "O cliente")
        respostas = request.app.state.nucleo.pedido_do_cliente(s, prof, orc, quem, texto)
        s.commit()
        request.app.state.avisar(prof.canal_id, respostas)
    return RedirectResponse(f"/o/{token}?enviado=1", status_code=303)
