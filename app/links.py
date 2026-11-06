"""Links secretos do site. Quem tem o link tem acesso: por isso o token é longo e impossível de adivinhar."""
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select

from . import config
from .db import Link

VALIDADE_DIAS = 7  # editor e perfil; o link do cliente não expira
VALIDADE_PAINEL_DIAS = 30  # o painel é para reabrir sempre
PREFIXO = {"cliente": "o", "editor": "e", "perfil": "p", "painel": "d"}


def agora() -> datetime:
    return datetime.now()


def criar(s, prof, tipo: str, orc=None) -> Link:
    if tipo not in PREFIXO:
        raise ValueError(f"tipo de link desconhecido: {tipo}")
    if tipo == "cliente":  # um link por orçamento, o mesmo em todas as revisões
        existente = s.scalar(select(Link).where(Link.tipo == "cliente", Link.orcamento_id == orc.id))
        if existente:
            return existente
    link = Link(token=secrets.token_urlsafe(16), tipo=tipo, profissional_id=prof.id,
                orcamento_id=orc.id if orc is not None else None,
                expira_em=None if tipo == "cliente" else agora() + timedelta(
                    days=VALIDADE_PAINEL_DIAS if tipo == "painel" else VALIDADE_DIAS))
    s.add(link)
    s.flush()
    return link


def buscar(s, token: str, tipo: str) -> Link | None:
    link = s.scalar(select(Link).where(Link.token == token))
    if link is None or link.tipo != tipo:
        return None
    if link.expira_em is not None and link.expira_em < agora():
        return None
    return link


def url(link: Link) -> str:
    return f"{config.BASE_URL}/{PREFIXO[link.tipo]}/{link.token}"
