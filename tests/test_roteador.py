"""Pedidos livres (fora do padrão) viram uma rotina do bot, ou uma pergunta com botões; nunca um beco sem saída."""
from app.db import Evento
from tests.apoio_web import montar
from tests.test_fluxo import IAFalsa


class IARoteadora(IAFalsa):
    rotas = {
        "meu nome tá errado, é Elétrica Silva, e a cidade é Realeza - PR": {
            "acoes": [{"comando": "/nome", "argumento": "Elétrica Silva"},
                      {"comando": "/cidade", "argumento": "Realeza - PR"}], "pergunta": None, "opcoes": []},
        "deixa o orçamento mais bonito": {
            "acoes": [{"comando": "/modelo", "argumento": None}], "pergunta": None, "opcoes": []},
        "quero dar garantia de 90 dias em tudo": {
            "acoes": [{"comando": "/condicao", "argumento": "Garantia: 90 dias"}], "pergunta": None, "opcoes": []},
        "apaga tudo": {
            "acoes": [{"comando": "/apagarconta", "argumento": None}], "pergunta": None, "opcoes": []},
        "hmm aquilo lá": {
            "acoes": [], "pergunta": "Você quer mudar seus dados ou um orçamento?",
            "opcoes": ["/perfil", "/orcamentos", "/inventado"]},
    }

    def rotear(self, texto, contexto=""):
        if texto == "muda pra azul":
            assert "orçamento aberto" in contexto
            return {"acoes": [{"comando": "/cor", "argumento": "azul"}], "pergunta": None, "opcoes": []}
        if texto == "cai":
            raise RuntimeError("IA fora do ar")
        return self.rotas.get(texto, {"acoes": [], "pergunta": None, "opcoes": []})


def _pronto(tmp_path):
    a = montar(tmp_path, ia=IARoteadora())
    a.cadastrar()
    return a


def _eventos(a, tipo):
    with a.Sessao() as s:
        return [e.dados for e in s.query(Evento).filter_by(tipo=tipo)]


def test_varios_dados_numa_frase(tmp_path):
    a = _pronto(tmp_path)
    _, t = a.bot("meu nome tá errado, é Elétrica Silva, e a cidade é Realeza - PR")
    assert "Nome atualizado: Elétrica Silva" in t and "Cidade atualizado: Realeza - PR" in t
    p = a.prof()
    assert (p.nome, p.cidade) == ("Elétrica Silva", "Realeza - PR")
    assert _eventos(a, "roteado") == [{"comandos": ["/nome Elétrica Silva", "/cidade Realeza - PR"]}]


def test_pedido_vago_abre_a_rotina(tmp_path):
    a = _pronto(tmp_path)
    rs, _ = a.bot("deixa o orçamento mais bonito")
    assert any(r.imagem for r in rs)  # prévias dos modelos


def test_condicao_fixa_por_frase(tmp_path):
    a = _pronto(tmp_path)
    a.bot("quero dar garantia de 90 dias em tudo")
    assert a.prof().condicoes_padrao == [{"rotulo": "Garantia", "texto": "90 dias"}]


def test_nunca_apaga_conta_por_roteamento(tmp_path):
    a = _pronto(tmp_path)
    rs, _ = a.bot("apaga tudo")
    assert a.prof().nome == "Victor Elétrica"
    assert rs[0].botoes  # caiu na pergunta com opções
    assert _eventos(a, "nao_entendido") == [{"texto": "apaga tudo"}]


def test_duvida_vira_pergunta_com_botoes(tmp_path):
    a = _pronto(tmp_path)
    rs, t = a.bot("hmm aquilo lá")
    assert "mudar seus dados ou um orçamento" in t
    assert [b[0][1] for b in rs[-1].botoes] == ["/perfil", "/orcamentos"]  # comando inventado some


def test_ia_do_roteador_fora_do_ar_ainda_oferece_caminho(tmp_path):
    a = _pronto(tmp_path)
    rs, t = a.bot("cai")
    assert "Não entendi como orçamento" in t
    assert [b[0][1] for b in rs[-1].botoes] == ["/exemplo", "/perfil", "/orcamentos", "/menu"]


def test_pedido_livre_com_orcamento_aberto_volta_ao_resumo(tmp_path):
    a = _pronto(tmp_path)
    a.bot("Orçamento pra Dona Maria, trocar 6 tomadas, 2 chuveiros e 15 metros de fiação")
    a.bot("120")
    a.bot("12,50")
    rs, t = a.bot("muda pra azul")
    assert a.prof().cor_pdf == "azul"
    assert a.prof().estado == "CONFIRMANDO"
    assert rs[-1].botoes and "Dona Maria" in rs[-1].texto  # o resumo do orçamento aberto volta


# ---------------------------------------------------------------- dúvidas fora do script
class IADuvidas(IARoteadora):
    def rotear(self, texto, contexto=""):
        self.ultimo_contexto = contexto
        if texto == "da pra usar no whatsapp?":
            return {"acoes": [], "resposta": "Por enquanto é no Telegram; o cliente recebe pelo WhatsApp.",
                    "pergunta": None, "opcoes": ["/exemplo", "/inventado"]}
        if texto == "posso colocar minha logo?":
            return {"acoes": [{"comando": "/perfil", "argumento": None}], "resposta": "Pode! Mande a foto dela.",
                    "pergunta": None, "opcoes": []}
        return super().rotear(texto, contexto)


def test_duvida_sobre_o_bot_tem_resposta_direta(tmp_path):
    a = montar(tmp_path, ia=IADuvidas())
    a.cadastrar()
    rs, t = a.bot("da pra usar no whatsapp?")
    assert t == "Por enquanto é no Telegram; o cliente recebe pelo WhatsApp."
    assert [b[0][1] for b in rs[0].botoes] == ["/exemplo"]  # opção inventada é descartada
    assert _eventos(a, "duvida") == [{"texto": "da pra usar no whatsapp?"}]
    assert _eventos(a, "nao_entendido") == []
    _, t = a.bot("posso colocar minha logo?")  # resposta e rotina juntas
    assert t.startswith("Pode! Mande a foto dela.") and "Seus dados" in t


def test_roteador_conhece_os_orcamentos_recentes(tmp_path):
    a = montar(tmp_path, ia=IADuvidas())
    a.cadastrar()
    a.bot("o cliente aprovou o da maria")
    assert "Ainda não há orçamentos" in a.nucleo.ia.ultimo_contexto
    a.orcamento()
    a.bot("o cliente aprovou o da maria")
    assert "Nº 0001 - Dona Maria" in a.nucleo.ia.ultimo_contexto and "(enviado)" in a.nucleo.ia.ultimo_contexto


def test_limite_da_ia_avisa_para_esperar(tmp_path):
    class Limite(Exception):
        status_code = 429

    class IASemCota(IARoteadora):
        def interpretar(self, *a, **kw):
            raise Limite("Rate limit reached")

    a = montar(tmp_path, ia=IARoteadora())
    a.cadastrar()
    a.nucleo.ia = IASemCota()
    _, t = a.bot("orçamento pro João, 2 tomadas")
    assert "alguns minutos" in t and "Ops" not in t
