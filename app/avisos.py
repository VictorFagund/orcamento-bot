"""Avisos para o profissional fora do processo do bot (ex: o site avisa que o cliente aprovou)."""
import json
import logging

import httpx

from . import config

log = logging.getLogger(__name__)
API = "https://api.telegram.org/bot{token}/{metodo}"


def _cliente() -> httpx.Client:
    # Só IPv4: em redes com IPv6 quebrado o HTTPS do Telegram trava (mesmo motivo de bot_telegram.conexao)
    return httpx.Client(transport=httpx.HTTPTransport(local_address="0.0.0.0"), timeout=30)


def _teclado(botoes):
    if not botoes:
        return None
    return {"inline_keyboard": [[{"text": rotulo, "callback_data": valor[:64]} for rotulo, valor in linha]
                                for linha in botoes]}


class AlertaTelegram(logging.Handler):
    """Erro grave nos logs -> mensagem no Telegram do dono do sistema. O mesmo erro só avisa de 10 em 10 minutos."""

    INTERVALO = 600

    def __init__(self, enviar=None, relogio=None):
        super().__init__(level=logging.ERROR)
        self._enviar = enviar or self._enviar_api
        self._relogio = relogio or __import__("time").monotonic
        self._ultimo: dict[str, float] = {}

    def emit(self, registro: logging.LogRecord):
        if not config.ADMIN_CHAT_ID:
            return
        chave = f"{registro.name}:{registro.getMessage()[:120]}"
        agora = self._relogio()
        if agora - self._ultimo.get(chave, -self.INTERVALO) < self.INTERVALO:
            return
        self._ultimo[chave] = agora
        detalhe = ""
        if registro.exc_info and registro.exc_info[1] is not None:
            detalhe = f"\n{type(registro.exc_info[1]).__name__}: {registro.exc_info[1]}"[:600]
        try:
            self._enviar(f"🚨 {config.NOME_PRODUTO}: {registro.getMessage()[:500]}{detalhe}")
        except Exception:
            pass  # o alerta nunca pode derrubar o sistema

    @staticmethod
    def _enviar_api(texto: str):
        with _cliente() as http:
            http.post(API.format(token=config.TELEGRAM_TOKEN, metodo="sendMessage"),
                      json={"chat_id": config.ADMIN_CHAT_ID, "text": texto})


def instalar_alerta():
    if config.ADMIN_CHAT_ID and config.TELEGRAM_TOKEN:
        logging.getLogger().addHandler(AlertaTelegram())


def enviar_telegram(canal_id: str, respostas) -> None:
    """Manda as respostas do núcleo para o chat do profissional pela API do Telegram."""
    if not canal_id.startswith("telegram:") or not config.TELEGRAM_TOKEN:
        return
    chat_id = canal_id.split(":", 1)[1]
    with _cliente() as http:
        for r in respostas:
            teclado = _teclado(r.botoes)
            if r.texto:
                dados = {"chat_id": chat_id, "text": r.texto[:4000]}
                if teclado and not r.arquivo:
                    dados["reply_markup"] = teclado
                http.post(API.format(token=config.TELEGRAM_TOKEN, metodo="sendMessage"), json=dados).raise_for_status()
            if r.arquivo:
                with open(r.arquivo, "rb") as f:
                    dados = {"chat_id": chat_id}
                    if teclado:
                        dados["reply_markup"] = json.dumps(teclado)
                    http.post(API.format(token=config.TELEGRAM_TOKEN, metodo="sendDocument"), data=dados,
                              files={"document": f}).raise_for_status()
