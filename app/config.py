"""Configurações lidas do arquivo .env (veja .env.example)."""
import os

from dotenv import load_dotenv

load_dotenv()

# IA (transcrição de áudio + interpretação do texto)
# Funciona com qualquer provedor compatível com a API da OpenAI (OpenAI, Groq...). Veja .env.example.
IA_API_KEY = os.getenv("IA_API_KEY") or os.getenv("OPENAI_API_KEY", "")
IA_BASE_URL = os.getenv("IA_BASE_URL") or None  # vazio = OpenAI
MODELO_TEXTO = os.getenv("MODELO_TEXTO", "gpt-4o-mini")
MODELO_AUDIO = os.getenv("MODELO_AUDIO", "whisper-1")
# "schema" = JSON estruturado estrito (OpenAI). "objeto" = modo compatível, para provedores que não suportam schema.
IA_MODO_JSON = os.getenv("IA_MODO_JSON", "schema")

# Canal
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# Armazenamento
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///dados/orcamentos.db")
PASTA_ARQUIVOS = os.getenv("PASTA_ARQUIVOS", "dados/arquivos")

# Lembretes de orçamento sem resposta: dias após o envio (1º lembrete, 2º lembrete...)
FOLLOWUP_DIAS = [int(d) for d in os.getenv("FOLLOWUP_DIAS", "3,7").split(",") if d.strip()]
# Só manda lembrete dentro deste horário (no fuso abaixo), para não incomodar de madrugada
HORARIO_LEMBRETES = tuple(int(h) for h in os.getenv("HORARIO_LEMBRETES", "8-20").split("-"))
FUSO = os.getenv("FUSO", "America/Sao_Paulo")

# Lembretes de cobrança: dias após a aprovação, enquanto houver saldo a receber
COBRANCA_DIAS = [int(d) for d in os.getenv("COBRANCA_DIAS", "7,15").split(",") if d.strip()]
# Resumo semanal: dia da semana (0 = segunda) e hora a partir da qual é enviado
RESUMO_DIA = int(os.getenv("RESUMO_DIA", "0"))
RESUMO_HORA = int(os.getenv("RESUMO_HORA", "8"))
# Teto anual do MEI em reais (R$ 81 mil em 2026; há projetos para aumentar: confira o valor vigente)
LIMITE_MEI = int(os.getenv("LIMITE_MEI", "81000"))

# Reativação de clientes: no máximo N sugestões por profissional por dia (o resto fica para os dias seguintes)
REATIVACOES_POR_DIA = int(os.getenv("REATIVACOES_POR_DIA", "3"))

# Produto
NOME_PRODUTO = os.getenv("NOME_PRODUTO", "Orçamento Rápido")
VALIDADE_DIAS = int(os.getenv("VALIDADE_DIAS", "7"))
