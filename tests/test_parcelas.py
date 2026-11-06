"""Pagamento dividido em parcelas/etapas: plano, chat, PDF, página do cliente, painel e cobrança."""
from datetime import date, datetime, timedelta

from app import calculo, parcelas
from app.db import Orcamento
from tests.apoio_web import montar
from tests.test_fluxo import _hora_sp
from tests.test_roteador import IARoteadora

HOJE = date(2026, 11, 6)


# ---------------------------------------------------------------- regras do plano
def test_formas_curtas_sem_ia():
    tres = parcelas.simples("3x mensal", HOJE)
    assert [p["vencimento"] for p in tres] == ["2026-11-06", "2026-12-06", "2027-01-06"]
    assert parcelas.simples("4 vezes", HOJE)[3]["vencimento"] == "2027-02-06"
    meio = parcelas.simples("50/50", HOJE)
    assert [(p["rotulo"], p["pct"], p["quando"]) for p in meio] == [("Entrada", 50, "para começar"),
                                                                     ("Final", 50, "na entrega")]
    assert len(parcelas.simples("30 / 40 / 30", HOJE)) == 3
    for ruim in ("50/40", "1x", "30x", "metade agora", "100/0"):
        assert parcelas.simples(ruim, HOJE) is None


def test_mes_curto_nao_quebra_a_data():
    assert parcelas.mais_meses(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_valores_fecham_com_o_total_e_acompanham_mudanca():
    plano, erro = parcelas.normalizar(parcelas.simples("3x", HOJE), 100000)
    assert erro is None and parcelas.valores(plano, 100000) == [33333, 33333, 33334]
    entrada_resto = [parcelas.parcela("Entrada", valor=30000), parcelas.parcela(), parcelas.parcela()]
    plano, _ = parcelas.normalizar(entrada_resto, 100000)
    assert parcelas.valores(plano, 100000) == [30000, 35000, 35000]
    assert parcelas.valores(plano, 120000) == [30000, 45000, 45000]  # orçamento mudou: o resto acompanha
    plano, _ = parcelas.normalizar(parcelas.simples("50/50", HOJE), 100000)
    assert parcelas.valores(plano, 80000) == [40000, 40000]


def test_divisao_que_nao_fecha_e_recusada():
    _, erro = parcelas.normalizar([parcelas.parcela(valor=30000), parcelas.parcela(valor=50000)], 100000)
    assert "somam R$ 800,00" in erro and "R$ 1.000,00" in erro
    _, erro = parcelas.normalizar([parcelas.parcela(valor=100000), parcelas.parcela()], 100000)
    assert "não sobra nada" in erro
    _, erro = parcelas.normalizar([parcelas.parcela(valor=100000)], 100000)
    assert "pelo menos 2" in erro


def test_pagamentos_quitam_em_ordem():
    plano, _ = parcelas.normalizar(parcelas.simples("3x", HOJE), 90000)
    sit = parcelas.situacao(plano, 90000, 45000, hoje=HOJE + timedelta(days=40))
    assert [p["estado"] for p in sit] == ["paga", "atrasada", "aberta"]
    assert sit[1]["falta"] == 15000


def test_o_que_a_ia_transcreveu_vira_plano():
    dados = {"entendeu": True, "parcelas": [
        {"rotulo": "Entrada", "percentual": None, "valor": 300, "resto": False, "meses": None, "dias": None,
         "quando": "para começar"},
        {"rotulo": None, "percentual": None, "valor": None, "resto": True, "meses": 1, "dias": None, "quando": None},
        {"rotulo": None, "percentual": None, "valor": None, "resto": True, "meses": 2, "dias": None, "quando": None}]}
    plano = parcelas.de_ia(dados, HOJE)
    assert [p["rotulo"] for p in plano] == ["Entrada", "2ª parcela", "3ª parcela"]
    assert plano[0]["valor"] == 30000 and plano[2]["vencimento"] == "2027-01-06"
    assert parcelas.de_ia({"entendeu": False, "parcelas": []}, HOJE) is None


# ---------------------------------------------------------------- no chat e no site
class IAParcelas(IARoteadora):
    def ler_parcelas(self, texto, total):
        if texto == "entrada de 100 e o resto em 2x por mês":
            linha = lambda **kw: {"rotulo": None, "percentual": None, "valor": None, "resto": False, "meses": None,
                                  "dias": None, "quando": None, **kw}
            return {"entendeu": True, "parcelas": [linha(rotulo="Entrada", valor=100, quando="para começar"),
                                                   linha(resto=True, meses=1), linha(resto=True, meses=2)]}
        return {"entendeu": False, "parcelas": []}


def _pronto(tmp_path):
    a = montar(tmp_path, ia=IAParcelas())
    a.cadastrar()
    a.orcamento()
    return a


def test_dividir_pelo_botao_gera_pdf_e_mostra_no_link(tmp_path):
    a = _pronto(tmp_path)
    total = a.orc(1).total_centavos
    rs, t = a.bot("/parcelas 1 50/50")
    assert "dividido" in t and "Entrada" in t and "Final" in t
    assert any(r.arquivo and r.arquivo.endswith(".pdf") for r in rs)
    pix_vez = [r.texto for r in rs if r.texto and r.texto.startswith("000201")]
    assert pix_vez and calculo.reais(total // 2).replace("R$ ", "") in t  # Pix da entrada, não do total
    with a.Sessao() as s:
        orc = s.query(Orcamento).one()
        assert len(orc.parcelas) == 2
    a.bot("/aprovado 1")
    pagina = a.web.get(_link_cliente(a)).text
    assert "Parcelas" in pagina and "Entrada (1 de 2)" in pagina and "na entrega" in pagina


def _link_cliente(a):
    from app.db import Link
    with a.Sessao() as s:
        return "/o/" + s.query(Link).filter_by(tipo="cliente").first().token


def test_recebimento_diz_a_proxima_parcela(tmp_path):
    a = _pronto(tmp_path)
    a.bot("/parcelas 1 50/50")
    rs, _ = a.bot("/aprovado 1")
    assert rs[0].botoes[0][0][0].startswith("💰 Recebi Entrada")
    _, t = a.bot(rs[0].botoes[0][0][1])  # toca no botão da entrada
    assert "Próxima: Final" in t and "na entrega" in t
    _, t = a.bot("/pago 1")
    assert "quitado" in t and "Próxima" not in t


def test_sem_dizer_a_divisao_pergunta_e_entende_a_resposta(tmp_path):
    a = _pronto(tmp_path)
    rs, t = a.bot("/parcelas 1")
    assert "Como o cliente vai pagar" in t and rs[-1].botoes
    _, t = a.bot("entrada de 100 e o resto em 2x por mês")
    assert "dividido" in t and "Entrada: R$ 100,00" in t
    assert len(a.orc(1).parcelas) == 3
    assert a.prof().estado == "OCIOSO"


def test_divisao_que_nao_entendeu_continua_perguntando(tmp_path):
    a = _pronto(tmp_path)
    a.bot("/parcelas 1")
    _, t = a.bot("sei la, vê aí")
    assert "Não entendi" in t and a.prof().estado == "PARCELAS_1"
    _, t = a.bot("cancelar")
    assert a.prof().estado == "OCIOSO" and a.orc(1).parcelas is None


def test_voltar_a_pagar_de_uma_vez(tmp_path):
    a = _pronto(tmp_path)
    _, t = a.bot("/parcelas 1 3x")
    assert "dividido" in t
    _, t = a.bot("/parcelas 1 remover")
    assert "de uma vez" in t and a.orc(1).parcelas is None


def test_sem_numero_pergunta_qual_quando_ha_varios(tmp_path):
    a = _pronto(tmp_path)
    _, t = a.bot("/parcelas")  # só um em aberto: vai direto nele
    assert "Nº 0001" in t and "Como o cliente vai pagar" in t
    a.bot("cancelar")
    a.orcamento()
    rs, t = a.bot("/parcelas 3x")
    assert "De qual orçamento" in t
    assert [b[0][1] for b in rs[-1].botoes] == ["/parcelas 2 3x", "/parcelas 1 3x"]
    assert a.orc(1).parcelas is None and a.orc(2).parcelas is None


def test_pedido_livre_chega_nas_parcelas(tmp_path):
    IARoteadora.rotas["o 1 vai ser em 3x"] = {
        "acoes": [{"comando": "/parcelas", "argumento": "1 3x"}], "pergunta": None, "opcoes": []}
    a = _pronto(tmp_path)
    _, t = a.bot("o 1 vai ser em 3x")
    assert "dividido" in t and len(a.orc(1).parcelas) == 3


def test_painel_mostra_parcela_da_vez_e_o_que_vence(tmp_path):
    a = _pronto(tmp_path)
    a.bot("/parcelas 1 3x")
    a.bot("/aprovado 1")
    _, t = a.bot("/painel")
    url = "/d/" + t.split("/d/")[1].split()[0]
    pagina = a.web.get(url).text
    assert "Parcelas para receber nos próximos 7 dias" in pagina and "vence hoje" in pagina
    assert "Parcela da vez" in pagina and "Recebi 1ª parcela" in pagina
    terco = parcelas.valores(a.orc(1).parcelas, a.orc(1).total_centavos)[0]
    a.web.post(url + "/acao", data={"numero": "1", "acao": "parcial", "valor": calculo.valor_curto(terco)})
    assert a.orc(1).recebido_centavos == terco
    pagina = a.web.get(url).text
    assert "Recebi 2ª parcela" in pagina and "vence hoje" not in pagina
    csv = a.web.get(url + "/planilha.csv").content.decode("utf-8-sig")
    assert "Próxima parcela" in csv and "2ª parcela (2 de 3)" in csv


def test_cobranca_espera_o_vencimento_da_parcela(tmp_path):
    a = _pronto(tmp_path)
    a.bot("/parcelas 1 2x")
    a.bot("/aprovado 1")
    valores = parcelas.valores(a.orc(1).parcelas, a.orc(1).total_centavos)
    a.bot(f"/pago 1 {calculo.valor_curto(valores[0])}")
    assert a.nucleo.verificar_cobrancas(_hora_sp(10, 10)) == []  # 2ª vence daqui ~1 mês
    envios = a.nucleo.verificar_cobrancas(_hora_sp(40, 10))  # 1 mês + 7 dias depois
    assert envios and calculo.reais(valores[1]) in envios[0][1][1].texto
    assert "2ª parcela" in envios[0][1][1].texto


def test_parcela_na_entrega_nao_gera_cobranca_automatica(tmp_path):
    a = _pronto(tmp_path)
    a.bot("/parcelas 1 50/50")
    a.bot("/aprovado 1")
    a.bot("/pago 1 " + calculo.valor_curto(a.orc(1).total_centavos // 2))
    assert a.nucleo.verificar_cobrancas(_hora_sp(30, 10)) == []
    _, t = a.bot("/cobrar 1")  # ele cobra quando entregar
    assert "Final" in t
