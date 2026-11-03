"""Monta o orçamento com os preços da tabela. Toda a matemática acontece aqui, nunca na IA."""
import re


def montar_rascunho(dados_ia: dict, tabela: dict[int, dict]) -> dict:
    """Converte a saída da IA num rascunho com preços.

    tabela: {item_preco_id: {"descricao", "unidade", "preco_centavos"}}
    Itens sem preço ficam com preco_centavos=None (o sistema pergunta ao profissional).
    """
    itens = []
    for item in dados_ia.get("itens", []):
        qtd = quantidade(item.get("quantidade"))
        if qtd <= 0:
            continue
        item_id = item.get("item_preco_id")
        if item_id not in tabela:  # protege contra id inventado
            item_id = None

        informado = _numero(item.get("preco_informado"))
        if informado is not None and informado > 0:
            preco, origem = round(informado * 100), "informado"
        elif item_id is not None:
            preco, origem = tabela[item_id]["preco_centavos"], "tabela"
        else:
            preco, origem = None, None

        itens.append(
            {
                "descricao": str(item.get("descricao") or "").strip() or "Item",
                "quantidade": qtd,
                "unidade": item.get("unidade") or (tabela[item_id]["unidade"] if item_id else None),
                "item_preco_id": item_id,
                "preco_centavos": preco,
                "origem": origem,
            }
        )

    cliente = dados_ia.get("cliente") or {}
    return {
        "cliente": {k: cliente.get(k) for k in ("nome", "endereco", "telefone")},
        "itens": itens,
        "observacoes": dados_ia.get("observacoes"),
        "desconto": _desconto(dados_ia),
    }


def _desconto(dados_ia: dict) -> dict | None:
    """Desconto como foi FALADO. O valor em R$ é calculado depois, em valor_desconto()."""
    for chave, tipo in (("total_desejado", "total"), ("desconto_percentual", "percentual"), ("desconto_valor", "valor")):
        valor = dados_ia.get(chave)
        if valor is not None and float(valor) > 0:
            if tipo == "percentual" and float(valor) >= 100:
                continue
            return {"tipo": tipo, "valor": float(valor)}
    return None


_EXTENSO = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "três": 3, "quatro": 4, "cinco": 5, "seis": 6,
            "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "quinze": 15, "vinte": 20,
            "meia duzia": 6, "meia dúzia": 6, "duzia": 12, "dúzia": 12, "uma duzia": 12, "uma dúzia": 12}


def _numero(valor) -> float | None:
    """Número vindo da IA, que às vezes chega como texto ("3", "2,5")."""
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(str(valor).strip().replace(",", "."))
    except ValueError:
        return None


def quantidade(valor) -> float:
    """Quantidade segura: aceita número, "3", "2,5" ou por extenso ("duas", "meia dúzia").
    Sem quantidade = 1. Valor que não dá para entender = 1 (o profissional confere no resumo)."""
    if valor is None or valor == "":
        return 1.0
    n = _numero(valor)
    if n is not None:
        return n
    return float(_EXTENSO.get(str(valor).strip().lower(), 1))


def pendentes(rascunho: dict) -> list[int]:
    """Índices dos itens que ainda estão sem preço."""
    return [i for i, item in enumerate(rascunho["itens"]) if item["preco_centavos"] is None]


def subtotal(item: dict) -> int:
    return round(item["quantidade"] * item["preco_centavos"])


def subtotal_itens(rascunho: dict) -> int:
    return sum(subtotal(i) for i in rascunho["itens"] if i["preco_centavos"] is not None)


def valor_desconto(rascunho: dict) -> int:
    """Desconto em centavos. Negativo = acréscimo (ex: cliente aceitou pagar mais que o calculado)."""
    d = rascunho.get("desconto")
    if not d:
        return 0
    sub = subtotal_itens(rascunho)
    if d["tipo"] == "percentual":
        return round(sub * d["valor"] / 100)
    if d["tipo"] == "valor":
        return min(round(d["valor"] * 100), sub)
    if d["tipo"] == "acrescimo":
        return -round(d["valor"] * 100)
    return sub - round(d["valor"] * 100)  # "total": valor final desejado


def total(rascunho: dict) -> int:
    return subtotal_itens(rascunho) - valor_desconto(rascunho)


def fixar_desconto(rascunho: dict) -> dict:
    """Converte "fecha em X" num desconto fixo em R$, para que mudanças futuras nos itens não
    mantenham o total travado em X sem querer."""
    d = rascunho.get("desconto")
    if d and d["tipo"] == "total" and not pendentes(rascunho):
        dif = valor_desconto(rascunho)
        rascunho["desconto"] = {"tipo": "valor", "valor": dif / 100} if dif > 0 else (
            {"tipo": "acrescimo", "valor": -dif / 100} if dif < 0 else None)
    return rascunho


def rotulo_desconto(rascunho: dict) -> str:
    d = rascunho.get("desconto") or {}
    if d.get("tipo") == "percentual":
        return f"Desconto ({qtd_fmt(d['valor'])}%)"
    return "Acréscimo" if valor_desconto(rascunho) < 0 else "Desconto"


def valor_sinal(total_centavos: int, percentual: int | None) -> int:
    """Sinal pedido no link do cliente. None = 50%; 0 = o total (sem sinal, paga tudo)."""
    pct = 50 if percentual is None else percentual
    return total_centavos if pct <= 0 or pct >= 100 else round(total_centavos * pct / 100)


def valor_curto(centavos: int) -> str:
    """24000 -> '240'; 24050 -> '240,50' (para comandos como /pago 3 240,50)."""
    return str(centavos // 100) if centavos % 100 == 0 else f"{centavos / 100:.2f}".replace(".", ",")


def reais(centavos: int) -> str:
    """12345 -> 'R$ 123,45' (formato brasileiro)."""
    s = f"{centavos / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def qtd_fmt(qtd: float) -> str:
    return str(int(qtd)) if qtd == int(qtd) else f"{qtd:.2f}".rstrip("0").replace(".", ",")


def ler_valor(texto: str) -> int | None:
    """Extrai um valor em reais de um texto livre e devolve em centavos.

    Aceita: '80', 'R$ 80,50', '1.200', '1200.00', '80 reais'.
    """
    m = re.search(r"\d[\d.,]*", texto)
    if not m or re.search(r"-\s*$", texto[:m.start()]):  # sem número, ou número negativo
        return None
    bruto = m.group().rstrip(".,")
    if "," in bruto:  # formato BR: 1.234,56
        bruto = bruto.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", bruto):  # 1.200 = mil e duzentos
        bruto = bruto.replace(".", "")
    try:
        valor = float(bruto)
    except ValueError:
        return None
    return round(valor * 100) if valor > 0 else None
