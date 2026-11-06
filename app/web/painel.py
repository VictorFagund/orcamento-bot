"""Painel do profissional: o mês em números, os orçamentos com filtro e busca, ações rápidas e planilha.

Só o profissional tem o link. As ações (aprovado, recusado, recebi) rodam os mesmos comandos do chat, e as respostas
(recibo incluso) também vão para o chat.
"""
import csv
import io
import logging
import re
import unicodedata
from datetime import date, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import select

from .. import calculo, links
from ..db import Orcamento, Profissional
from . import pagina, visao

log = logging.getLogger(__name__)
rotas = APIRouter()

FILTROS = {"todos": "Todos", "abertos": "Em aberto", "areceber": "A receber", "pagos": "Pagos",
           "recusados": "Recusados"}
ROTULO_SITUACAO = {"aberto": "Em aberto", "vencido": "Vencido", "aprovado": "Aprovado", "pago": "Pago",
                   "recusado": "Recusado"}
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


def _norm(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower().strip()


def _carregar(s, token):
    link = links.buscar(s, token, "painel")
    prof = s.get(Profissional, link.profissional_id) if link else None
    if prof is None:
        raise HTTPException(404)
    return prof


def _orcamentos(s, prof):
    return s.scalars(select(Orcamento).where(Orcamento.profissional_id == prof.id)
                     .order_by(Orcamento.numero.desc())).all()


def _mes(texto: str | None) -> date:
    try:
        ano, mes = (int(x) for x in (texto or "").split("-"))
        return date(ano, mes, 1)
    except ValueError:
        hoje = date.today()
        return date(hoje.year, hoje.month, 1)


def _vizinho(mes: date, passo: int) -> date:
    n = mes.year * 12 + mes.month - 1 + passo
    return date(n // 12, n % 12 + 1, 1)


def _no_mes(quando: datetime | None, mes: date) -> bool:
    return quando is not None and (quando.year, quando.month) == (mes.year, mes.month)


def _passa(orc, filtro: str, busca: str) -> bool:
    sit = visao.situacao(orc)
    if filtro == "abertos" and sit not in ("aberto", "vencido"):
        return False
    if filtro == "areceber" and not (orc.status == "aprovado" and orc.saldo_centavos > 0):
        return False
    if filtro == "pagos" and sit != "pago":
        return False
    if filtro == "recusados" and sit != "recusado":
        return False
    alvo = _norm(busca)
    if alvo:
        numero = re.fullmatch(r"(?:n[o.]?\s*)?#?\s*(\d+)", alvo)  # "3", "0003", "nº 3", "#3"
        if numero:
            return int(numero.group(1)) == orc.numero
        return alvo in _norm(orc.cliente.nome if orc.cliente else "")
    return True


def numeros(orcs, mes: date) -> dict:
    """O mês em números. 'A receber' é o saldo de tudo que já foi aprovado, de qualquer mês."""
    do_mes = [o for o in orcs if _no_mes(o.criado_em, mes)]
    fechados = [o for o in do_mes if o.status in ("aprovado", "pago")]
    recebido = sum(p.valor_centavos for o in orcs for p in o.pagamentos if _no_mes(p.recebido_em, mes))
    a_receber = [o for o in orcs if o.status == "aprovado" and o.saldo_centavos > 0]
    por_cliente: dict[str, int] = {}
    for o in orcs:
        if o.cliente and o.recebido_centavos:
            por_cliente[o.cliente.nome] = por_cliente.get(o.cliente.nome, 0) + o.recebido_centavos
    return {
        "orcados": len(do_mes), "orcado_valor": calculo.reais(sum(o.total_centavos for o in do_mes)),
        "fechados": len(fechados), "fechado_valor": calculo.reais(sum(o.total_centavos for o in fechados)),
        "taxa": round(100 * len(fechados) / len(do_mes)) if do_mes else None,
        "recebido": calculo.reais(recebido),
        "a_receber": calculo.reais(sum(o.saldo_centavos for o in a_receber)), "a_receber_n": len(a_receber),
        "clientes": [(nome, calculo.reais(v)) for nome, v in sorted(por_cliente.items(), key=lambda x: -x[1])[:3]],
    }


def _linha(s, prof, orc) -> dict:
    sit = visao.situacao(orc)
    return {"numero": orc.numero, "n4": f"{orc.numero:04d}", "cliente": orc.cliente.nome if orc.cliente else None,
            "data": f"{orc.criado_em:%d/%m}", "total": calculo.reais(orc.total_centavos),
            "situacao": sit, "rotulo": ROTULO_SITUACAO[sit],
            "recebido": calculo.reais(orc.recebido_centavos) if orc.recebido_centavos else None,
            "falta": calculo.reais(orc.saldo_centavos) if orc.recebido_centavos and orc.saldo_centavos else None,
            "link_cliente": links.url(links.criar(s, prof, "cliente", orc))}


@rotas.get("/d/{token}")
def ver(request: Request, token: str, mes: str | None = None, f: str = "todos", q: str = "", msg: str = ""):
    filtro = f if f in FILTROS else "todos"
    mes_ = _mes(mes)
    with request.app.state.Sessao() as s:
        prof = _carregar(s, token)
        orcs = _orcamentos(s, prof)
        lista = [_linha(s, prof, o) for o in orcs if _passa(o, filtro, q)]
        s.commit()  # links do cliente criados agora para orçamentos antigos
        hoje = date.today()
        url = lambda **kw: f"/d/{token}?" + urlencode({"mes": f"{mes_:%Y-%m}", "f": filtro, "q": q, **kw})
        return pagina(request, "painel.html", **visao.cores(prof), prof=prof, token=token, n=numeros(orcs, mes_),
                      lista=lista, total_orcs=len(orcs), filtro=filtro, filtros=FILTROS, q=q, msg=msg[:300],
                      mes_nome=f"{MESES[mes_.month - 1]} de {mes_.year}", mes=f"{mes_:%Y-%m}",
                      anterior=url(mes=f"{_vizinho(mes_, -1):%Y-%m}"),
                      proximo=url(mes=f"{_vizinho(mes_, 1):%Y-%m}") if mes_ < date(hoje.year, hoje.month, 1) else None,
                      url_filtro=lambda chave: url(f=chave))


@rotas.post("/d/{token}/acao")
async def acao(request: Request, token: str):
    form = await request.form()
    numero, tipo, valor = str(form.get("numero") or ""), form.get("acao"), str(form.get("valor") or "").strip()
    volta = {k: str(form.get(k) or "") for k in ("mes", "f", "q")}
    with request.app.state.Sessao() as s:
        prof = _carregar(s, token)
        existe = numero.isdigit() and s.scalar(select(Orcamento.id).where(
            Orcamento.profissional_id == prof.id, Orcamento.numero == int(numero)))
        prof_id = prof.id
    if not existe or tipo not in ("aprovado", "recusado", "pago", "parcial"):
        raise HTTPException(400, "Ação inválida")
    if tipo == "parcial":
        centavos = calculo.ler_valor(valor)
        if not centavos or centavos <= 0:
            msg = "Digite o valor que recebeu, por exemplo 300 ou 150,50."
            return RedirectResponse(f"/d/{token}?" + urlencode({**volta, "msg": msg}), status_code=303)
        comando = f"/pago {numero} {calculo.valor_curto(centavos)}"
    else:
        comando = f"/{tipo} {numero}"
    canal, respostas = request.app.state.nucleo.acao_painel(prof_id, comando)
    try:
        request.app.state.avisar(canal, respostas)
    except Exception:
        log.exception("Não consegui avisar no chat a ação do painel")
    texto = next((r.texto for r in respostas if r.texto), "Feito.")
    msg = texto.split("\nO recibo está aí")[0]
    if any(r.arquivo for r in respostas):
        msg += " O recibo foi para o seu chat."
    return RedirectResponse(f"/d/{token}?" + urlencode({**volta, "msg": msg}), status_code=303)


@rotas.get("/d/{token}/pdf/{numero}")
def baixar_pdf(request: Request, token: str, numero: int):
    with request.app.state.Sessao() as s:
        prof = _carregar(s, token)
        existe = s.scalar(select(Orcamento.id).where(Orcamento.profissional_id == prof.id, Orcamento.numero == numero))
        prof_id = prof.id
    if not existe:
        raise HTTPException(404)
    _, respostas = request.app.state.nucleo.acao_painel(prof_id, f"/pdf {numero}")
    caminho = next((r.arquivo for r in respostas if r.arquivo), None)
    if not caminho:
        raise HTTPException(404)
    return FileResponse(caminho, media_type="application/pdf", filename=f"orcamento_{numero:04d}.pdf",
                        content_disposition_type="inline")


@rotas.get("/d/{token}/planilha.csv")
def planilha(request: Request, token: str):
    with request.app.state.Sessao() as s:
        prof = _carregar(s, token)
        orcs = _orcamentos(s, prof)
        saida = io.StringIO()
        w = csv.writer(saida, delimiter=";")  # ; e vírgula decimal: abre direto no Excel em português
        w.writerow(["Número", "Data", "Cliente", "Telefone do cliente", "Situação", "Total", "Recebido", "Falta",
                    "Aprovado em", "Validade"])
        dinheiro = lambda c: f"{c / 100:.2f}".replace(".", ",")
        for o in sorted(orcs, key=lambda o: o.numero):
            w.writerow([o.numero, f"{o.criado_em:%d/%m/%Y}", o.cliente.nome if o.cliente else "",
                        (o.cliente.telefone or "") if o.cliente else "", ROTULO_SITUACAO[visao.situacao(o)],
                        dinheiro(o.total_centavos), dinheiro(o.recebido_centavos), dinheiro(o.saldo_centavos),
                        f"{o.aprovado_em:%d/%m/%Y}" if o.aprovado_em else "", f"{o.validade:%d/%m/%Y}"])
    return Response("﻿" + saida.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="orcamentos_{date.today():%Y-%m-%d}.csv"'})
