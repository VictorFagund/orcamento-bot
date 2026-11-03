"""Adaptador do Telegram com mensagens simuladas (não usa a rede nem precisa de token)."""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import bot_telegram
from app.db import iniciar_banco
from app.nucleo import Nucleo
from tests.test_fluxo import IAFalsa, _hora_sp


@pytest.fixture
def tg(tmp_path, monkeypatch):
    monkeypatch.setattr(bot_telegram, "nucleo",
                        Nucleo(iniciar_banco(f"sqlite:///{tmp_path}/tg.db"), IAFalsa(), str(tmp_path / "arq")))

    def mensagem(texto=None, voz=None, foto=None, encaminhada_de=None, usuario=42):
        def arquivo(conteudo):
            return SimpleNamespace(get_file=AsyncMock(return_value=SimpleNamespace(
                download_as_bytearray=AsyncMock(return_value=bytearray(conteudo)))))
        origem = SimpleNamespace(sender_user=SimpleNamespace(full_name=encaminhada_de)) if encaminhada_de else None
        msg = SimpleNamespace(text=texto, caption=None, voice=arquivo(voz) if voz else None, audio=None,
                              photo=[arquivo(foto)] if foto else [], forward_origin=origem, chat_id=usuario,
                              reply_text=AsyncMock(), reply_document=AsyncMock())
        update = SimpleNamespace(effective_message=msg, effective_user=SimpleNamespace(id=usuario))
        bot = SimpleNamespace(send_chat_action=AsyncMock(), send_message=AsyncMock(), send_document=AsyncMock(),
                              send_photo=AsyncMock())
        asyncio.run(bot_telegram.ao_receber(update, SimpleNamespace(bot=bot)))
        textos = [c.args[0] for c in msg.reply_text.call_args_list] + [c.args[1] for c in bot.send_message.call_args_list]
        docs = [c.args[1].name for c in bot.send_document.call_args_list]
        return "\n".join(textos), docs

    return mensagem


def _cadastro(tg):
    for m in ["oi", "Victor Elétrica", "Eletricista", "pular", "pular", "Pix", "pular", "pular", "tomada 40, chuveiro 120"]:
        tg(m)


def test_texto_voz_e_pdf(tg):
    t, _ = tg("oi")
    assert "qual o seu nome" in t
    _cadastro(tg)
    # áudio: o bot baixa o arquivo do Telegram e manda para a transcrição
    t, _ = tg(voz="Orçamento pra Dona Maria, trocar 6 tomadas, 2 chuveiros e 15 metros de fiação".encode())
    assert 'Entendi: "Orçamento pra Dona Maria' in t
    tg("120")
    tg("12,50")
    t, docs = tg("ok")
    assert len(docs) == 1 and docs[0].endswith("orcamento_0001.pdf") and "Nº 0001 pronto" in t


def test_foto_vira_logo(tg):
    _cadastro(tg)
    t, _ = tg(foto=b"\xff\xd8\xff fake jpeg")
    assert "Logo salva" in t


def test_mensagem_encaminhada_identifica_o_cliente(tg):
    _cadastro(tg)
    tg("Orçamento pra Dona Maria, trocar 6 tomadas, 2 chuveiros e 15 metros de fiação")
    tg("120")
    tg("12,50")
    tg("ok")
    t, _ = tg("Consegue fazer por 700?", encaminhada_de="Maria Souza")
    assert "Em qual orçamento" in t  # tratou como pedido do cliente


def test_usuarios_diferentes_nao_se_misturam(tg):
    _cadastro(tg)
    t, _ = tg("oi", usuario=99)
    assert "qual o seu nome" in t  # outro usuário começa o próprio cadastro


def test_audio_avisa_na_hora_e_falha_de_rede_nao_deixa_sem_resposta(tg):
    _cadastro(tg)
    t, _ = tg(voz="Orçamento pra Dona Maria, trocar 6 tomadas".encode())
    assert t.startswith("🎧 Recebi o áudio")

    msg = SimpleNamespace(text=None, caption=None, audio=None, photo=[], forward_origin=None, chat_id=42,
                          voice=SimpleNamespace(get_file=AsyncMock(side_effect=TimeoutError("Timed out"))),
                          reply_text=AsyncMock(), reply_document=AsyncMock())
    update = SimpleNamespace(effective_message=msg, effective_user=SimpleNamespace(id=42))
    asyncio.run(bot_telegram.ao_receber(update, SimpleNamespace(bot=SimpleNamespace(send_chat_action=AsyncMock()))))
    assert "Pode mandar de novo" in msg.reply_text.call_args_list[-1].args[0]


def test_textos_longos_sao_divididos():
    texto = "\n".join(f"linha {i} " + "x" * 50 for i in range(200))
    pedacos = bot_telegram.partes(texto)
    assert all(len(p) <= 4000 for p in pedacos) and len(pedacos) > 1
    assert "\n".join(pedacos).replace("\n", "") == texto.replace("\n", "")
    assert bot_telegram.partes("") == [] and bot_telegram.partes("oi") == ["oi"]


def test_rotina_periodica_envia_para_o_chat_certo(tg):
    _cadastro(tg)
    tg("Orçamento pra Dona Maria, trocar 6 tomadas, 2 chuveiros e 15 metros de fiação")
    tg("120")
    tg("12,50")
    tg("ok")
    bot = SimpleNamespace(send_message=AsyncMock())
    asyncio.run(bot_telegram.enviar_rotinas(bot, _hora_sp(4, 10)))  # 4 dias sem resposta
    chats = {c.args[0] for c in bot.send_message.call_args_list}
    assert chats == {42} and "sem resposta há" in bot.send_message.call_args_list[0].args[1]


def test_usuario_que_bloqueou_o_bot_nao_trava_os_outros(tg):
    _cadastro(tg)
    tg("Orçamento pra Dona Maria, trocar 6 tomadas, 2 chuveiros e 15 metros de fiação")
    tg("120")
    tg("12,50")
    tg("ok")
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError("Forbidden: bot was blocked")))
    asyncio.run(bot_telegram.enviar_rotinas(bot, _hora_sp(4, 10)))  # não levanta erro
