"""Perfil, condições, visual do PDF e tabela de preços pelo navegador (só o profissional tem o link)."""
from fastapi import APIRouter, HTTPException, Request

from .. import links, pdf
from ..calculo import valor_curto
from ..db import Profissional
from . import pagina, visao

rotas = APIRouter()


def _carregar(s, token):
    link = links.buscar(s, token, "perfil")
    prof = s.get(Profissional, link.profissional_id) if link else None
    if prof is None:
        raise HTTPException(404)
    return prof


def _formulario(prof) -> dict:
    return {"nome": prof.nome or "", "profissao": prof.profissao or "", "telefone": prof.telefone or "",
            "cidade": prof.cidade or "", "pagamento": prof.pagamento_padrao or "", "pix": prof.pix_chave or "",
            "sinal": "" if prof.sinal_percentual is None else str(prof.sinal_percentual),
            "modelo": prof.modelo_pdf or pdf.MODELO_PADRAO, "cor": prof.cor_pdf or pdf.COR_PADRAO,
            "condicoes": "\n".join(f"{c['rotulo']}: {c['texto']}" for c in prof.condicoes_padrao or []),
            "tabela": [{"id": i.id, "descricao": i.descricao, "unidade": i.unidade or "", "tipo": i.tipo or "servico",
                        "preco": valor_curto(i.preco_centavos)} for i in sorted(prof.itens_preco, key=lambda i: i.id)]}


def _contexto(prof, form, erros, salvo=False):
    return dict(**visao.cores(prof), form=form, erros=erros, salvo=salvo,
                modelos=[(k, v[0]) for k, v in pdf.MODELOS.items()], cores=[(k, v[0]) for k, v in pdf.CORES.items()])


@rotas.get("/p/{token}")
def ver(request: Request, token: str):
    with request.app.state.Sessao() as s:
        prof = _carregar(s, token)
        return pagina(request, "perfil.html", **_contexto(prof, _formulario(prof), []))


@rotas.post("/p/{token}")
async def salvar(request: Request, token: str):
    f = await request.form()
    ids, descr, unid, tipos, precos = (f.getlist(c) for c in ("item_id", "item_descricao", "item_unidade", "item_tipo",
                                                               "item_preco"))
    remover = set(f.getlist("item_remover"))
    tabela = [{"id": ids[i], "descricao": descr[i], "unidade": unid[i] if i < len(unid) else "",
               "tipo": tipos[i] if i < len(tipos) else "servico", "preco": precos[i] if i < len(precos) else "",
               "remover": ids[i] in remover and ids[i] != ""} for i in range(len(ids))]
    condicoes = [dict(zip(("rotulo", "texto"), (p.strip() for p in linha.split(":", 1))))
                 for linha in (f.get("condicoes") or "").splitlines() if ":" in linha]
    dados = {k: f.get(k) for k in ("nome", "profissao", "telefone", "cidade", "pagamento", "pix", "sinal", "modelo", "cor")}
    dados.update(tabela=tabela, condicoes=condicoes)
    with request.app.state.Sessao() as s:
        prof_id = _carregar(s, token).id
    erros = request.app.state.nucleo.salvar_perfil(prof_id, dados)
    with request.app.state.Sessao() as s:
        prof = _carregar(s, token)
        if erros:
            form = {**dados, "condicoes": f.get("condicoes") or "", "tabela": tabela}
            return pagina(request, "perfil.html", 422, **_contexto(prof, form, erros))
        return pagina(request, "perfil.html", **_contexto(prof, _formulario(prof), [], salvo=True))
