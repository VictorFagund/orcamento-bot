"""Avalia a IA REAL (a do seu .env) com frases realistas e mostra a taxa de acerto.

Rodar:   python avaliar_ia.py
Opções:  python avaliar_ia.py --caso 5        (só um caso)
         python avaliar_ia.py --json res.json (salva o detalhe)

Use para: comparar modelos/provedores (troque no .env e rode de novo) e ver se uma mudança no prompt
melhorou ou piorou. Cada chamada custa centavos (OpenAI) ou usa sua cota grátis (Groq).
"""
import argparse
import json
import os
import sys
import time
import unicodedata

CASOS = os.path.join(os.path.dirname(__file__), "tests", "casos_ia.json")


def _norm(t) -> str:
    return unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()


def _perto(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.01
    except (TypeError, ValueError):
        return False


def avaliar_caso(esperado: dict, resp: dict) -> tuple[list[str], list[str], bool]:
    """Devolve (verificações que passaram, as que falharam, inventou_preço)."""
    ok, falhas = [], []

    def checa(nome, cond):
        (ok if cond else falhas).append(nome)

    if "intencao" in esperado:
        checa(f"intenção = {esperado['intencao']} (veio {resp.get('intencao')})", resp.get("intencao") == esperado["intencao"])
    cli = resp.get("cliente") or {}
    if "cliente_nome" in esperado:
        e = esperado["cliente_nome"]
        cond = (not cli.get("nome")) if e is None else _norm(e) in _norm(cli.get("nome"))
        checa(f"cliente {'vazio' if e is None else '~ ' + e} (veio {cli.get('nome')!r})", cond)
    for campo in ("endereco", "telefone"):
        if campo in esperado:
            checa(f"{campo} contém {esperado[campo]!r} (veio {cli.get(campo)!r})",
                  _norm(esperado[campo]) in _norm(cli.get(campo)))
    if esperado.get("observacoes"):
        checa("observações preenchidas", bool(resp.get("observacoes")))
    for campo in ("numero_orcamento", "valor_pago", "desconto_percentual", "desconto_valor", "total_desejado"):
        if campo in esperado:
            e, v = esperado[campo], resp.get(campo)
            checa(f"{campo} = {e} (veio {v})", v is None if e is None else _perto(v, e))
    if esperado.get("sem_desconto"):
        checa("desconto removido", all(resp.get(c) is None for c in
                                       ("desconto_percentual", "desconto_valor", "total_desejado")))

    inventou = False
    if "itens" in esperado:
        itens = list(resp.get("itens") or [])
        for e in esperado["itens"]:
            aceitos = e["id"] if isinstance(e["id"], list) else [e["id"]]
            achado = next((i for i in itens if i.get("item_preco_id") in aceitos and
                           (e.get("contem") is None or _norm(e["contem"]) in _norm(i.get("descricao")))), None)
            rotulo = f"item {e.get('contem') or e['id']}"
            if achado is None:
                falhas.append(f"{rotulo} não encontrado")
                continue
            itens.remove(achado)
            checa(f"{rotulo}: quantidade {e['qtd']} (veio {achado.get('quantidade')})", _perto(achado.get("quantidade"), e["qtd"]))
            if "preco" in e:
                checa(f"{rotulo}: preço dito {e['preco']} (veio {achado.get('preco_informado')})",
                      _perto(achado.get("preco_informado"), e["preco"]))
            elif achado.get("preco_informado") is not None:
                inventou = True
        checa(f"sem itens a mais ({len(itens)} sobrando: {[i.get('descricao') for i in itens]})", not itens)
        inventou = inventou or any(i.get("preco_informado") is not None for i in itens)
        checa("não inventou preço", not inventou)

    if "precos" in esperado:
        precos = list(resp.get("precos") or [])
        for e in esperado["precos"]:
            achado = next((p for p in precos if _norm(e["contem"]) in _norm(p.get("descricao"))), None)
            checa(f"preço de '{e['contem']}' = {e['preco']} (veio {achado and achado.get('preco')})",
                  achado is not None and _perto(achado.get("preco"), e["preco"]))
    return ok, falhas, inventou


def rodar(ia, casos: dict, so: int | None = None, saida=print) -> dict:
    resultados, tempos = [], []
    for n, caso in enumerate(casos["casos"], 1):
        if so and n != so:
            continue
        inicio = time.time()
        try:
            resp = ia.interpretar(caso["mensagem"], casos["tabela"], rascunho=caso.get("rascunho"),
                                  contexto=caso.get("contexto", ""))
            erro = None
        except Exception as e:  # noqa: BLE001 - queremos registrar qualquer falha da IA
            resp, erro = {}, f"{type(e).__name__}: {e}"
        tempos.append(time.time() - inicio)
        ok, falhas, inventou = avaliar_caso(caso["esperado"], resp) if not erro else ([], [erro], False)
        passou = not falhas
        resultados.append({"n": n, "nome": caso["nome"], "passou": passou, "ok": ok, "falhas": falhas,
                           "inventou_preco": inventou, "resposta": resp, "segundos": round(tempos[-1], 2)})
        saida(f"{'✅' if passou else '❌'} {n:2d}. {caso['nome']}  ({tempos[-1]:.1f}s)")
        for f in falhas:
            saida(f"       ✗ {f}")

    total = len(resultados)
    casos_ok = sum(r["passou"] for r in resultados)
    checks_ok = sum(len(r["ok"]) for r in resultados)
    checks = checks_ok + sum(len(r["falhas"]) for r in resultados)
    inventados = sum(r["inventou_preco"] for r in resultados)
    resumo = {"casos": total, "casos_ok": casos_ok, "verificacoes": checks, "verificacoes_ok": checks_ok,
              "precos_inventados": inventados, "tempo_medio": round(sum(tempos) / max(len(tempos), 1), 2)}
    saida("")
    saida(f"Casos corretos:     {casos_ok}/{total} ({100 * casos_ok // max(total, 1)}%)")
    saida(f"Verificações:       {checks_ok}/{checks} ({100 * checks_ok // max(checks, 1)}%)")
    saida(f"Preços inventados:  {inventados}  (o ideal é 0 - mesmo assim o bot mostra tudo para conferência)")
    saida(f"Tempo médio:        {resumo['tempo_medio']}s por mensagem")
    return {"resumo": resumo, "resultados": resultados}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--caso", type=int, help="roda só o caso de número N")
    parser.add_argument("--json", help="salva o resultado detalhado neste arquivo")
    args = parser.parse_args()

    from app import config
    from app.ia import IAOpenAI

    print(f"Modelo: {config.MODELO_TEXTO}  |  provedor: {config.IA_BASE_URL or 'OpenAI'}  |  modo JSON: {config.IA_MODO_JSON}\n")
    with open(CASOS, encoding="utf-8") as f:
        casos = json.load(f)
    resultado = rodar(IAOpenAI(), casos, args.caso)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=1, default=str)
        print(f"\nDetalhes salvos em {args.json}")
    sys.exit(0 if resultado["resumo"]["casos_ok"] == resultado["resumo"]["casos"] else 1)


if __name__ == "__main__":
    main()
