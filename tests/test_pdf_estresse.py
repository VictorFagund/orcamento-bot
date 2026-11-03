"""PDF em situações extremas: muitos itens, textos longos, caracteres especiais, logo quebrada."""
import os
import subprocess
from datetime import date, datetime

import pytest

from app.db import Cliente, Orcamento, OrcamentoItem, Pagamento, Profissional
from app.pdf import gerar_pdf, gerar_recibo


def _paginas(caminho):
    try:
        saida = subprocess.run(["pdfinfo", caminho], capture_output=True, text=True).stdout
    except FileNotFoundError:
        pytest.skip("pdfinfo não instalado")
    return int(next(l.split()[-1] for l in saida.splitlines() if l.startswith("Pages")))


def _orc(n_itens, descricao="Troca de tomada", cliente="Dona Maria"):
    orc = Orcamento(numero=1, total_centavos=0, validade=date(2026, 11, 5), criado_em=datetime(2026, 10, 29),
                    cliente=Cliente(nome=cliente, endereco="Rua " + "muito longa " * 15, telefone="(46) 9"),
                    observacoes="Observação " * 80, pagamento="Pix ou cartão")
    for i in range(n_itens):
        orc.itens.append(OrcamentoItem(descricao=f"{descricao} {i + 1}", quantidade=1.5, unidade="m²",
                                       preco_unit_centavos=123456, subtotal_centavos=185184))
    orc.total_centavos = sum(i.subtotal_centavos for i in orc.itens)
    return orc


def _prof(tmp_path, **kw):
    base = dict(nome="Victor Elétrica", profissao="Eletricista", telefone="(46) 99999-0000",
                cidade="Santa Izabel do Oeste", pix_chave="+5546999990000")
    return Profissional(**{**base, **kw})


def test_muitos_itens_quebra_pagina_sem_erro(tmp_path):
    caminho = gerar_pdf(_prof(tmp_path), _orc(60), str(tmp_path / "grande.pdf"))
    assert _paginas(caminho) >= 2


def test_textos_longos_emoji_e_simbolos(tmp_path):
    prof = _prof(tmp_path, nome="⚡ Zé da Elétrica & Cia — “Rápido” ™ " + "N" * 80)
    orc = _orc(3, descricao="Instalação de ventilador 🌀 com controle — modelo “turbo” ½ " + "x" * 200,
               cliente="Dona 😊 Maria Ñandú")
    caminho = gerar_pdf(prof, orc, str(tmp_path / "estranho.pdf"))
    assert os.path.getsize(caminho) > 1000


def test_logo_invalida_nao_impede_o_pdf(tmp_path):
    logo = tmp_path / "logo.jpg"
    logo.write_bytes(b"isto nao e uma imagem")
    caminho = gerar_pdf(_prof(tmp_path, logo_path=str(logo)), _orc(2), str(tmp_path / "logo_ruim.pdf"))
    assert os.path.exists(caminho)


def test_valor_alto_e_recibo_com_valor_quebrado(tmp_path):
    prof = _prof(tmp_path)
    orc = _orc(1)
    orc.total_centavos = 98765432  # R$ 987.654,32
    pag = Pagamento(valor_centavos=12345678, recebido_em=datetime(2026, 10, 29))
    orc.pagamentos.append(pag)
    gerar_pdf(prof, orc, str(tmp_path / "alto.pdf"))
    caminho = gerar_recibo(prof, orc, pag, 1, str(tmp_path / "recibo.pdf"))
    texto = subprocess.run(["pdftotext", caminho, "-"], capture_output=True, text=True).stdout
    assert "R$ 123.456,78" in texto and "cento e vinte e três mil" in texto


def test_sem_pix_sem_cidade_sem_telefone(tmp_path):
    prof = Profissional(nome="Só o Nome")
    orc = _orc(1)
    orc.cliente = None
    caminho = gerar_pdf(prof, orc, str(tmp_path / "minimo.pdf"))
    assert os.path.exists(caminho)
