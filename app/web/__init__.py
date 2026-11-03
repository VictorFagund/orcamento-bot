"""Site do produto: páginas abertas por links secretos (orçamento do cliente, editor, perfil).

Roda num processo à parte (web.py), com o mesmo banco e o mesmo núcleo do bot. Para avisar o profissional no chat,
recebe a função `avisar(canal_id, respostas)`.
"""
import os
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import config

PASTA = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(PASTA, "templates"))
templates.env.globals["produto"] = config.NOME_PRODUTO


def pagina(request: Request, nome: str, status: int = 200, **contexto) -> HTMLResponse:
    return templates.TemplateResponse(request, nome, contexto, status_code=status)


def criar_app(Sessao, nucleo, avisar: Callable) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.Sessao, app.state.nucleo, app.state.avisar = Sessao, nucleo, avisar

    @app.exception_handler(StarletteHTTPException)
    async def erro(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return pagina(request, "invalido.html", 404)
        if exc.status_code == 410:
            return pagina(request, "indisponivel.html", 410)
        return pagina(request, "invalido.html", exc.status_code, mensagem=str(exc.detail))

    @app.get("/saude")
    def saude():
        return {"ok": True}

    for modulo in ("cliente", "editor", "perfil", "legal"):
        try:
            rotas = __import__(f"{__name__}.{modulo}", fromlist=["rotas"])
        except ModuleNotFoundError as e:
            if e.name != f"{__name__}.{modulo}":
                raise
            continue  # módulo ainda não existe nesta versão
        app.include_router(rotas.rotas)
    return app
