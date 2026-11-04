"""Termos de uso e política de privacidade."""
from fastapi import APIRouter, Request

from . import pagina

rotas = APIRouter()


@rotas.get("/termos")
def termos(request: Request):
    return pagina(request, "termos.html")


@rotas.get("/privacidade")
def privacidade(request: Request):
    return pagina(request, "privacidade.html")
