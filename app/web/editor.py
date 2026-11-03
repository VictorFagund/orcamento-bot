"""Editor do orçamento pelo navegador (só o profissional tem o link)."""
from fastapi import APIRouter, HTTPException, Request

from .. import links
from ..calculo import qtd_fmt, valor_curto
from ..db import Orcamento, Profissional
from . import pagina, visao

rotas = APIRouter()


def _carregar(s, token):
    link = links.buscar(s, token, "editor")
    if link is None:
        raise HTTPException(404)
    prof = s.get(Profissional, link.profissional_id)
    orc = s.get(Orcamento, link.orcamento_id) if link.orcamento_id else None
    if prof is None or (link.orcamento_id and (orc is None or orc.profissional_id != prof.id)):
        raise HTTPException(404)
    return link, prof, orc


def _formulario(dados: dict) -> dict:
    """Rascunho -> valores de texto para os campos do formulário."""
    d = dados.get("desconto") or {}
    return {"cliente": dados.get("cliente") or {}, "observacoes": dados.get("observacoes") or "",
            "condicoes": "\n".join(f"{c['rotulo']}: {c['texto']}" for c in dados.get("condicoes") or []),
            "itens": [{"descricao": i["descricao"], "quantidade": qtd_fmt(i["quantidade"]), "unidade": i.get("unidade") or "",
                       "preco": valor_curto(i["preco_centavos"] or 0), "item_preco_id": i.get("item_preco_id") or "",
                       "tipo": i.get("tipo") or "servico"}
                      for i in dados.get("itens") or []],
            "desconto_tipo": d.get("tipo") if d.get("tipo") in ("valor", "percentual") else "",
            "desconto_valor": (qtd_fmt(d["valor"]) if d.get("tipo") == "percentual" else
                               valor_curto(round(d["valor"] * 100)) if d.get("tipo") == "valor" else "")}


@rotas.get("/e/{token}")
def ver(request: Request, token: str):
    with request.app.state.Sessao() as s:
        link, prof, orc = _carregar(s, token)
        if orc is None and (prof.estado != "CONFIRMANDO" or not prof.rascunho):
            raise HTTPException(404, "Esse rascunho já foi gerado ou descartado. Peça um link novo com /editarweb.")
        dados = request.app.state.nucleo.dados_editor(prof, orc)
        titulo = f"Orçamento Nº {orc.numero:04d}" if orc else "Orçamento em conferência"
        return pagina(request, "editor.html", **visao.cores(prof), titulo=titulo, form=_formulario(dados), erros=[])


@rotas.post("/e/{token}")
async def salvar(request: Request, token: str):
    f = await request.form()
    campos = ("descricao", "quantidade", "unidade", "preco", "item_preco_id", "tipo")
    colunas = {c: f.getlist(c) for c in campos}
    itens = [{c: (colunas[c][i] if i < len(colunas[c]) else "") for c in campos} for i in range(len(colunas["descricao"]))]
    dados = {"cliente": {"nome": f.get("cliente_nome"), "endereco": f.get("cliente_endereco"),
                         "telefone": f.get("cliente_telefone")},
             "itens": itens, "observacoes": f.get("observacoes"),
             "condicoes": [dict(zip(("rotulo", "texto"), (p.strip() for p in linha.split(":", 1))))
                           for linha in (f.get("condicoes") or "").splitlines() if ":" in linha],
             "desconto": {"tipo": f.get("desconto_tipo") or None, "valor": f.get("desconto_valor")}}
    with request.app.state.Sessao() as s:
        link, prof, orc = _carregar(s, token)
        cores, titulo = visao.cores(prof), (f"Orçamento Nº {orc.numero:04d}" if orc else "Orçamento em conferência")
        prof_id, orc_id, canal = prof.id, (orc.id if orc else None), prof.canal_id
    erros, respostas, novo_id = request.app.state.nucleo.salvar_edicao(prof_id, orc_id, dados)
    if erros:
        form = {"cliente": dados["cliente"], "observacoes": dados["observacoes"] or "", "itens": itens,
                "condicoes": f.get("condicoes") or "",
                "desconto_tipo": dados["desconto"]["tipo"] or "", "desconto_valor": dados["desconto"]["valor"] or ""}
        return pagina(request, "editor.html", 422, **cores, titulo=titulo, form=form, erros=erros)
    with request.app.state.Sessao() as s:  # o link do rascunho passa a apontar para o orçamento gerado
        link = links.buscar(s, token, "editor")
        link.orcamento_id = novo_id
        s.commit()
    request.app.state.avisar(canal, respostas)
    return pagina(request, "editor_salvo.html", **cores, token=token)
