"""Adaptador do Telegram: recebe a mensagem, entrega ao núcleo e devolve as respostas.

Rodar:  python bot_telegram.py
"""
import asyncio
import logging

import httpx
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

from app import config
from app.db import iniciar_banco
from app.ia import IAOpenAI
from app.nucleo import Mensagem, Nucleo

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

nucleo: Nucleo | None = None  # criado em main(); nos testes, é substituído por um núcleo com IA simulada
LIMITE_TELEGRAM = 4000  # o Telegram recusa mensagens acima de 4096 caracteres


def partes(texto: str, limite: int = LIMITE_TELEGRAM) -> list[str]:
    """Divide textos longos em pedaços, de preferência em quebras de linha."""
    pedacos = []
    while len(texto) > limite:
        corte = texto.rfind("\n", 0, limite)
        corte = corte if corte > limite // 2 else limite
        pedacos.append(texto[:corte])
        texto = texto[corte:].lstrip("\n")
    return pedacos + [texto] if texto else pedacos


def teclado(botoes):
    """Botões do núcleo -> teclado do Telegram. O botão devolve, ao ser tocado, o texto que ele "diz" ao bot."""
    if not botoes:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(rotulo, callback_data=valor[:64]) for rotulo, valor in linha]
                                 for linha in botoes])


async def enviar(bot, chat_id, respostas):
    for r in respostas:
        markup = teclado(r.botoes)
        if r.imagem:
            with open(r.imagem, "rb") as f:
                await bot.send_photo(chat_id, f, caption=(r.texto or "")[:1000] or None, reply_markup=markup)
            continue
        pedacos = partes(r.texto or "")
        for i, pedaco in enumerate(pedacos):
            # os botões vão na última parte da mensagem
            await bot.send_message(chat_id, pedaco, reply_markup=markup if i == len(pedacos) - 1 else None)
        if r.arquivo:
            with open(r.arquivo, "rb") as f:
                await bot.send_document(chat_id, f, reply_markup=markup if not pedacos else None)


async def ao_tocar_botao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toque num botão = o profissional "disse" o texto do botão."""
    consulta = update.callback_query
    await consulta.answer()
    try:  # tira os botões da mensagem tocada, para não tocar duas vezes no mesmo
        await consulta.edit_message_reply_markup(None)
    except Exception:
        pass
    chat_id = consulta.message.chat_id
    try:
        await context.bot.send_chat_action(chat_id, "typing")
        respostas = await asyncio.to_thread(nucleo.processar, f"telegram:{update.effective_user.id}",
                                            Mensagem(texto=consulta.data))
        await enviar(context.bot, chat_id, respostas)
    except Exception:
        logging.exception("Falha ao processar botão de %s", update.effective_user.id)
        await context.bot.send_message(chat_id, "⚠️ Tive um problema de conexão. Pode tocar de novo?")


async def ao_receber(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg is None:
        return
    entrada = Mensagem(texto=msg.text or msg.caption)

    # Mensagem encaminhada (ex: o profissional repassa o pedido do cliente)
    origem = msg.forward_origin
    if origem is not None:
        remetente = getattr(origem, "sender_user", None)
        entrada.encaminhada_de = (remetente.full_name if remetente else getattr(origem, "sender_user_name", "")) or ""

    try:
        if msg.voice or msg.audio:
            # Transcrever + interpretar leva alguns segundos: avisa logo para o profissional não achar que travou
            await msg.reply_text("🎧 Recebi o áudio, já te respondo...")
            arquivo = await (msg.voice or msg.audio).get_file()
            entrada.audio = bytes(await arquivo.download_as_bytearray())
            entrada.audio_nome = "audio.ogg" if msg.voice else (msg.audio.file_name or "audio.mp3")
        elif msg.photo:
            arquivo = await msg.photo[-1].get_file()  # maior resolução
            entrada.foto = bytes(await arquivo.download_as_bytearray())

        await context.bot.send_chat_action(msg.chat_id, "typing")
        # O núcleo é síncrono (IA + banco); roda numa thread para não travar o bot
        respostas = await asyncio.to_thread(nucleo.processar, f"telegram:{update.effective_user.id}", entrada)
        await enviar(context.bot, msg.chat_id, respostas)
    except Exception:  # rede caiu, Telegram lento... o profissional não pode ficar sem resposta
        logging.exception("Falha ao processar mensagem de %s", update.effective_user.id)
        try:
            await msg.reply_text("⚠️ Tive um problema de conexão e não consegui processar. Pode mandar de novo?")
        except Exception:
            logging.exception("Falha também ao avisar o erro")
        return


async def enviar_rotinas(bot, agora=None):
    """Uma rodada das rotinas: lembretes de resposta e cobrança, resumo semanal e reativação de clientes."""
    envios = await asyncio.to_thread(nucleo.rotina_periodica, agora, "telegram:")
    for canal_id, respostas in envios:
        chat_id = int(canal_id.split(":", 1)[1])  # em conversa privada, chat_id = id do usuário
        try:
            await enviar(bot, chat_id, respostas)
        except Exception:  # ex: o usuário bloqueou o bot; não pode impedir os outros envios
            logging.exception("Falha ao enviar para %s", chat_id)


async def lembretes_periodicos(app: Application):
    while True:
        try:
            await enviar_rotinas(app.bot)
        except Exception:
            logging.exception("Erro nas rotinas periódicas")
        await asyncio.sleep(30 * 60)


COMANDOS = [("menu", "O que dá pra fazer"), ("orcamentos", "Últimos orçamentos"), ("precos", "Minha tabela de preços"),
            ("areceber", "O que falta receber"), ("modelo", "Visual do PDF"), ("perfil", "Meus dados"),
            ("cancelar", "Descartar o orçamento em andamento")]


async def ao_iniciar(app: Application):
    try:  # o menu "/" do Telegram com os comandos principais
        await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMANDOS])
    except Exception:
        logging.exception("Não consegui definir o menu de comandos")
    asyncio.get_running_loop().create_task(lembretes_periodicos(app))


def conexao() -> HTTPXRequest:
    """Conexão com o Telegram só por IPv4 e com prazos maiores.

    Em redes com IPv6 quebrado (conecta, mas o HTTPS não completa), o padrão trava em
    "Timed out" ao baixar áudio ou responder.
    """
    ipv4 = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
    return HTTPXRequest(connect_timeout=15, read_timeout=30, write_timeout=30, media_write_timeout=60,
                        httpx_kwargs={"transport": ipv4})


def main():
    global nucleo
    if not config.TELEGRAM_TOKEN:
        raise SystemExit("Defina TELEGRAM_TOKEN no arquivo .env (crie o bot com o @BotFather)")
    from app.avisos import instalar_alerta
    instalar_alerta()
    nucleo = Nucleo(iniciar_banco(config.DATABASE_URL), IAOpenAI())
    app = (Application.builder().token(config.TELEGRAM_TOKEN).request(conexao())
           .get_updates_request(conexao()).post_init(ao_iniciar).build())
    app.add_handler(CallbackQueryHandler(ao_tocar_botao))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.PRIVATE, ao_receber))
    logging.info("Bot rodando. Ctrl+C para parar.")
    app.run_polling()


if __name__ == "__main__":
    main()
