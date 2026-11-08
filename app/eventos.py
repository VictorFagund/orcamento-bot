"""Eventos de uso do beta, para medir ativação, retenção e o que as pessoas fazem com o produto."""
from datetime import datetime

from .db import Evento

TIPOS = {"cadastro_concluido", "orcamento_gerado", "correcao", "editor_aberto", "editor_salvo", "link_aberto",
         "aprovado_link", "alteracao_link", "limite_atingido", "falha_ia", "roteado", "nao_entendido", "parcelas", "duvida"}


def registrar(s, prof_id: int, tipo: str, **dados) -> None:
    if tipo not in TIPOS:
        raise ValueError(f"evento desconhecido: {tipo}")
    s.add(Evento(profissional_id=prof_id, tipo=tipo, dados=dados or None, criado_em=datetime.now()))
