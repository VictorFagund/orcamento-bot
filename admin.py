"""Administração do beta pelo terminal.

  python admin.py listar                        prestadores, plano e orçamentos no mês
  python admin.py plano telegram:12345 piloto   muda o plano (gratis | piloto)
"""
import sys
from datetime import datetime

from app import config
from app.db import Profissional, iniciar_banco
from app.nucleo import Nucleo

PLANOS = ("gratis", "piloto")


def listar(Sessao) -> list[tuple]:
    nucleo = Nucleo(Sessao, ia=None)
    with Sessao() as s:
        return [(p.canal_id, p.nome or "-", p.plano or "gratis", nucleo._orcamentos_no_mes(s, p, datetime.now()))
                for p in s.query(Profissional).order_by(Profissional.id)]


def mudar_plano(Sessao, canal_id: str, plano: str) -> str:
    if plano not in PLANOS:
        return f"Plano desconhecido: {plano}. Use: {', '.join(PLANOS)}"
    with Sessao() as s:
        prof = s.query(Profissional).filter_by(canal_id=canal_id).one_or_none()
        if prof is None:
            return f"Não achei {canal_id}. Veja os canais com: python admin.py listar"
        prof.plano = plano
        s.commit()
        return f"{prof.nome or canal_id}: plano {plano}"


def main(argv):
    Sessao = iniciar_banco(config.DATABASE_URL)
    if argv[:1] == ["listar"]:
        for canal, nome, plano, mes in listar(Sessao):
            print(f"{canal:<24} {nome:<30} {plano:<8} {mes} no mês")
    elif argv[:1] == ["plano"] and len(argv) == 3:
        print(mudar_plano(Sessao, argv[1], argv[2]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
