"""Pagamento dividido em parcelas ou etapas: entrada + entrega, 3x mensal, entrada de 500 + o resto em 2x...

O plano guarda só o que o profissional disse: percentual, valor fixo ou "o resto", e quando vence (data ou um
momento como "na entrega"). Os valores em reais saem do total do orçamento na hora, então se o orçamento mudar o
plano acompanha. Os pagamentos registrados quitam as parcelas em ordem.

Formato guardado em Orcamento.parcelas: [{"rotulo", "pct", "valor", "vencimento", "quando"}, ...]
  pct/valor: só um dos dois; nenhum dos dois = parte do resto (dividido igualmente entre as parcelas "resto").
"""
import re
import unicodedata
from calendar import monthrange
from datetime import date, timedelta

from .calculo import reais

MAXIMO = 24


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    return " ".join(t.replace(",", " ").split())


def mais_meses(d: date, n: int) -> date:
    mes = d.month - 1 + n
    ano, mes = d.year + mes // 12, mes % 12 + 1
    return date(ano, mes, min(d.day, monthrange(ano, mes)[1]))


def parcela(rotulo=None, pct=None, valor=None, vencimento: date | None = None, quando=None) -> dict:
    return {"rotulo": rotulo, "pct": pct, "valor": valor,
            "vencimento": vencimento.isoformat() if vencimento else None, "quando": quando}


def _rotulos_padrao(plano: list[dict]) -> list[dict]:
    for i, p in enumerate(plano, 1):
        if not p.get("rotulo"):
            p["rotulo"] = f"{i}ª parcela"
    return plano


REMOVER = {"remover", "tirar", "nenhuma", "a vista", "avista", "tudo de uma vez", "de uma vez", "sem parcelas",
           "apagar", "cancelar"}


def quer_remover(texto: str) -> bool:
    return _norm(texto) in REMOVER


def simples(texto: str, hoje: date) -> list[dict] | None:
    """Formas curtas que não precisam da IA: '3x', '3x mensal', '4 vezes', '50/50', '30/40/30'."""
    t = _norm(texto)
    m = re.fullmatch(r"(\d{1,2}) ?(?:x|vezes)(?: (?:mensal|mensais|por mes|todo mes|ao mes|no mes))?", t)
    if m:
        n = int(m.group(1))
        if not 2 <= n <= MAXIMO:
            return None
        return [parcela(f"{i + 1}ª parcela", vencimento=mais_meses(hoje, i)) for i in range(n)]
    m = re.fullmatch(r"\d{1,3}(?: ?/ ?\d{1,3})+", t)
    if m:
        pcts = [int(x) for x in re.findall(r"\d+", t)]
        if sum(pcts) != 100 or not 2 <= len(pcts) <= MAXIMO or 0 in pcts:
            return None
        plano = []
        for i, pct in enumerate(pcts):
            if i == 0:
                plano.append(parcela("Entrada", pct=pct, quando="para começar"))
            elif i == len(pcts) - 1:
                plano.append(parcela("Final", pct=pct, quando="na entrega"))
            else:
                plano.append(parcela(f"{i + 1}ª etapa", pct=pct))
        return plano
    return None


def de_ia(dados: dict, hoje: date) -> list[dict] | None:
    """Converte o que a IA transcreveu (ver ia.SCHEMA_PARCELAS) para o formato guardado."""
    if not dados or not dados.get("entendeu"):
        return None
    plano = []
    for p in (dados.get("parcelas") or [])[:MAXIMO]:
        pct = p.get("percentual")
        valor = p.get("valor")
        if p.get("resto"):
            pct = valor = None
        elif pct:
            pct, valor = float(pct), None
        elif valor:
            pct, valor = None, round(float(valor) * 100)
        else:
            pct = valor = None  # sem número e sem "resto": também é parte do restante
        venc = None
        if p.get("meses") is not None:
            venc = mais_meses(hoje, int(p["meses"]))
        elif p.get("dias") is not None:
            venc = hoje + timedelta(days=int(p["dias"]))
        rotulo = (str(p.get("rotulo") or "").strip()[:40]) or None
        quando = (str(p.get("quando") or "").strip()[:60]) or None
        if plano and quando and _norm(quando) in ("para comecar", "agora", "de entrada"):
            quando = None  # só a primeira parte é "para começar"; a IA às vezes repete nas parcelas do resto
        plano.append(parcela(rotulo, pct=pct, valor=valor, vencimento=venc, quando=quando))
    return _rotulos_padrao(plano) if len(plano) >= 2 else None


def _fixo(p: dict, total: int) -> int | None:
    if p.get("valor"):
        return int(p["valor"])
    if p.get("pct"):
        return round(total * float(p["pct"]) / 100)
    return None


def valores(plano: list[dict], total: int) -> list[int]:
    fixos = [_fixo(p, total) for p in plano]
    restos = [i for i, v in enumerate(fixos) if v is None]
    sobra = total - sum(v for v in fixos if v is not None)
    if not restos:  # não deveria acontecer (normalizar garante um "resto"), mas fecha a conta na última
        fixos[-1] += sobra
        return fixos
    cada, centavos = divmod(max(sobra, 0), len(restos))
    for k, i in enumerate(restos):
        fixos[i] = cada + (centavos if k == len(restos) - 1 else 0)
    return fixos


def normalizar(plano: list[dict], total: int) -> tuple[list[dict] | None, str | None]:
    """Confere se a divisão fecha com o total. Devolve (plano, None) ou (None, mensagem de erro).
    Sem nenhuma parcela "resto", a última vira o resto: assim o plano acompanha se o orçamento mudar."""
    if not plano or len(plano) < 2:
        return None, "Preciso de pelo menos 2 parcelas."
    if len(plano) > MAXIMO:
        return None, f"Dá para dividir em até {MAXIMO} parcelas."
    fixos = [_fixo(p, total) for p in plano]
    soma = sum(v for v in fixos if v is not None)
    if any(v is not None and v <= 0 for v in fixos):
        return None, "Tem parcela com valor zero."
    if all(v is not None for v in fixos):
        if abs(soma - total) > len(plano):  # tolera o arredondamento de percentuais
            return None, f"As parcelas somam {reais(soma)}, mas o orçamento é de {reais(total)}."
        plano = [dict(p) for p in plano]
        plano[-1]["pct"] = plano[-1]["valor"] = None
    elif soma >= total:
        return None, (f"Só as parcelas com valor já somam {reais(soma)}, e o orçamento é de {reais(total)}: "
                      "não sobra nada para o resto.")
    return _rotulos_padrao([dict(p) for p in plano]), None


def _quando_txt(p: dict) -> str | None:
    if p.get("vencimento"):
        return "vence " + date.fromisoformat(p["vencimento"]).strftime("%d/%m/%Y")
    return p.get("quando")


def situacao(plano: list[dict], total: int, recebido: int, hoje: date | None = None) -> list[dict]:
    """Cada parcela com o que já foi pago (os pagamentos quitam em ordem) e se está atrasada."""
    hoje = hoje or date.today()
    saida, saldo = [], recebido
    for n, (p, valor) in enumerate(zip(plano, valores(plano, total)), 1):
        pago = min(saldo, valor)
        saldo -= pago
        venc = date.fromisoformat(p["vencimento"]) if p.get("vencimento") else None
        falta = valor - pago
        if falta == 0:
            estado = "paga"
        elif venc and venc < hoje:
            estado = "atrasada"
        elif pago:
            estado = "parcial"
        else:
            estado = "aberta"
        saida.append({"n": n, "rotulo": p.get("rotulo") or f"{n}ª parcela", "valor": valor, "pago": pago,
                      "falta": falta, "vencimento": venc, "quando": _quando_txt(p), "estado": estado,
                      "valor_txt": reais(valor), "falta_txt": reais(falta)})
    return saida


def da_vez(orc, hoje: date | None = None) -> dict | None:
    """A primeira parcela ainda não quitada do orçamento (None se não tem plano ou já quitou tudo)."""
    plano = getattr(orc, "parcelas", None)
    if not plano:
        return None
    for p in situacao(plano, orc.total_centavos, orc.recebido_centavos, hoje):
        if p["falta"] > 0:
            p["total_parcelas"] = len(plano)
            return p
    return None


def resumo(plano: list[dict], total: int) -> str:
    linhas = []
    for p, valor in zip(plano, valores(plano, total)):
        quando = _quando_txt(p)
        linhas.append(f"{p.get('rotulo')}: {reais(valor)}" + (f" ({quando})" if quando else ""))
    return "\n".join(f"{i}. {l}" for i, l in enumerate(linhas, 1))
