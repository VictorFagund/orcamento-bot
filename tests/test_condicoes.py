"""Condições por ramo: garantia, prazo, material..."""
from app import links
from app.calculo import juntar_condicoes
from app.catalogo import condicoes_da_profissao
from tests.apoio_web import PEDIDO, montar
from tests.test_fluxo import IAFalsa


class IAComGarantia(IAFalsa):
    def interpretar(self, texto, tabela, rascunho=None, contexto=""):
        dados = super().interpretar(texto.replace(" garantia de 6 meses nesse", ""), tabela, rascunho, contexto)
        if "garantia de 6 meses" in texto:
            dados = {**dados, "condicoes": [{"rotulo": "garantia", "texto": "6 meses"}]}
        return dados


def _gerar(a, pedido=PEDIDO):
    a.bot(pedido)
    a.bot("120")
    a.bot("12,50")
    return a.bot("ok")


def test_condicao_padrao_vai_para_todo_orcamento(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    _, t = a.bot("/condicao Garantia: 90 dias na mão de obra")
    assert "vai em todos os orçamentos" in t
    _gerar(a)
    assert a.orc().condicoes == [{"rotulo": "Garantia", "texto": "90 dias na mão de obra"}]
    with a.Sessao() as s:
        token = links.criar(s, a.prof(), "cliente", a.orc()).token
        s.commit()
    assert "90 dias na mão de obra" in a.web.get(f"/o/{token}").text


def test_condicao_dita_no_audio_vale_so_naquele(tmp_path):
    a = montar(tmp_path, ia=IAComGarantia())
    a.cadastrar()
    a.bot("/condicao Garantia: 90 dias")
    _gerar(a, PEDIDO + " garantia de 6 meses nesse")
    assert a.orc().condicoes == [{"rotulo": "Garantia", "texto": "6 meses"}]
    assert a.prof().condicoes_padrao == [{"rotulo": "Garantia", "texto": "90 dias"}]
    _gerar(a)
    assert a.orc(2).condicoes == [{"rotulo": "Garantia", "texto": "90 dias"}]


def test_juntar_condicoes_ignora_acento_e_caixa():
    padrao = [{"rotulo": "Garantia", "texto": "90 dias"}, {"rotulo": "Prazo", "texto": "A combinar"}]
    assert juntar_condicoes(padrao, [{"rotulo": "garantia", "texto": "6 meses"},
                                     {"rotulo": "Visita técnica", "texto": "R$ 50"}]) == [
        {"rotulo": "Garantia", "texto": "6 meses"}, {"rotulo": "Prazo", "texto": "A combinar"},
        {"rotulo": "Visita técnica", "texto": "R$ 50"}]


def test_comando_condicao_adiciona_e_remove(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.bot("/condicao Prazo: 2 dias úteis")
    rs, t = a.bot("/condicoes")
    assert "Prazo: 2 dias úteis" in t and rs[0].botoes  # sugestões da profissão como botões
    a.bot("/condicao remover prazo")
    assert a.prof().condicoes_padrao == []
    _, t = a.bot("/condicao remover Garantia")
    assert "Não achei" in t


def test_sugestoes_por_profissao():
    assert ("Peças", "Novas, com nota fiscal do fornecedor") in condicoes_da_profissao("Mecânico")
    assert condicoes_da_profissao("Eletricista")[0][0] == "Garantia"
    assert ("Prazo", "A combinar") in condicoes_da_profissao("Fotógrafo")


def test_editor_edita_as_condicoes_do_orcamento(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.bot("/condicao Garantia: 90 dias")
    _gerar(a)
    token = a.nucleo.link_editor("telegram:42", 1).rsplit("/", 1)[1]
    orc = a.orc()
    form = {"descricao": [i.descricao for i in orc.itens], "quantidade": [str(i.quantidade) for i in orc.itens],
            "unidade": [i.unidade or "" for i in orc.itens], "item_preco_id": [str(i.item_preco_id or "") for i in orc.itens],
            "preco": [f"{i.preco_unit_centavos / 100:.2f}".replace(".", ",") for i in orc.itens],
            "condicoes": "Prazo: 5 dias"}
    a.web.post(f"/e/{token}", data=form)
    assert a.orc().condicoes == [{"rotulo": "Prazo", "texto": "5 dias"}]  # garantia tirada só deste
