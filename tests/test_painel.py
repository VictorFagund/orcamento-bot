"""Painel do profissional: números do mês, filtros, busca, ações, PDF e planilha."""
from datetime import date, datetime, timedelta

from app import links
from app.db import Link, Orcamento
from app.web.painel import numeros
from tests.apoio_web import montar


def _painel(a):
    _, t = a.bot("/painel")
    assert "30 dias" in t
    return "/d/" + t.split("/d/")[1].split()[0]


def _com_dois(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.orcamento()  # Nº 1, Dona Maria
    a.orcamento()  # Nº 2
    return a, _painel(a)


def test_link_do_painel_vale_30_dias(tmp_path):
    a, url = _com_dois(tmp_path)
    with a.Sessao() as s:
        link = s.query(Link).filter_by(tipo="painel").one()
        assert timedelta(days=29) < link.expira_em - datetime.now() <= timedelta(days=30)


def test_painel_mostra_numeros_e_lista(tmp_path):
    a, url = _com_dois(tmp_path)
    total = a.orc(1).total_centavos
    r = a.web.get(url)
    assert r.status_code == 200
    assert "Nº 0001" in r.text and "Nº 0002" in r.text and "Dona Maria" in r.text
    assert "2 orçamentos" in r.text
    assert "Em aberto" in r.text


def test_recebi_parte_registra_e_avisa_no_chat(tmp_path):
    a, url = _com_dois(tmp_path)
    r = a.web.post(url + "/acao", data={"numero": "1", "acao": "parcial", "valor": "100", "f": "todos"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert a.orc(1).recebido_centavos == 10000 and a.orc(1).status == "aprovado"
    canal, respostas = a.avisos[-1]
    assert canal == "telegram:42" and any(x.arquivo for x in respostas)  # recibo no chat
    pagina = a.web.get(r.headers["location"]).text
    assert "recibo foi para o seu chat" in pagina
    assert "falta" in pagina


def test_valor_parcial_invalido_nao_registra(tmp_path):
    a, url = _com_dois(tmp_path)
    r = a.web.post(url + "/acao", data={"numero": "1", "acao": "parcial", "valor": "abc"}, follow_redirects=True)
    assert "Digite o valor" in r.text
    assert a.orc(1).recebido_centavos == 0


def test_aprovado_recusado_e_pago(tmp_path):
    a, url = _com_dois(tmp_path)
    a.web.post(url + "/acao", data={"numero": "1", "acao": "pago"})
    a.web.post(url + "/acao", data={"numero": "2", "acao": "recusado"})
    assert a.orc(1).status == "pago" and a.orc(2).status == "recusado"
    pagos = a.web.get(url + "?f=pagos").text
    assert "Nº 0001" in pagos and "Nº 0002" not in pagos
    recusados = a.web.get(url + "?f=recusados").text
    assert "Nº 0002" in recusados and "Nº 0001" not in recusados


def test_acao_em_orcamento_de_outro_profissional_e_recusada(tmp_path):
    a, url = _com_dois(tmp_path)
    a.cadastrar(canal="telegram:99")
    a.orcamento(canal="telegram:99")
    _, t = a.bot("/painel", canal="telegram:99")
    outro = "/d/" + t.split("/d/")[1].split()[0]
    assert a.web.post(outro + "/acao", data={"numero": "7", "acao": "pago"}).status_code == 400
    a.web.post(outro + "/acao", data={"numero": "1", "acao": "pago"})
    assert a.orc(1).status == "enviado"  # o Nº 1 do primeiro profissional não mudou


def test_busca_por_nome_e_numero(tmp_path):
    a, url = _com_dois(tmp_path)
    assert "Nº 0002" in a.web.get(url + "?q=maria").text
    so_um = a.web.get(url + "?q=n%C2%BA%202").text
    assert "Nº 0002" in so_um and "Nº 0001" not in so_um
    assert "Nenhum orçamento neste filtro" in a.web.get(url + "?q=zezinho").text


def test_pdf_e_planilha(tmp_path):
    a, url = _com_dois(tmp_path)
    r = a.web.get(url + "/pdf/1")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert a.web.get(url + "/pdf/9").status_code == 404
    a.web.post(url + "/acao", data={"numero": "1", "acao": "parcial", "valor": "50,5"})
    csv = a.web.get(url + "/planilha.csv")
    assert csv.headers["content-type"].startswith("text/csv")
    linhas = csv.content.decode("utf-8-sig").splitlines()
    assert linhas[0].startswith("Número;Data;Cliente")
    assert ";50,50;" in linhas[1]


def test_link_invalido_ou_de_outro_tipo(tmp_path):
    a, url = _com_dois(tmp_path)
    assert a.web.get("/d/nao-existe").status_code == 404
    _, t = a.bot("/perfilweb")
    token_perfil = t.split("/p/")[1].split()[0]
    assert a.web.get(f"/d/{token_perfil}").status_code == 404


def test_sem_orcamentos_mostra_orientacao(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    assert "ainda não tem orçamentos" in a.web.get(_painel(a)).text


def test_numeros_do_mes():
    class C:  # objetos mínimos no formato do banco
        def __init__(self, **kw): self.__dict__.update(kw)
    nov, out = datetime(2026, 11, 5), datetime(2026, 10, 20)
    maria = C(nome="Maria")
    o1 = C(criado_em=nov, status="pago", total_centavos=50000, pagamentos=[C(valor_centavos=50000, recebido_em=nov)],
           cliente=maria, recebido_centavos=50000, saldo_centavos=0)
    o2 = C(criado_em=nov, status="enviado", total_centavos=20000, pagamentos=[], cliente=None,
           recebido_centavos=0, saldo_centavos=20000)
    o3 = C(criado_em=out, status="aprovado", total_centavos=30000, pagamentos=[C(valor_centavos=10000, recebido_em=nov)],
           cliente=maria, recebido_centavos=10000, saldo_centavos=20000)
    n = numeros([o1, o2, o3], date(2026, 11, 1))
    assert (n["orcados"], n["fechados"], n["taxa"]) == (2, 1, 50)
    assert n["recebido"] == "R$ 600,00"  # inclui o que entrou em novembro de um orçamento de outubro
    assert n["a_receber"] == "R$ 200,00" and n["a_receber_n"] == 1
    assert n["clientes"] == [("Maria", "R$ 600,00")]


def test_pedido_livre_abre_o_painel(tmp_path):
    from tests.test_roteador import IARoteadora
    IARoteadora.rotas["quero ver como tão minhas vendas"] = {
        "acoes": [{"comando": "/painel", "argumento": None}], "pergunta": None, "opcoes": []}
    a = montar(tmp_path, ia=IARoteadora())
    a.cadastrar()
    _, t = a.bot("quero ver como tão minhas vendas")
    assert "/d/" in t
