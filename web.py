"""Site do produto (links do orçamento para o cliente, editor e perfil).

Rodar:  python web.py      (o bot roda à parte: python bot_telegram.py)
"""
import logging

import uvicorn

from app import config
from app.avisos import enviar_telegram
from app.db import iniciar_banco
from app.ia import IAOpenAI
from app.nucleo import Nucleo
from app.web import criar_app

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)

app = criar_app(iniciar_banco(config.DATABASE_URL), None, enviar_telegram)


def main():
    app.state.nucleo = Nucleo(app.state.Sessao, IAOpenAI())
    uvicorn.run(app, host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
