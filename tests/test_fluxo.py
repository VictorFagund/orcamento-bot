"""Testa o fluxo completo com uma IA simulada (não gasta nada, não precisa de chave).

Rodar:  python -m pytest -q
"""
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import calculo
from app.db import Orcamento, Profissional, iniciar_banco
from app.ia import rascunho_para_ia
from app.nucleo import Mensagem, Nucleo


class IAFalsa:
    """Devolve respostas prontas, imitando o formato da IA real."""

    def transcrever(self, audio, nome_arquivo="audio.ogg"):
        return audio.decode()  # no teste, o "áudio" já é o texto

    ultimo_contexto = ""

    def interpretar(self, texto, tabela, rascunho=None, contexto=""):
        IAFalsa.ultimo_contexto = contexto
        vazio = {"intencao": "outro", "numero_orcamento": None,
                 "cliente": {"nome": None, "endereco": None, "telefone": None},
                 "itens": [], "precos": [], "observacoes": None,
                 "desconto_percentual": None, "desconto_valor": None, "total_desejado": None, "valor_pago": None}
        if rascunho:  # edição: a IA real recebe o estado atual e devolve o estado completo corrigido
            atual = {**vazio, **rascunho_para_ia(rascunho), "intencao": "orcamento"}
            if "por 700" in texto:
                return {**atual, "desconto_percentual": None, "desconto_valor": None, "total_desejado": 700}
            if "10%" in texto:
                for i in atual["itens"]:
                    if "chuveiro" in i["descricao"].lower():
                        i["preco_informado"] = 100
                return {**atual, "desconto_percentual": 10, "desconto_valor": None, "total_desejado": None}
            if "pagar 650" in texto:
                return {**atual, "desconto_percentual": None, "desconto_valor": None, "total_desejado": 650}
        if "ENCAMINHADA" in texto and "700" in texto:
            return {**vazio, "intencao": "editar"}
        if "pagar 650" in texto:
            return {**vazio, "intencao": "editar", "cliente": {"nome": "Maria", "endereco": None, "telefone": None}}
        if texto.startswith("recebi 300 da Dona Maria"):
            return {**vazio, "intencao": "pagamento", "valor_pago": 300,
                    "cliente": {"nome": "Maria", "endereco": None, "telefone": None}}
        if texto == "recebi o resto":
            return {**vazio, "intencao": "pagamento"}
        if texto == "limpeza 150":
            return {**vazio, "intencao": "tabela_precos", "precos": [
                {"descricao": "Limpeza / higienização", "unidade": "un", "preco": 150, "sinonimos": []}]}
        ids = {t["descricao"]: t["id"] for t in tabela}
        if texto.startswith("Orçamento pro ") and ", limpeza" in texto:
            nome = texto[len("Orçamento pro "):texto.index(", limpeza")]
            return {**vazio, "intencao": "orcamento", "cliente": {"nome": nome, "endereco": None, "telefone": None},
                    "itens": [{"descricao": "Limpeza / higienização", "quantidade": 2, "unidade": "un",
                               "item_preco_id": ids.get("Limpeza / higienização"), "preco_informado": None}]}
        if texto == "40, 120" and "lista numerada" in contexto:  # números na ordem do catálogo
            return {**vazio, "intencao": "tabela_precos", "precos": [
                {"descricao": "Troca de tomada ou interruptor", "unidade": "un", "preco": 40, "sinonimos": []},
                {"descricao": "Instalação de chuveiro", "unidade": "un", "preco": 120, "sinonimos": []},
            ]}
        if "tomada 40" in texto:
            return {**vazio, "intencao": "tabela_precos", "precos": [
                {"descricao": "Troca de tomada", "unidade": "un", "preco": 40, "sinonimos": ["tomada"]},
                {"descricao": "Instalação de chuveiro", "unidade": "un", "preco": 120, "sinonimos": ["chuveiro"]},
            ]}
        cliente = {"nome": "Dona Maria", "endereco": "Rua das Flores, 120", "telefone": None}
        if "Dona Maria" in texto:
            return {**vazio, "intencao": "orcamento", "cliente": cliente, "observacoes": "Prazo de 2 dias", "itens": [
                {"descricao": "Troca de tomada", "quantidade": 6, "unidade": "un",
                 "item_preco_id": ids.get("Troca de tomada"), "preco_informado": None},
                {"descricao": "Instalação de chuveiro", "quantidade": 2, "unidade": "un",
                 "item_preco_id": 999, "preco_informado": None},  # id inventado: deve cair na tabela? não -> pergunta
                {"descricao": "Fiação nova", "quantidade": 15, "unidade": "m",
                 "item_preco_id": None, "preco_informado": None},
            ]}
        if "8 tomadas" in texto:
            itens = [dict(i, preco_informado=None) for i in _itens_ia(rascunho)]
            itens[0]["quantidade"] = 8
            return {**vazio, "intencao": "orcamento", "cliente": cliente, "itens": itens,
                    "observacoes": "Prazo de 2 dias"}
        return vazio


def _itens_ia(rascunho):
    return [{"descricao": i["descricao"], "quantidade": i["quantidade"], "unidade": i["unidade"],
             "item_preco_id": i["item_preco_id"]} for i in rascunho["itens"]]


@pytest.fixture
def bot(tmp_path):
    Sessao = iniciar_banco(f"sqlite:///{tmp_path}/teste.db")
    nucleo = Nucleo(Sessao, IAFalsa(), pasta_arquivos=str(tmp_path / "arquivos"))

    def enviar(texto=None, audio=None, encaminhada_de=None, foto=None):
        rs = nucleo.processar("teste:1", Mensagem(texto=texto, audio=audio, encaminhada_de=encaminhada_de, foto=foto))
        return rs, "\n".join(r.texto for r in rs if r.texto)

    enviar.Sessao = Sessao
    enviar.nucleo = nucleo
    return enviar


@pytest.mark.parametrize("profissao, primeiro", [
    ("Mecanico", "Troca de óleo e filtro"),
    ("Mecânico de automóveis", "Troca de óleo e filtro"),
    ("Eletricista automotivo", "Troca de óleo e filtro"),  # oficina, não elétrica de casa
    ("Mecânico de refrigeração", "Instalação de split até 12.000 BTUs"),  # é técnico de ar
    ("Eletricista", "Troca de tomada ou interruptor"),
    ("Serralheiro", "Portão de ferro"),
    ("Dedetizadora", "Dedetização"),
    ("Chaveiro 24h", "Abertura de porta"),
])
def test_catalogo_por_profissao(profissao, primeiro):
    from app.catalogo import servicos_da_profissao
    assert servicos_da_profissao(profissao)[0][0] == primeiro


def test_checklist_respondido_de_uma_vez(bot):
    bot("oi")
    _, t = bot("1. Victor Mecânica\n2. Mecânico\n3. (46) 99999-0000\n4. Realeza\n5. Pix\n"
               "6. CPF 529.982.247-25\n7. Sem logo")
    assert "Anotei de uma vez" in t and "Nome: Victor Mecânica" in t and "Cidade: Realeza" in t
    assert "Pix: 52998224725" in t and "1. Troca de óleo e filtro" in t  # pulou a logo e já mostra a lista
    with bot.Sessao() as s:
        prof = s.query(Profissional).one()
        assert (prof.nome, prof.profissao, prof.telefone, prof.estado) == (
            "Victor Mecânica", "Mecânico", "(46) 99999-0000", "CADASTRO_TABELA")


def test_checklist_de_uma_vez_para_na_resposta_invalida(bot):
    bot("oi")
    _, t = bot("Victor\nMecânico\n46999990000\nRealeza\nPix\n46999990000\nSem logo")
    assert "Nome: Victor" in t and "podem ser CPF ou celular" in t  # Pix ambígua: pergunta, não chuta
    _, t = bot("CPF 529.982.247-25")
    assert "Tem logo da empresa?" in t  # segue do ponto onde parou


def test_fluxo_completo(bot):
    _, t = bot("oi")
    assert "qual o seu nome" in t and "Chave Pix" in t  # checklist do cadastro logo de cara
    bot("Victor Elétrica")
    bot("Eletricista")
    bot("(46) 99999-0000")
    bot("Santa Izabel do Oeste")
    bot("Pix ou cartão, 50% de entrada")
    _, t = bot("(46) 99999-0000")
    assert "Chave Pix (celular) salva: +5546999990000" in t and "Tem logo da empresa?" in t
    _, t = bot("tenho sim")  # texto no passo da logo: pede a foto em vez de seguir
    assert "Mande a logo como foto" in t
    _, t = bot(foto=b"\xff\xd8\xff fake jpeg")
    assert "Logo salva" in t
    assert "1. Troca de tomada ou interruptor" in t  # catálogo do eletricista, sem preços
    _, t = bot("tomada 40, chuveiro 120")
    assert "Troca de tomada: R$ 40,00" in t and "Cadastro pronto" in t

    # Orçamento por "áudio": chuveiro veio com id inventado e fiação não existe -> pergunta os dois
    _, t = bot(audio="Orçamento pra Dona Maria, trocar 6 tomadas, 2 chuveiros e 15 metros de fiação".encode())
    assert "Entendi" in t and '"Instalação de chuveiro" ainda não está' in t
    _, t = bot("não sei")  # valor inválido
    assert "Não entendi o valor" in t
    _, t = bot("R$ 120")
    assert '"Fiação nova" ainda não está' in t and "(por m)" in t
    _, t = bot("12,50")
    assert "Total: R$ 667,50" in t  # 6*40 + 2*120 + 15*12,50

    _, t = bot("são 8 tomadas")
    assert "Total: R$ 747,50" in t

    rs, t = bot("ok")
    pdf = next(r.arquivo for r in rs if r.arquivo)
    assert os.path.exists(pdf) and os.path.getsize(pdf) > 1000
    assert "Nº 0001" in t
    codigo = rs[-1].texto  # Pix copia e cola sozinho na última mensagem, fácil de encaminhar
    assert codigo.startswith("000201") and "5406747.50" in codigo and "+5546999990000" in codigo
    assert os.path.exists(pdf.replace(".pdf", "_pix.png"))

    _, t = bot("/aprovado 1")
    assert "aprovado" in t
    with bot.Sessao() as s:
        orc = s.query(Orcamento).one()
        assert orc.status == "aprovado" and orc.total_centavos == 74750 and len(orc.itens) == 3

    _, t = bot("/precos")
    assert "Fiação nova (m) - R$ 12,50" in t


def _cadastro_e_orcamento(bot):
    for msg in ["oi", "Victor Elétrica", "Eletricista", "pular", "pular", "Pix", "pular", "pular", "tomada 40, chuveiro 120"]:
        bot(msg)
    bot("Orçamento pra Dona Maria, trocar 6 tomadas, 2 chuveiros e 15 metros de fiação")
    bot("120")
    bot("12,50")
    bot("são 8 tomadas")
    bot("ok")  # Nº 0001, total R$ 747,50


def test_cliente_pede_mudanca_encaminhada(bot):
    _cadastro_e_orcamento(bot)

    # Profissional encaminha a mensagem do cliente: o bot pergunta qual orçamento
    _, t = bot("Consegue fazer por 700?", encaminhada_de="Maria Souza")
    assert "Em qual orçamento" in t and "Nº 0001" in t
    _, t = bot("1")
    assert "Revisão do orçamento Nº 0001" in t
    assert "Subtotal: R$ 747,50" in t and "Desconto: -R$ 47,50" in t and "Total: R$ 700,00" in t

    rs, t = bot("ok")
    pdf = next(r.arquivo for r in rs if r.arquivo)
    assert pdf.endswith("orcamento_0001_r2.pdf") and os.path.exists(pdf)
    assert "revisão 2" in t
    with bot.Sessao() as s:
        orc = s.query(Orcamento).one()  # continua sendo o mesmo orçamento, não cria outro
        assert (orc.revisao, orc.total_centavos, orc.desconto_centavos) == (2, 70000, 4750)


def test_editar_com_desconto_percentual_e_preco_do_item(bot):
    _cadastro_e_orcamento(bot)
    _, t = bot("/editar 1 dá 10% de desconto e o chuveiro sai 100")
    # 8*40 + 2*100 + 15*12,50 = 707,50 ; -10% = 636,75
    assert "R$ 100,00 ✏️" in t and "Desconto (10%): -R$ 70,75" in t and "Total: R$ 636,75" in t
    assert "sua tabela não muda" in t
    bot("ok")
    _, t = bot("/precos")
    assert "Instalação de chuveiro (un) - R$ 120,00" in t  # tabela intacta
    with bot.Sessao() as s:
        orc = s.query(Orcamento).one()
        assert (orc.revisao, orc.total_centavos, orc.desconto_percentual) == (2, 63675, 10)


def test_editar_pelo_nome_do_cliente_e_cancelar(bot):
    _cadastro_e_orcamento(bot)
    _, t = bot("no orçamento da Dona Maria o cliente quer pagar 650")
    assert "Revisão do orçamento Nº 0001" in t and "Total: R$ 650,00" in t
    _, t = bot("cancelar")
    assert "continua como estava" in t
    with bot.Sessao() as s:
        assert s.query(Orcamento).one().total_centavos == 74750


def test_cancelar(bot):
    for msg in ["oi", "Ana Pinturas", "Pintora", "pular", "pular", "pular", "pular", "pular", "tomada 40"]:
        bot(msg)
    _, t = bot("Orçamento pra Dona Maria")
    assert "ainda não está" in t
    _, t = bot("cancelar")
    assert "descartado" in t
    _, t = bot("/orcamentos")
    assert "ainda não tem" in t


def test_pix_invalida_ambigua_e_catalogo(bot):
    for msg in ["oi", "Victor", "Eletricista", "pular", "Francisco Beltrão", "pular"]:
        bot(msg)
    _, t = bot("abc")
    assert "Não reconheci essa chave" in t
    _, t = bot("46999990000")  # pode ser CPF ou celular: pergunta em vez de adivinhar
    assert "podem ser CPF ou celular" in t
    _, t = bot("CPF 529.982.247-25")
    assert "Chave Pix (CPF) salva: 52998224725" in t
    bot("pular")  # logo
    _, t = bot("40, 120")
    assert "lista numerada" in IAFalsa.ultimo_contexto and "1. Troca de tomada ou interruptor" in IAFalsa.ultimo_contexto
    assert "Cadastro pronto" in t
    from app.db import ItemPreco
    with bot.Sessao() as s:
        tomada = s.query(ItemPreco).filter_by(descricao="Troca de tomada ou interruptor").one()
        assert "interruptor" in tomada.sinonimos  # sinônimos do catálogo entram junto
    _, t = bot("/pix remover")
    assert "removida" in t


def _hora_sp(dias, hora):
    """Horário do servidor equivalente a 'daqui N dias, às H horas em São Paulo'."""
    sp = (datetime.now(ZoneInfo("America/Sao_Paulo")) + timedelta(days=dias)).replace(hour=hora, minute=0)
    return sp.astimezone().replace(tzinfo=None)


def test_lembretes_de_followup(bot):
    _cadastro_e_orcamento(bot)
    n = bot.nucleo
    assert n.verificar_followups(_hora_sp(1, 10)) == []  # cedo demais
    assert n.verificar_followups(_hora_sp(4, 23)) == []  # fora do horário comercial

    envios = n.verificar_followups(_hora_sp(4, 10))
    assert len(envios) == 1 and envios[0][0] == "teste:1"
    aviso, msg_cliente = (r.texto for r in envios[0][1])
    assert re.search(r"Nº 0001 \(Dona Maria, R\$ 747,50\) está sem resposta há [34] dias", aviso) and "/adiar 1" in aviso
    assert msg_cliente.startswith("Olá, Dona Maria!") and "Victor Elétrica" in msg_cliente
    assert n.verificar_followups(_hora_sp(4, 11)) == []  # não repete o mesmo lembrete

    envios = n.verificar_followups(_hora_sp(8, 10))
    assert "vale até" in envios[0][1][1].texto  # 2º lembrete fala da validade
    assert n.verificar_followups(_hora_sp(20, 10)) == []  # depois do 2º, para

    bot("/adiar 1")
    assert len(n.verificar_followups(_hora_sp(4, 10))) == 1  # adiado: recomeça a contagem
    bot("/aprovado 1")
    assert n.verificar_followups(_hora_sp(30, 10)) == []  # aprovado não recebe lembrete


@pytest.mark.parametrize("texto,centavos", [
    ("80", 8000), ("R$ 80,50", 8050), ("1.200", 120000), ("1.234,56", 123456), ("1200.00", 120000),
    ("cobro 45 reais", 4500), ("sei lá", None), ("0", None),
])
def test_ler_valor(texto, centavos):
    assert calculo.ler_valor(texto) == centavos


def test_reais():
    assert calculo.reais(123456) == "R$ 1.234,56"
    assert calculo.reais(5) == "R$ 0,05"


def test_pagamento_parcial_recibo_e_cobranca(bot):
    _cadastro_e_orcamento(bot)  # Nº 0001, R$ 747,50
    _, t = bot("/aprovado 1")
    assert "/pago 1" in t
    _, t = bot("/areceber")
    assert "falta R$ 747,50" in t

    rs, t = bot("recebi 300 da Dona Maria")  # linguagem natural, entrada parcial
    recibo = next(r.arquivo for r in rs if r.arquivo)
    assert os.path.basename(recibo) == "recibo_0001_1.pdf" and os.path.exists(recibo)
    assert "R$ 300,00 registrado" in t and "Falta R$ 447,50" in t
    _, t = bot("/orcamentos")
    assert "aprovado (falta R$ 447,50)" in t

    envios = bot.nucleo.verificar_cobrancas(_hora_sp(8, 10))
    textos_cob = [r.texto for r in envios[0][1]]
    assert "ainda falta receber R$ 447,50" in textos_cob[0] and "/pago 1" in textos_cob[0]
    assert textos_cob[1].startswith("Olá, Dona Maria!") and "R$ 447,50" in textos_cob[1]
    assert bot.nucleo.verificar_cobrancas(_hora_sp(8, 11)) == []  # não repete

    _, t = bot("recebi o resto")  # sem dizer qual: pergunta, listando o que está em aberto
    assert "De qual orçamento" in t and "Nº 0001" in t
    rs, t = bot("/pago 1")
    assert "quitado" in t and any(r.arquivo and r.arquivo.endswith("recibo_0001_2.pdf") for r in rs)
    _, t = bot("/pago 1")
    assert "já está quitado" in t
    assert bot.nucleo.verificar_cobrancas(_hora_sp(20, 10)) == []  # pago: sem cobrança
    with bot.Sessao() as s:
        orc = s.query(Orcamento).one()
        assert orc.status == "pago" and [p.valor_centavos for p in orc.pagamentos] == [30000, 44750]
    rs, _ = bot("/recibo 1")
    assert rs[0].arquivo.endswith("recibo_0001_2.pdf")


def test_resumo_semanal(bot, monkeypatch):
    from app import config
    _cadastro_e_orcamento(bot)
    bot("/aprovado 1")
    bot("/pago 1 300")
    agora = _hora_sp(1, 10)
    dia = agora.astimezone(ZoneInfo("America/Sao_Paulo")).weekday()
    monkeypatch.setattr(config, "RESUMO_DIA", dia)
    monkeypatch.setattr(config, "LIMITE_MEI", 300)  # força o alerta do limite (R$ 300 recebidos = 100%)

    envios = bot.nucleo.verificar_resumos(agora)
    texto = envios[0][1][0].texto
    assert "Resumo da semana" in texto and "Orçamentos feitos: 1 (R$ 747,50)" in texto
    assert "Aprovados: 1" in texto and "Recebido: R$ 300,00" in texto and "A receber: R$ 447,50" in texto
    assert "limite anual do MEI" in texto
    assert bot.nucleo.verificar_resumos(agora + timedelta(hours=2)) == []  # uma vez por semana
    monkeypatch.setattr(config, "RESUMO_DIA", (dia + 1) % 7)
    assert bot.nucleo.verificar_resumos(_hora_sp(3, 10)) == []  # dia da semana errado: não manda
    _, t = bot("/resumo")
    assert "Resumo da semana" in t


def test_reativacao_de_cliente(bot):
    for msg in ["oi", "Frio Bom", "Técnico de ar condicionado", "pular", "pular", "pular", "pular", "pular", "limpeza 150"]:
        bot(msg)
    _, t = bot("/precos")
    assert "Limpeza / higienização (un) - R$ 150,00  🔁 a cada 6 meses" in t  # recorrência veio do catálogo
    _, t = bot("Orçamento pro Seu João, limpeza de 2 aparelhos")
    assert "Total: R$ 300,00" in t
    bot("ok")
    bot("/pago 1")

    assert bot.nucleo.verificar_reativacoes(_hora_sp(100, 10)) == []  # ainda não deu 6 meses
    envios = bot.nucleo.verificar_reativacoes(_hora_sp(190, 10))
    aviso, msg = (r.texto for r in envios[0][1])
    assert 'Faz 6 meses que você fez "Limpeza / higienização" para Seu João' in aviso
    assert msg.startswith("Olá, Seu João!") and "a limpeza do ar-condicionado" in msg and "Frio Bom" in msg
    assert bot.nucleo.verificar_reativacoes(_hora_sp(200, 10)) == []  # uma vez só

    _, t = bot("/retorno 1 0")
    assert "não vou mais lembrar" in t
    _, t = bot("/retorno 1 12")
    assert "12 meses" in t


def test_bot_desligado_por_dias_nao_manda_lembretes_em_rajada(bot):
    _cadastro_e_orcamento(bot)
    envios = bot.nucleo.verificar_followups(_hora_sp(10, 10))  # já passou do 1º e do 2º prazo
    assert len(envios) == 1 and "vale até" in envios[0][1][1].texto  # manda só o mais recente
    assert bot.nucleo.verificar_followups(_hora_sp(10, 11)) == []


def test_orcamento_muito_antigo_nao_recebe_lembrete(bot):
    _cadastro_e_orcamento(bot)
    assert bot.nucleo.verificar_followups(_hora_sp(90, 10)) == []  # 3 meses depois: encerra em silêncio
    assert bot.nucleo.verificar_followups(_hora_sp(91, 10)) == []


def test_reativacao_limitada_por_dia(bot):
    for msg in ["oi", "Frio Bom", "Técnico de ar condicionado", "pular", "pular", "pular", "pular", "pular", "limpeza 150"]:
        bot(msg)
    for nome in ["Ana", "Bruno", "Carla", "Davi", "Elisa"]:  # 5 clientes diferentes com limpeza paga
        bot(f"Orçamento pro {nome}, limpeza de 2 aparelhos")
        bot("ok")
    for n in range(1, 6):
        bot(f"/pago {n}")
    hoje = bot.nucleo.verificar_reativacoes(_hora_sp(190, 10))
    assert len(hoje) == 3  # limite diário
    assert bot.nucleo.verificar_reativacoes(_hora_sp(190, 15)) == []  # mesmo dia: nada
    assert len(bot.nucleo.verificar_reativacoes(_hora_sp(191, 10))) == 2  # no dia seguinte, os que faltavam
    assert bot.nucleo.verificar_reativacoes(_hora_sp(192, 10)) == []
