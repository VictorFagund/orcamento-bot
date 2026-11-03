"""Conversa com o bot pelo terminal, sem Telegram (usa a IA de verdade, só texto).

Rodar:  python simular.py
Os PDFs gerados ficam em dados/arquivos/pdfs/
"""
from app import config
from app.db import iniciar_banco
from app.ia import IAOpenAI
from app.nucleo import Mensagem, Nucleo


def main():
    nucleo = Nucleo(iniciar_banco(config.DATABASE_URL), IAOpenAI())
    print("Simulador do bot. Digite suas mensagens (Ctrl+C para sair).\n")
    while True:
        try:
            texto = input("você> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if not texto:
            continue
        for r in nucleo.processar("terminal:1", Mensagem(texto=texto)):
            if r.texto:
                print(f"\nbot> {r.texto}\n")
            if r.arquivo:
                print(f"bot> [PDF gerado: {r.arquivo}]\n")


if __name__ == "__main__":
    main()
