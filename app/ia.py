"""Camada de IA: transcrição de áudio e interpretação do que o profissional (ou o cliente) disse.

Regra de ouro: a IA NUNCA recebe nem decide preços da tabela. Ela só recebe a lista
de itens (id, descrição, sinônimos) e devolve QUAL item corresponde e QUANTOS.
Quando alguém FALA um valor (preço de um item, desconto, total), a IA só transcreve
esse número. Toda conta é feita depois, pelo código.
"""
import json
from typing import Protocol

from openai import OpenAI

from . import calculo, config

_NUM = {"type": ["number", "null"]}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["intencao", "numero_orcamento", "cliente", "itens", "precos", "observacoes", "condicoes",
                 "desconto_percentual", "desconto_valor", "total_desejado", "valor_pago"],
    "properties": {
        "intencao": {"type": "string", "enum": ["orcamento", "editar", "tabela_precos", "pagamento", "outro"]},
        "numero_orcamento": {"type": ["integer", "null"]},
        "cliente": {
            "type": "object",
            "additionalProperties": False,
            "required": ["nome", "endereco", "telefone"],
            "properties": {
                "nome": {"type": ["string", "null"]},
                "endereco": {"type": ["string", "null"]},
                "telefone": {"type": ["string", "null"]},
            },
        },
        "itens": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["descricao", "quantidade", "unidade", "item_preco_id", "preco_informado", "tipo"],
                "properties": {
                    "descricao": {"type": "string"},
                    "quantidade": {"type": "number"},
                    "unidade": {"type": ["string", "null"]},
                    "item_preco_id": {"type": ["integer", "null"]},
                    "preco_informado": _NUM,
                    "tipo": {"type": "string", "enum": ["servico", "peca"]},
                },
            },
        },
        "precos": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["descricao", "unidade", "preco", "sinonimos"],
                "properties": {
                    "descricao": {"type": "string"},
                    "unidade": {"type": ["string", "null"]},
                    "preco": {"type": "number"},
                    "sinonimos": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "observacoes": {"type": ["string", "null"]},
        "condicoes": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": False, "required": ["rotulo", "texto"],
                      "properties": {"rotulo": {"type": "string"}, "texto": {"type": "string"}}},
        },
        "desconto_percentual": _NUM,
        "desconto_valor": _NUM,
        "total_desejado": _NUM,
        "valor_pago": _NUM,
    },
}

PROMPT_SISTEMA = """Você é o assistente de um prestador de serviço brasileiro (eletricista, pintor, encanador etc.)
que monta e ajusta orçamentos a partir do que ele fala ou escreve, muitas vezes de forma informal.
Às vezes ele ENCAMINHA a mensagem do cliente dele (vem marcada como encaminhada): nesse caso, o pedido
é do cliente (ex: "consegue fazer por 600?", "tira o chuveiro") e deve ser aplicado ao orçamento.

Classifique a mensagem em "intencao":
- "orcamento": descreve serviços para um novo orçamento, OU corrige o ORÇAMENTO ATUAL (quando ele for informado).
- "editar": NÃO há ORÇAMENTO ATUAL e a mensagem pede mudança num orçamento que já foi enviado
  (cita o número, o nome do cliente, ou é uma mensagem encaminhada do cliente pedindo alteração, desconto,
  outro preço, tirar/incluir algo). Preencha "numero_orcamento" se for citado e cliente.nome se for citado.
  Nesse caso não precisa preencher itens.
- "tabela_precos": informa ou atualiza quanto cobra NORMALMENTE por itens ("tomada 40, chuveiro 120",
  "chuveiro agora é 130"). Mudança de preço só para um orçamento específico NÃO é tabela_precos.
  Se a mensagem cita um cliente ou o serviço de alguém ("pro João", "pra Bia", "do Gol do Seu Carlos",
  "Hilux do Marcos"), NÃO é tabela_precos, mesmo que tenha valores: esses valores são do orçamento.
  (Continua valendo "editar" para mudança num orçamento já enviado e para mensagem ENCAMINHADA do cliente.)
- "pagamento": ele avisa que RECEBEU dinheiro de um cliente ("recebi 850 da Dona Maria", "o orçamento 3 foi pago",
  "a Maria pagou 300 de entrada"). Preencha "numero_orcamento" e/ou cliente.nome se forem ditos, e "valor_pago"
  SOMENTE se o valor for dito (null = pagou o que faltava). Nesse caso não precisa preencher itens.
- "outro": qualquer outra coisa.

Para "orcamento":
- "cliente": o que for dito (nome, endereço, telefone); null no que não for dito.
- "itens": cada serviço/material com "descricao" curta e clara (ex: "Troca de tomada"),
  "quantidade" (número; 1 se não for dita) e "unidade" (un, m, m², diária... ou null).
- "item_preco_id": o id do item da TABELA DO PROFISSIONAL que corresponde ao serviço
  (compare pela descrição e pelos sinônimos com bom senso: "trocar 6 tomadas" -> "Troca de tomada").
  Se nenhum corresponder com segurança, null. NUNCA invente um id.
- "preco_informado": o valor unitário que ele DISSE para esse item, quando disser. Um número falado junto
  do item conta como dito: "pastilha 180" -> 180, "pastilha sai 220" -> 220, "disco por 480 o par" -> 480,
  "a fiação da cozinha eu faço por 300" -> 300, "nesse carro eu cobro 250" -> 250,
  "troca de óleo, cento e cinquenta" -> 150. Quantidade não é preço ("6 tomadas", "duas horas").
  Se nenhum valor foi dito para o item, null. Nunca estime nem complete preço.
- Ajustes no valor, SOMENTE se forem ditos explicitamente (nunca calcule nada, só transcreva o número):
  "desconto_percentual": ex. "dá 10% de desconto" -> 10.
  "desconto_valor": desconto em reais, ex. "tira 50 reais" -> 50.
  "total_desejado": quando é dito o valor final do orçamento todo, ex. "fecha em 700",
  "o cliente quer pagar 600", "consegue fazer por 650?" -> 650.
  Preencha no máximo UM dos três. "tira o desconto" -> os três null.
- Se houver um ORÇAMENTO ATUAL, devolva o estado COMPLETO já corrigido: todos os itens (mantenha os que não
  mudaram, inclusive preco_informado anteriores), cliente, observacoes e o desconto atual (a menos que a
  mensagem mude ou remova o desconto).
- "tipo" de cada item: "peca" quando o item é a coisa comprada (peça ou material: "pastilha", "disjuntor 20A",
  "2 latas de tinta", "cabo 2,5mm"); "servico" quando é o trabalho ("troca de pastilha", "instalação", "mão de obra").
- "observacoes": detalhes que não são itens nem condições (ou null).
- "condicoes": condições ditas para ESTE orçamento, como garantia, prazo de execução, material incluso ou não,
  visita técnica. Formato {"rotulo": "Garantia", "texto": "6 meses"}, {"rotulo": "Prazo", "texto": "3 dias úteis"}.
  Só o que foi dito; senão, lista vazia. Com ORÇAMENTO ATUAL, mantenha as condições que ele já tem.

Para "tabela_precos": preencha "precos" com descricao, unidade, preco (número em reais) e "sinonimos"
(2 a 4 formas comuns de se referir ao mesmo serviço). Deixe "itens" vazio.

Campos que não se aplicam: listas vazias e null."""


SCHEMA_CADASTRO = {
    "type": "object", "additionalProperties": False,
    "required": ["nome", "profissao", "telefone", "cidade", "pagamento", "pix"],
    "properties": {k: {"type": ["string", "null"]} for k in ("nome", "profissao", "telefone", "cidade", "pagamento", "pix")},
}
PROMPT_CADASTRO = """Um prestador de serviço brasileiro respondeu de uma vez um checklist de cadastro, do jeito dele
(a ordem pode ser qualquer uma, pode faltar item, pode ter rótulo ou não). Separe cada informação no campo certo:
- nome: nome da pessoa ou da empresa, como deve aparecer no topo do orçamento
- profissao: a área de trabalho (ex: "Eletricista", "Mecânico"), com inicial maiúscula
- telefone: telefone de contato, como foi escrito
- cidade: cidade onde atende (pode incluir o estado)
- pagamento: condições de pagamento que ele oferece aos clientes (ex: "Pix ou cartão, 50% de entrada")
- pix: a chave Pix, exatamente como escrita (CPF, CNPJ, celular, e-mail ou chave aleatória)
Pistas: um número de celular que aparece junto de "pix" é a chave Pix; sem essa indicação, é o telefone. "Pix" sozinho
na lista é forma de pagamento, não chave. Se algo não foi dito, use null. Nunca invente."""


class IA(Protocol):
    def transcrever(self, audio: bytes, nome_arquivo: str = "audio.ogg") -> str: ...

    def interpretar(self, texto: str, tabela: list[dict], rascunho: dict | None = None, contexto: str = "") -> dict: ...


class IAOpenAI:
    """Cliente para qualquer API compatível com a da OpenAI (OpenAI, Groq e outras)."""

    def __init__(self, api_key: str = config.IA_API_KEY, base_url: str | None = config.IA_BASE_URL):
        if not api_key:
            raise RuntimeError("Defina IA_API_KEY no arquivo .env")
        self.cliente = OpenAI(api_key=api_key, base_url=base_url)

    def transcrever(self, audio: bytes, nome_arquivo: str = "audio.ogg") -> str:
        resp = self.cliente.audio.transcriptions.create(
            model=config.MODELO_AUDIO, file=(nome_arquivo, audio), language="pt"
        )
        return resp.text.strip()

    def extrair_cadastro(self, texto: str) -> dict:
        """Checklist respondido de uma vez -> campos do cadastro."""
        if config.IA_MODO_JSON == "objeto":
            formato = {"type": "json_object"}
            sistema = (PROMPT_CADASTRO + "\n\nResponda SOMENTE com JSON com as chaves: "
                       + ", ".join(SCHEMA_CADASTRO["required"]))
        else:
            formato = {"type": "json_schema", "json_schema": {"name": "cadastro", "strict": True, "schema": SCHEMA_CADASTRO}}
            sistema = PROMPT_CADASTRO
        resp = self.cliente.chat.completions.create(
            model=config.MODELO_TEXTO, temperature=0, response_format=formato,
            messages=[{"role": "system", "content": sistema}, {"role": "user", "content": texto}])
        dados = json.loads(resp.choices[0].message.content) or {}
        return {k: (str(dados.get(k)).strip() or None) if dados.get(k) else None for k in SCHEMA_CADASTRO["required"]}

    def interpretar(self, texto: str, tabela: list[dict], rascunho: dict | None = None, contexto: str = "") -> dict:
        partes = [f"TABELA DO PROFISSIONAL (sem preços): {json.dumps(tabela, ensure_ascii=False)}"]
        if rascunho:
            partes.append(f"ORÇAMENTO ATUAL: {json.dumps(rascunho_para_ia(rascunho), ensure_ascii=False)}")
            # Sem isto, modelos como o gpt-oss classificam "são 8 tomadas" como "editar" e devolvem itens vazios
            partes.append("Há um ORÇAMENTO ATUAL: a mensagem é uma correção dele. Use intencao \"orcamento\" "
                          "(nunca \"editar\") e devolva o estado COMPLETO já corrigido, com todos os itens. "
                          "Só use outra intenção se a mensagem for claramente um pagamento ou tabela de preços.")
        if contexto:
            partes.append(f"CONTEXTO: {contexto}")
        partes.append(f"MENSAGEM: {texto}")

        sistema = PROMPT_SISTEMA
        if config.IA_MODO_JSON == "objeto":
            formato = {"type": "json_object"}
            sistema += ("\n\nResponda SOMENTE com um objeto JSON válido, com exatamente as chaves deste JSON Schema:\n"
                        + json.dumps(SCHEMA, ensure_ascii=False))
        else:
            formato = {"type": "json_schema",
                       "json_schema": {"name": "interpretacao", "strict": True, "schema": SCHEMA}}

        resp = self.cliente.chat.completions.create(
            model=config.MODELO_TEXTO,
            temperature=0,
            messages=[{"role": "system", "content": sistema}, {"role": "user", "content": "\n\n".join(partes)}],
            response_format=formato,
        )
        return completar(json.loads(resp.choices[0].message.content))


def completar(dados: dict) -> dict:
    """Garante que todas as chaves existem (modelos no modo compatível às vezes omitem alguma)."""
    base = {"intencao": "outro", "numero_orcamento": None, "itens": [], "precos": [], "observacoes": None,
            "condicoes": [],
            "desconto_percentual": None, "desconto_valor": None, "total_desejado": None, "valor_pago": None}
    dados = {**base, **{k: v for k, v in (dados or {}).items() if v is not None or k not in base}}
    cli = dados.get("cliente") or {}
    dados["cliente"] = {k: cli.get(k) for k in ("nome", "endereco", "telefone")}
    dados["itens"] = [{"descricao": str(i.get("descricao") or "Item"), "quantidade": i.get("quantidade"),  # 0 continua 0 (item removido)
                       "unidade": i.get("unidade"), "item_preco_id": i.get("item_preco_id"),
                       "preco_informado": i.get("preco_informado"),
                       "tipo": i.get("tipo") if i.get("tipo") in ("servico", "peca") else None} for i in dados["itens"] or []]
    dados["precos"] = [p for p in dados["precos"] or [] if isinstance(p.get("preco"), (int, float))]
    return dados


def rascunho_para_ia(rascunho: dict) -> dict:
    """Manda o orçamento atual para a IA sem os preços da tabela (só valores que foram falados)."""
    desconto = rascunho.get("desconto") or {}
    return {
        "cliente": rascunho.get("cliente"),
        "itens": [
            {
                "descricao": i["descricao"],
                "quantidade": i["quantidade"],
                "unidade": i.get("unidade"),
                "item_preco_id": i.get("item_preco_id"),
                "preco_informado": i["preco_centavos"] / 100 if i.get("origem") == "informado" else None,
                "tipo": i.get("tipo") or "servico",
            }
            for i in rascunho.get("itens", [])
        ],
        "observacoes": rascunho.get("observacoes"),
        "condicoes": rascunho.get("condicoes") or [],
        "desconto_percentual": desconto.get("valor") if desconto.get("tipo") == "percentual" else None,
        "desconto_valor": desconto.get("valor") if desconto.get("tipo") == "valor" else None,
        "total_desejado": (desconto.get("valor") if desconto.get("tipo") == "total"
                           else calculo.total(rascunho) / 100 if desconto.get("tipo") == "acrescimo" else None),
    }
