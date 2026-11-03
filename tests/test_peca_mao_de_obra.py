"""Peça e mão de obra separadas no resumo, no PDF e na página do cliente."""
import pymupdf

from app import links
from app.calculo import subtotais_por_tipo
from tests.apoio_web import montar
from tests.test_fluxo import IAFalsa


class IAOficina(IAFalsa):
    def interpretar(self, texto, tabela, rascunho=None, contexto=""):
        if texto.startswith("Gol do Seu Carlos"):
            vazio = super().interpretar("", tabela)
            return {**vazio, "intencao": "orcamento", "cliente": {"nome": "Seu Carlos", "endereco": None, "telefone": None},
                    "itens": [{"descricao": "Troca de pastilha", "quantidade": 1, "unidade": "un", "tipo": "servico",
                               "item_preco_id": None, "preco_informado": 80},
                              {"descricao": "Pastilha dianteira", "quantidade": 1, "unidade": "jogo", "tipo": "peca",
                               "item_preco_id": None, "preco_informado": 180}]}
        return super().interpretar(texto, tabela, rascunho, contexto)


def _texto_pdf(caminho):
    with pymupdf.open(caminho) as doc:
        return " ".join(p.get_text() for p in doc)


def test_orcamento_misto_mostra_dois_blocos(tmp_path):
    a = montar(tmp_path, ia=IAOficina())
    a.cadastrar()
    rs, t = a.bot("Gol do Seu Carlos: troca de pastilha 80 e a pastilha 180")
    assert "🔧 Mão de obra (R$ 80,00)" in t and "📦 Peças e materiais (R$ 180,00)" in t  # resumo do chat
    a.bot("ok")
    orc = a.orc()
    texto = _texto_pdf(orc.pdf_path)
    assert "MÃO DE OBRA" in texto and "PEÇAS E MATERIAIS" in texto
    assert "Subtotal mão de obra: R$ 80,00" in texto and "Subtotal peças e materiais: R$ 180,00" in texto
    with a.Sessao() as s:
        token = links.criar(s, a.prof(), "cliente", orc).token
        s.commit()
    pagina = a.web.get(f"/o/{token}").text
    assert "Peças e materiais" in pagina and "Subtotal mão de obra: R$ 80,00" in pagina


def test_orcamento_so_de_servico_fica_como_antes(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.orcamento()
    texto = _texto_pdf(a.orc().pdf_path)
    assert "PEÇAS E MATERIAIS" not in texto and "Subtotal mão de obra" not in texto
    assert all(i.tipo == "servico" for i in a.orc().itens)


def test_tipo_vem_da_tabela_quando_a_ia_nao_diz():
    from app.calculo import montar_rascunho
    tabela = {7: {"descricao": "Disjuntor 20A", "unidade": "un", "preco_centavos": 3500, "tipo": "peca"}}
    r = montar_rascunho({"itens": [{"descricao": "disjuntor", "quantidade": 2, "item_preco_id": 7}]}, tabela)
    assert r["itens"][0]["tipo"] == "peca"
    assert subtotais_por_tipo(r) == {"peca": 7000}


def test_editor_troca_o_tipo_do_item(tmp_path):
    a = montar(tmp_path)
    a.cadastrar()
    a.orcamento()
    token = a.nucleo.link_editor("telegram:42", 1).rsplit("/", 1)[1]
    orc = a.orc()
    form = {"descricao": [i.descricao for i in orc.itens], "quantidade": [str(i.quantidade) for i in orc.itens],
            "unidade": [i.unidade or "" for i in orc.itens], "item_preco_id": ["" for _ in orc.itens],
            "preco": [f"{i.preco_unit_centavos / 100:.2f}".replace(".", ",") for i in orc.itens],
            "tipo": ["peca"] + ["servico"] * (len(orc.itens) - 1)}
    a.web.post(f"/e/{token}", data=form)
    assert a.orc().itens[0].tipo == "peca"
