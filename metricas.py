"""Números do beta.

  python metricas.py            últimos 30 dias
  python metricas.py --dias 21
"""
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app import config
from app.db import Evento, iniciar_banco


def _pct(parte, todo) -> float:
    return round(100 * parte / todo, 1) if todo else 0.0


def calcular(Sessao, desde: date, ate: date) -> dict:
    inicio, fim = datetime.combine(desde, datetime.min.time()), datetime.combine(ate, datetime.max.time())
    with Sessao() as s:
        evs = s.scalars(select(Evento).where(Evento.criado_em >= inicio, Evento.criado_em <= fim)
                        .order_by(Evento.criado_em, Evento.id)).all()
    cadastrados = {e.profissional_id for e in evs if e.tipo == "cadastro_concluido"}
    gerados = [e for e in evs if e.tipo == "orcamento_gerado" and (e.dados or {}).get("revisao", 1) == 1]
    semanas = defaultdict(set)
    for e in gerados:
        semanas[e.profissional_id].add(e.criado_em.isocalendar()[:2])
    ativados = {p for p in cadastrados if semanas.get(p)}
    retidos = {p for p in ativados if len(semanas[p]) >= 2}

    # correções entre o início do rascunho e o "ok": zera a cada orçamento gerado do mesmo profissional
    correcoes, sem_correcao = defaultdict(int), 0
    for e in evs:
        if e.tipo == "correcao":
            correcoes[e.profissional_id] += 1
        elif e.tipo == "orcamento_gerado":
            if (e.dados or {}).get("revisao", 1) == 1 and correcoes[e.profissional_id] == 0:
                sem_correcao += 1
            correcoes[e.profissional_id] = 0

    ids_gerados = {(e.dados or {}).get("orcamento_id") for e in gerados}
    abertos = {(e.dados or {}).get("orcamento_id") for e in evs if e.tipo == "link_aberto"} & ids_gerados
    aprovados = {(e.dados or {}).get("orcamento_id") for e in evs if e.tipo == "aprovado_link"} & ids_gerados
    return {
        "cadastrados": len(cadastrados), "ativados": len(ativados), "ativacao_pct": _pct(len(ativados), len(cadastrados)),
        "retidos": len(retidos), "retencao_pct": _pct(len(retidos), len(cadastrados)),
        "orcamentos": len(gerados),
        "orcamentos_por_prestador": round(len(gerados) / len(ativados), 1) if ativados else 0.0,
        "sem_correcao_pct": _pct(sem_correcao, len(gerados)),
        "links_abertos_pct": _pct(len(abertos), len(gerados)), "aprovados_link_pct": _pct(len(aprovados), len(gerados)),
        "limite_atingido": sum(1 for e in evs if e.tipo == "limite_atingido"),
        "falhas_ia": sum(1 for e in evs if e.tipo == "falha_ia"),
    }


ROTULOS = [("cadastrados", "Cadastros concluídos"), ("ativacao_pct", "Fizeram o 1º orçamento (%)"),
           ("retencao_pct", "Voltaram em outra semana (%)"), ("orcamentos", "Orçamentos novos"),
           ("orcamentos_por_prestador", "Orçamentos por prestador ativo"), ("sem_correcao_pct", "Saíram sem correção (%)"),
           ("links_abertos_pct", "Cliente abriu o link (%)"), ("aprovados_link_pct", "Aprovados pelo link (%)"),
           ("limite_atingido", "Bateram no limite grátis"), ("falhas_ia", "Falhas da IA")]


def main(argv):
    dias = int(argv[argv.index("--dias") + 1]) if "--dias" in argv else 30
    ate = date.today()
    m = calcular(iniciar_banco(config.DATABASE_URL), ate - timedelta(days=dias), ate)
    print(f"Últimos {dias} dias")
    for chave, rotulo in ROTULOS:
        print(f"  {rotulo:<34} {m[chave]}")


if __name__ == "__main__":
    main(sys.argv[1:])
