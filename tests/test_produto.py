"""Botões, visual do PDF, perfil e cadastro de uma vez com a IA separando os campos."""
import os

import pytest

from app.db import Profissional, iniciar_banco
from app.nucleo import Mensagem, Nucleo
from tests.test_fluxo import IAFalsa


class IAComCadastro(IAFalsa):
    """Como a IA real: separa os campos do checklist, em qualquer ordem."""

    def extrair_cadastro(self, texto):
        return {"nome": "Elétrica Silva", "profissao": "Eletricista", "telefone": "(46) 99999-0000",
                "cidade": "Realeza", "pagamento": "Pix ou cartão", "pix": "CPF 529.982.247-25"}


@pytest.fixture
def bot(tmp_path):
    Sessao = iniciar_banco(f"sqlite:///{tmp_path}/p.db")
    nucleo = Nucleo(Sessao, IAComCadastro(), pasta_arquivos=str(tmp_path / "arq"))

    def enviar(texto=None):
        rs = nucleo.processar("teste:1", Mensagem(texto=texto))
        return rs, "\n".join(r.texto for r in rs if r.texto)

    enviar.Sessao = Sessao
    return enviar


def cadastrar(bot):
    bot("oi")
    bot("Pix 529.982.247-25\nRealeza\n(46) 99999-0000\nEletricista\nElétrica Silva\nPix ou cartão")
    bot("pular")             # logo
    bot("tomada 40, chuveiro 120")
    bot("aceito")


def test_checklist_em_qualquer_ordem_vai_para_os_campos_certos(bot):
    bot("oi")
    rs, t = bot("Pix 529.982.247-25\nRealeza\n(46) 99999-0000\nEletricista\nElétrica Silva\nPix ou cartão")
    assert "Anotei assim" in t and "Cidade: Realeza" in t and "Pagamento: Pix ou cartão" in t
    assert any(r.botoes == [[("⏭️ Pular", "pular")]] for r in rs)  # próxima pergunta (logo) tem botão de pular
    with bot.Sessao() as s:
        prof = s.query(Profissional).one()
        assert (prof.profissao, prof.telefone, prof.cidade, prof.pix_chave, prof.estado) == (
            "Eletricista", "(46) 99999-0000", "Realeza", "52998224725", "CADASTRO_LOGO")


def test_resumo_tem_botoes_e_gerar_pelo_botao_funciona(bot):
    cadastrar(bot)
    rs, t = bot("Orçamento pra Dona Maria, trocar 6 tomadas, 2 chuveiros e 15 metros de fiação")
    bot("120")
    rs, t = bot("12,50")
    assert "Confira o orçamento" in t and "Total: R$" in t
    assert rs[-1].botoes[0][0] == ("✅ Está certo, gerar PDF", "ok")
    _, t = bot("/corrigir")
    assert "são 8 tomadas" in t
    rs, t = bot("ok")  # o mesmo que tocar no botão
    assert "Nº 0001 pronto" in t
    pos = [r for r in rs if r.botoes][0].botoes
    assert ("👍 Cliente aprovou", "/aprovado 1") in pos[0] and ("💰 Já recebi", "/pago 1") in pos[1]


def test_escolher_modelo_e_cor_do_pdf(bot):
    cadastrar(bot)
    rs, _ = bot("/modelo")
    previas = [r for r in rs if r.imagem]
    assert len(previas) == 3 and all(os.path.exists(r.imagem) for r in previas)
    assert previas[0].botoes[0][0][1].startswith("/modelo ")
    _, t = bot("/modelo simples")
    assert "modelo Simples" in t
    rs, t = bot("/cor verde")
    assert "Cor verde salva" in t and rs[0].imagem
    with bot.Sessao() as s:
        prof = s.query(Profissional).one()
        assert (prof.modelo_pdf, prof.cor_pdf) == ("simples", "verde")
    # o orçamento sai no modelo escolhido sem erro
    bot("Orçamento pra Dona Maria, trocar 6 tomadas, 2 chuveiros e 15 metros de fiação")
    bot("120")
    bot("12,50")
    rs, _ = bot("ok")
    assert any(r.arquivo and r.arquivo.endswith(".pdf") for r in rs)


def test_perfil_mostra_e_corrige_dados(bot):
    cadastrar(bot)
    _, t = bot("/perfil")
    assert "Cidade: Realeza" in t and "/cidade" in t
    _, t = bot("/cidade Realeza - PR")
    assert "Cidade atualizado: Realeza - PR" in t
    _, t = bot("/pagamento")
    assert "Ex: /pagamento" in t
    with bot.Sessao() as s:
        assert s.query(Profissional).one().cidade == "Realeza - PR"


@pytest.mark.parametrize("modelo", ["classico", "moderno", "simples"])
def test_todos_os_modelos_geram_pdf_com_desconto_e_pix(tmp_path, modelo):
    from types import SimpleNamespace
    from app.pdf import gerar_pdf, orcamento_exemplo
    prof = SimpleNamespace(nome="Elétrica Silva", profissao="Eletricista", telefone="(46) 99999-0000",
                           cidade="Realeza", pix_chave="52998224725", logo_path=None,
                           pagamento_padrao="Pix", modelo_pdf=modelo, cor_pdf="vinho")
    orc = orcamento_exemplo(prof)
    orc.desconto_centavos, orc.desconto_percentual = 1000, None
    orc.total_centavos -= 1000
    orc.observacoes = "Prazo de 2 dias úteis — material incluso"
    caminho = gerar_pdf(prof, orc, str(tmp_path / f"{modelo}.pdf"))
    assert os.path.getsize(caminho) > 2000
