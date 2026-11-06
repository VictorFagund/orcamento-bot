"""Gera os PDFs: orçamento (em 3 modelos visuais, com a cor que o profissional escolher) e recibo."""
import os
from types import SimpleNamespace
from datetime import date, datetime, timedelta

from fpdf import FPDF
from fpdf.fonts import FontFace

from . import config, parcelas, pix
from .calculo import qtd_fmt, reais

FONTES = os.path.join(os.path.dirname(__file__), "fontes")
CINZA = (110, 110, 110)
TEXTO = (32, 34, 38)
SUAVE = (96, 100, 108)

# Cores que o profissional pode escolher para os documentos
CORES = {
    "azul": ("Azul", (31, 78, 121)),
    "verde": ("Verde", (34, 112, 74)),
    "vinho": ("Vinho", (128, 36, 52)),
    "laranja": ("Laranja", (196, 88, 22)),
    "roxo": ("Roxo", (88, 58, 140)),
    "grafite": ("Grafite", (44, 48, 54)),
}
MODELOS = {
    "classico": ("Clássico", "Cabeçalho com linha e tabela listrada. Sóbrio, cara de empresa."),
    "moderno": ("Moderno", "Faixa colorida no topo e total em destaque. Chama atenção no celular."),
    "simples": ("Simples", "Preto e branco com um toque de cor. Limpo e direto."),
}
MODELO_PADRAO, COR_PADRAO = "moderno", "azul"

_TROCAS = {"–": "-", "—": "-", "“": '"', "”": '"', "‘": "'", "’": "'", "…": "...", "•": "-", "™": "(TM)",
           "€": "EUR", " ": " "}


def _t(texto) -> str:
    """As fontes cobrem os acentos do português (latin-1). Símbolos comuns viram equivalentes simples e o que
    não tem equivalente (emoji etc.) é removido, em vez de aparecer como quadradinho."""
    texto = str(texto or "")
    for de, para in _TROCAS.items():
        texto = texto.replace(de, para)
    limpo = texto.encode("latin-1", "ignore").decode("latin-1")
    return " ".join(limpo.split()) if limpo != texto else limpo


def _clara(cor, k=.9):
    """Mistura a cor com branco (k = quanto de branco)."""
    return tuple(round(c + (255 - c) * k) for c in cor)


class _PDF(FPDF):
    def footer(self):
        self.set_y(-14)
        self.set_font("Hanken", "", 8)
        self.set_text_color(*CINZA)
        self.cell(0, 6, _t(getattr(self, "rodape", f"Orçamento feito em 1 minuto com {config.NOME_PRODUTO}")),
                  align="C")


MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


def _novo_pdf() -> "_PDF":
    pdf = _PDF(format="A4")
    pdf.add_font("Hanken", "", os.path.join(FONTES, "hanken-400.ttf"))
    pdf.add_font("Hanken", "B", os.path.join(FONTES, "hanken-800.ttf"))
    pdf.add_font("HankenM", "", os.path.join(FONTES, "hanken-600.ttf"))
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(True, margin=20)
    pdf.add_page()
    return pdf


def _caber(pdf, texto: str, largura: float, tamanho: float, minimo: float = 10) -> str:
    """Diminui a fonte até o texto caber na largura; se ainda não couber, corta com '...'."""
    texto = _t(texto)
    while pdf.get_string_width(texto) > largura and tamanho > minimo:
        tamanho -= 0.5
        pdf.set_font_size(tamanho)
    while pdf.get_string_width(texto) > largura and len(texto) > 4:
        texto = texto[:-4].rstrip() + "..."
    return texto


def _cor(prof):
    return CORES.get(getattr(prof, "cor_pdf", None) or COR_PADRAO, CORES[COR_PADRAO])[1]


def _logo(pdf, prof, x, y, h) -> float:
    """Desenha a logo e devolve a largura usada (0 se não houver)."""
    if prof.logo_path and os.path.exists(prof.logo_path):
        try:
            info = pdf.image(prof.logo_path, x=x, y=y, h=h)
            return info.rendered_width + 6
        except Exception:
            pass  # logo inválida não pode impedir o documento
    return 0


def _contato(prof) -> str:
    return "  ·  ".join(filter(None, [prof.telefone, prof.cidade]))


# ---------------------------------------------------------------- cabeçalhos
def _cabecalho(pdf, prof, titulo: str, linha1: str, linha2: str, cor=None):
    """Clássico: logo + dados do profissional à esquerda | título, número e data à direita, linha embaixo."""
    cor = cor or _cor(prof)
    x_texto = 15 + _logo(pdf, prof, 15, 14, 22)
    largura = 128 - x_texto
    pdf.set_xy(x_texto, 15)
    pdf.set_font("Hanken", "B", 17)
    pdf.set_text_color(*cor)
    pdf.cell(largura, 8, _caber(pdf, prof.nome, largura, 17))
    y = 24
    for linha in filter(None, [prof.profissao, _contato(prof)]):
        pdf.set_xy(x_texto, y)
        pdf.set_font("Hanken", "", 10)
        pdf.set_text_color(*SUAVE)
        pdf.cell(largura, 5, _caber(pdf, linha, largura, 10, 8))
        y += 5
    pdf.set_xy(130, 15)
    pdf.set_font("Hanken", "B", 14)
    pdf.set_text_color(*cor)
    pdf.cell(65, 8, _t(titulo), align="R")
    pdf.set_font("Hanken", "", 10)
    pdf.set_text_color(*SUAVE)
    pdf.set_xy(130, 24)
    pdf.cell(65, 5, _t(linha1), align="R")
    pdf.set_xy(130, 29)
    pdf.cell(65, 5, _t(linha2), align="R")
    pdf.set_draw_color(*cor)
    pdf.set_line_width(0.7)
    pdf.line(15, 40, 195, 40)
    return 46


def _cabecalho_moderno(pdf, prof, titulo, linha1, linha2, cor):
    """Faixa colorida de ponta a ponta com o nome em branco."""
    pdf.set_fill_color(*cor)
    pdf.rect(0, 0, 210, 44, style="F")
    x = 15
    if prof.logo_path and os.path.exists(prof.logo_path):
        pdf.set_fill_color(255, 255, 255)
        pdf.rect(15, 10, 26, 26, style="F", round_corners=True, corner_radius=3)
        x = 15 + _logo(pdf, prof, 17, 12, 22) + 2
    largura = 125 - x
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(x, 12)
    pdf.set_font("Hanken", "B", 19)
    pdf.cell(largura, 9, _caber(pdf, prof.nome, largura, 19, 12))
    y = 22
    for linha in filter(None, [prof.profissao, _contato(prof)]):
        pdf.set_xy(x, y)
        pdf.set_font("Hanken", "", 10)
        pdf.set_text_color(*_clara(cor, .78))
        pdf.cell(largura, 5, _caber(pdf, linha, largura, 10, 8))
        y += 5.5
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(125, 12)
    pdf.set_font("Hanken", "B", 15)
    pdf.cell(70, 9, _t(titulo), align="R")
    pdf.set_font("HankenM", "", 10)
    pdf.set_xy(125, 22)
    pdf.cell(70, 5, _t(linha1), align="R")
    pdf.set_text_color(*_clara(cor, .78))
    pdf.set_font("Hanken", "", 10)
    pdf.set_xy(125, 27.5)
    pdf.cell(70, 5, _t(linha2), align="R")
    return 54


def _cabecalho_simples(pdf, prof, titulo, linha1, linha2, cor):
    x = 15 + _logo(pdf, prof, 15, 15, 16)
    pdf.set_text_color(*TEXTO)
    pdf.set_xy(x, 15)
    pdf.set_font("Hanken", "B", 15)
    pdf.cell(110 - x, 7, _caber(pdf, prof.nome, 110 - x, 15))
    pdf.set_xy(x, 23)
    pdf.set_font("Hanken", "", 9.5)
    pdf.set_text_color(*SUAVE)
    pdf.cell(110 - x, 5, _caber(pdf, " · ".join(filter(None, [prof.profissao, _contato(prof)])), 110 - x, 9.5, 7.5))
    pdf.set_xy(15, 40)
    pdf.set_font("Hanken", "B", 30)
    pdf.set_text_color(*TEXTO)
    pdf.cell(100, 13, _t(titulo.capitalize()))
    pdf.set_fill_color(*cor)
    pdf.rect(15, 55, 14, 1.6, style="F")
    pdf.set_font("Hanken", "", 10)
    pdf.set_text_color(*SUAVE)
    pdf.set_xy(120, 42)
    pdf.cell(75, 5, _t(linha1), align="R")
    pdf.set_xy(120, 47.5)
    pdf.cell(75, 5, _t(linha2), align="R")
    return 64


# ---------------------------------------------------------------- blocos do orçamento
def _bloco_cliente(pdf, orc, y, cor, modelo):
    cli = orc.cliente
    linhas = [cli.nome if cli else "Não informado"]
    if cli and cli.endereco:
        linhas.append(cli.endereco)
    if cli and cli.telefone:
        linhas.append(f"Telefone: {cli.telefone}")
    if modelo == "moderno":
        altura = 9 + 5.2 * len(linhas)
        pdf.set_fill_color(*_clara(cor, .92))
        pdf.rect(15, y, 180, altura, style="F", round_corners=True, corner_radius=3)
        pdf.set_xy(20, y + 3)
        y_txt = y + 3
    else:
        pdf.set_xy(15, y)
        y_txt = y
    pdf.set_font("HankenM", "", 8.5)
    pdf.set_text_color(*cor)
    pdf.cell(0, 5, "PARA", new_x="LMARGIN", new_y="NEXT")
    x = 20 if modelo == "moderno" else 15
    for i, linha in enumerate(linhas):
        pdf.set_x(x)
        pdf.set_font("Hanken", "B" if i == 0 else "", 11.5 if i == 0 else 10)
        pdf.set_text_color(*(TEXTO if i == 0 else SUAVE))
        pdf.multi_cell(175 - (x - 15), 5.4, _t(linha), new_x="LMARGIN", new_y="NEXT")
    fim = pdf.get_y()
    return (y + 9 + 5.2 * len(linhas) + 6) if modelo == "moderno" else fim + 6


def _tabela(pdf, orc, cor, modelo):
    pdf.set_font("Hanken", "", 10)
    pdf.set_text_color(*TEXTO)
    if modelo == "classico":
        estilo = dict(headings_style=FontFace(family="HankenM", color=(255, 255, 255), fill_color=cor),
                      cell_fill_color=_clara(cor, .93), cell_fill_mode="ROWS", borders_layout="SINGLE_TOP_LINE")
        pdf.set_draw_color(*_clara(cor, .8))
    else:
        estilo = dict(headings_style=FontFace(family="HankenM", color=cor if modelo == "moderno" else SUAVE,
                                              size_pt=9),
                      borders_layout="HORIZONTAL_LINES", cell_fill_mode="NONE")
        pdf.set_draw_color(225, 227, 230)
        pdf.set_fill_color(255, 255, 255)  # a tabela herdaria a cor de preenchimento do bloco anterior
    pdf.set_line_width(0.25)
    grupos: dict[str, list] = {}
    for item in orc.itens:
        grupos.setdefault(getattr(item, "tipo", None) or "servico", []).append(item)
    misto = len(grupos) > 1
    for tipo in ("servico", "peca"):
        if tipo not in grupos:
            continue
        if misto:
            pdf.set_font("HankenM", "", 10.5)
            pdf.set_text_color(*cor)
            pdf.cell(0, 7, _t(("Mão de obra" if tipo == "servico" else "Peças e materiais").upper()),
                     new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Hanken", "", 10)
            pdf.set_text_color(*TEXTO)
        titulo_1 = "Serviço" if tipo == "servico" else "Peça / material"
        with pdf.table(col_widths=(92, 22, 33, 33), text_align=("LEFT", "CENTER", "RIGHT", "RIGHT"),
                       line_height=7.5, padding=(2, 2.5), **estilo) as tabela:
            linha = tabela.row()
            for titulo in (titulo_1, "Qtd", "Valor unit.", "Total"):
                linha.cell(_t(titulo.upper() if modelo != "classico" else titulo))
            for item in grupos[tipo]:
                linha = tabela.row()
                qtd = qtd_fmt(item.quantidade) + (f" {item.unidade}" if item.unidade and item.unidade != "un" else "")
                linha.cell(_t(item.descricao))
                linha.cell(_t(qtd))
                linha.cell(_t(reais(item.preco_unit_centavos)))
                linha.cell(_t(reais(item.subtotal_centavos)))
        if misto:
            pdf.set_font("Hanken", "", 9.5)
            pdf.set_text_color(*SUAVE)
            pdf.cell(0, 7, _t(f"Subtotal {'mão de obra' if tipo == 'servico' else 'peças e materiais'}: "
                              f"{reais(sum(i.subtotal_centavos for i in grupos[tipo]))}"), align="R",
                     new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)


def _totais(pdf, orc, cor, modelo):
    pdf.ln(4)
    desconto = orc.desconto_centavos or 0
    if desconto:
        if orc.desconto_percentual:
            rotulo = f"Desconto ({qtd_fmt(orc.desconto_percentual)}%)"
        else:
            rotulo = "Desconto" if desconto > 0 else "Acréscimo"
        sinal = "- " if desconto > 0 else "+ "
        pdf.set_font("Hanken", "", 10)
        pdf.set_text_color(*SUAVE)
        for txt in (f"Subtotal: {reais(orc.total_centavos + desconto)}", f"{rotulo}: {sinal}{reais(abs(desconto))}"):
            pdf.cell(0, 6, _t(txt), align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    total = reais(orc.total_centavos)
    if modelo == "moderno":
        y = pdf.get_y()
        pdf.set_fill_color(*cor)
        pdf.rect(115, y, 80, 16, style="F", round_corners=True, corner_radius=4)
        pdf.set_text_color(*_clara(cor, .75))
        pdf.set_font("HankenM", "", 9)
        pdf.set_xy(120, y + 2.5)
        pdf.cell(30, 5, "TOTAL")
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Hanken", "B", 17)
        pdf.set_xy(120, y + 4)
        pdf.cell(70, 9, _t(total), align="R")
        pdf.set_y(y + 22)
    elif modelo == "simples":
        y = pdf.get_y()
        pdf.set_draw_color(*TEXTO)
        pdf.set_line_width(0.5)
        pdf.line(115, y, 195, y)
        pdf.set_xy(115, y + 3)
        pdf.set_font("HankenM", "", 10)
        pdf.set_text_color(*SUAVE)
        pdf.cell(30, 8, "Total")
        pdf.set_font("Hanken", "B", 20)
        pdf.set_text_color(*TEXTO)
        pdf.set_xy(115, y + 2)
        pdf.cell(80, 10, _t(total), align="R")
        pdf.set_y(y + 18)
    else:
        pdf.set_font("Hanken", "B", 14)
        pdf.set_text_color(*cor)
        pdf.cell(0, 9, _t(f"TOTAL: {total}"), align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)


def _condicoes(pdf, orc, cor):
    condicoes = [(c["rotulo"], c["texto"]) for c in (getattr(orc, "condicoes", None) or [])]
    plano = getattr(orc, "parcelas", None)
    for rotulo, valor in (
        ("Observações", orc.observacoes),
        ("Forma de pagamento", orc.pagamento),
        ("Parcelas", parcelas.resumo(plano, orc.total_centavos) if plano else None),
        *condicoes,
        ("Validade", f"Este orçamento vale até {orc.validade:%d/%m/%Y}."),
    ):
        if not valor:
            continue
        pdf.set_font("HankenM", "", 9)
        pdf.set_text_color(*cor)
        pdf.cell(0, 5.5, _t(rotulo.upper()), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Hanken", "", 10)
        pdf.set_text_color(*TEXTO)
        pdf.multi_cell(0, 5.2, _t(valor), align="L", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2.5)


def _bloco_pix(pdf, prof, orc, caminho, cor, modelo):
    vez = parcelas.da_vez(orc)
    valor = vez["falta"] if vez else orc.total_centavos
    titulo = f"Pague com Pix ({vez['rotulo']}): {reais(valor)}" if vez else f"Pague com Pix: {reais(valor)}"
    codigo = pix.gerar_copia_e_cola(prof.pix_chave, prof.nome or "", prof.cidade or "BRASIL",
                                    valor, f"ORC{orc.numero:04d}")
    qr = pix.gerar_qrcode(codigo, caminho.replace(".pdf", "_pix.png"))
    if pdf.get_y() > 225:
        pdf.add_page()
    y = pdf.get_y() + 3
    if modelo == "moderno":
        pdf.set_fill_color(*_clara(cor, .92))
        pdf.rect(15, y, 180, 46, style="F", round_corners=True, corner_radius=4)
        pdf.set_fill_color(255, 255, 255)
        pdf.rect(18, y + 3, 40, 40, style="F", round_corners=True, corner_radius=2)
    else:
        pdf.set_draw_color(*(cor if modelo == "classico" else (200, 202, 206)))
        pdf.set_line_width(0.4)
        pdf.rect(15, y, 180, 46, round_corners=True, corner_radius=3, style="D")
    pdf.image(qr, x=19, y=y + 4, h=38)
    pdf.set_xy(64, y + 6)
    pdf.set_font("Hanken", "B", 12)
    pdf.set_text_color(*cor)
    pdf.cell(0, 6, _t(titulo), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(64)
    pdf.set_font("Hanken", "", 9.5)
    pdf.set_text_color(*SUAVE)
    pdf.multi_cell(126, 4.8, _t("Abra o app do seu banco, escolha Pix e aponte a câmera para o QR Code. "
                                "Ou copie o código abaixo (Pix copia e cola):"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(64)
    pdf.set_font("Courier", "", 7)
    pdf.set_text_color(*TEXTO)
    pdf.multi_cell(126, 3.4, codigo, wrapmode="CHAR", new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(y + 50)


def gerar_pdf(prof, orc, caminho: str, modelo: str | None = None, cor: str | None = None) -> str:
    """prof: Profissional, orc: Orcamento (com itens e cliente carregados). modelo/cor sobrescrevem os do perfil
    (usado nas prévias)."""
    modelo = modelo or getattr(prof, "modelo_pdf", None) or MODELO_PADRAO
    if modelo not in MODELOS:
        modelo = MODELO_PADRAO
    rgb = CORES.get(cor, (None, None))[1] or _cor(prof)
    pdf = _novo_pdf()
    rev = f" · rev. {orc.revisao}" if (orc.revisao or 1) > 1 else ""
    linha1, linha2 = f"Nº {orc.numero:04d}{rev}", f"{orc.criado_em:%d/%m/%Y}"
    if modelo == "moderno":
        y = _cabecalho_moderno(pdf, prof, "ORÇAMENTO", linha1, linha2, rgb)
    elif modelo == "simples":
        y = _cabecalho_simples(pdf, prof, "ORÇAMENTO", linha1, linha2, rgb)
    else:
        y = _cabecalho(pdf, prof, "ORÇAMENTO", linha1, f"Data: {linha2}", rgb) + 2
    y = _bloco_cliente(pdf, orc, y, rgb, modelo)
    pdf.set_y(y)
    _tabela(pdf, orc, rgb, modelo)
    _totais(pdf, orc, rgb, modelo)
    _condicoes(pdf, orc, rgb)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    if prof.pix_chave and orc.total_centavos > 0:
        _bloco_pix(pdf, prof, orc, caminho, rgb, modelo)
    pdf.output(caminho)
    return caminho


# ---------------------------------------------------------------- prévias para escolher o modelo
def orcamento_exemplo(prof):
    """Orçamento de mentira, com serviços da profissão, só para mostrar como o PDF fica."""
    from . import catalogo
    servicos = (catalogo.servicos_da_profissao(prof.profissao) or [])[:3]
    nomes = [d for d, _, _ in servicos] or ["Serviço principal", "Material", "Mão de obra"]
    precos = [12000, 4500, 8000]
    qtds = [1, 2, 1]
    itens = [SimpleNamespace(descricao=n, quantidade=q, unidade="un", preco_unit_centavos=p, subtotal_centavos=p * q)
             for n, q, p in zip(nomes, qtds, precos)]
    return SimpleNamespace(numero=1, revisao=1, criado_em=datetime.now(), itens=itens,
                           cliente=SimpleNamespace(nome="Maria Souza", endereco="Rua das Flores, 120", telefone=None),
                           total_centavos=sum(i.subtotal_centavos for i in itens), desconto_centavos=0,
                           desconto_percentual=None, observacoes=None, pagamento=prof.pagamento_padrao,
                           validade=date.today() + timedelta(days=config.VALIDADE_DIAS))


def gerar_previa(prof, pasta: str, modelo: str, cor: str | None = None) -> str:
    """PDF de exemplo -> imagem PNG da parte de cima da página (para mandar no chat)."""
    import pymupdf
    os.makedirs(pasta, exist_ok=True)
    cor = cor or getattr(prof, "cor_pdf", None) or COR_PADRAO
    caminho_pdf = os.path.join(pasta, f"previa_{modelo}_{cor}.pdf")
    gerar_pdf(prof, orcamento_exemplo(prof), caminho_pdf, modelo=modelo, cor=cor)
    png = caminho_pdf.replace(".pdf", ".png")
    with pymupdf.open(caminho_pdf) as doc:
        pag = doc[0]
        corte = pymupdf.Rect(0, 0, pag.rect.width, pag.rect.height * .72)
        pag.get_pixmap(dpi=110, clip=corte).save(png)
    return png


# ---------------------------------------------------------------- recibo
def gerar_recibo(prof, orc, pagamento, sequencia: int, caminho: str) -> str:
    """Recibo de um pagamento (total ou parcial) de um orçamento."""
    from num2words import num2words

    cor = _cor(prof)
    pdf = _novo_pdf()
    pdf.rodape = f"Recibo emitido com {config.NOME_PRODUTO}"
    data = pagamento.recebido_em
    _cabecalho(pdf, prof, "RECIBO", f"Nº {orc.numero:04d}-{sequencia}", f"Data: {data:%d/%m/%Y}", cor)

    valor = pagamento.valor_centavos
    pdf.set_xy(15, 52)
    pdf.set_font("Hanken", "B", 22)
    pdf.set_text_color(*cor)
    pdf.cell(0, 12, _t(f"Valor: {reais(valor)}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    extenso = num2words(valor / 100, lang="pt_BR", to="currency")
    cliente = orc.cliente.nome if orc.cliente else "cliente"
    servicos = "; ".join(f"{qtd_fmt(i.quantidade)}x {i.descricao}" for i in orc.itens)
    texto = (f"Recebi de {cliente} a importância de {reais(valor)} ({extenso}), referente a: {servicos}, "
             f"conforme orçamento Nº {orc.numero:04d}.")
    pdf.set_font("Hanken", "", 12)
    pdf.set_text_color(*TEXTO)
    pdf.multi_cell(0, 7, _t(texto), new_x="LMARGIN", new_y="NEXT")

    recebido, total = orc.recebido_centavos, orc.total_centavos
    if recebido < total or len(orc.pagamentos) > 1:
        pdf.ln(3)
        pdf.set_font("Hanken", "", 10)
        pdf.set_text_color(*SUAVE)
        situacao = "quitado" if recebido >= total else f"saldo a receber: {reais(total - recebido)}"
        pdf.multi_cell(0, 6, _t(f"Valor total do serviço: {reais(total)}. Recebido até esta data: {reais(recebido)} "
                                f"({situacao})."), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)
    pdf.set_font("Hanken", "", 12)
    pdf.set_text_color(*TEXTO)
    local = f"{prof.cidade}, " if prof.cidade else ""
    pdf.cell(0, 7, _t(f"{local}{data.day} de {MESES[data.month - 1]} de {data.year}."), new_x="LMARGIN", new_y="NEXT")

    pdf.ln(22)
    y = pdf.get_y()
    pdf.set_draw_color(60, 60, 60)
    pdf.set_line_width(0.3)
    pdf.line(55, y, 155, y)
    pdf.set_xy(15, y + 2)
    pdf.set_font("Hanken", "", 11)
    pdf.cell(0, 6, _t(prof.nome), align="C", new_x="LMARGIN", new_y="NEXT")
    if prof.profissao:
        pdf.set_font("Hanken", "", 9)
        pdf.set_text_color(*CINZA)
        pdf.cell(0, 5, _t(prof.profissao), align="C")

    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    pdf.output(caminho)
    return caminho
