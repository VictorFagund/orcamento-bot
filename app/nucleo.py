"""Núcleo da conversa. Não sabe se a mensagem veio do Telegram, WhatsApp ou terminal:
recebe uma Mensagem e devolve uma lista de Respostas (texto e/ou arquivo).
"""
import copy
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import shutil

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from . import calculo, catalogo, config, pix, textos
from .db import Aceite, Cliente, Evento, ItemPreco, Link, Orcamento, OrcamentoItem, Pagamento, Profissional
from .ia import IA, completar
from . import eventos, links
from . import pdf as pdf_mod
from .pdf import gerar_pdf, gerar_recibo

log = logging.getLogger(__name__)


@dataclass
class Mensagem:
    texto: str | None = None
    audio: bytes | None = None
    audio_nome: str = "audio.ogg"
    foto: bytes | None = None
    # Preenchido quando a mensagem foi ENCAMINHADA (ex: pedido do cliente). "" = remetente desconhecido.
    encaminhada_de: str | None = None


@dataclass
class Resposta:
    texto: str | None = None
    arquivo: str | None = None
    imagem: str | None = None  # foto (ex: prévia do modelo de PDF), com o texto como legenda
    # Botões embaixo da mensagem: linhas de (rótulo, o que o botão "diz" ao bot quando tocado)
    botoes: list[list[tuple[str, str]]] | None = None


AJUDA = textos.AJUDA
PULAR_BOTAO = [[("⏭️ Pular", "pular")]]
BOTOES_RESUMO = [[("✅ Está certo, gerar PDF", "ok")],
                 [("✏️ Corrigir algo", "/corrigir"), ("🗑️ Descartar", "cancelar")],
                 [("🌐 Editar no navegador", "/editarweb")]]
BOTOES_MENU = [[("📝 Como fazer um orçamento", "/exemplo")],
               [("💲 Minha tabela", "/precos"), ("📂 Orçamentos", "/orcamentos")],
               [("💰 A receber", "/areceber"), ("🎨 Visual do PDF", "/modelo")],
               [("👤 Meus dados", "/perfil"), ("📋 Todos os comandos", "/comandos")]]


def botoes_pos_envio(n: int):
    return [[("👍 Cliente aprovou", f"/aprovado {n}"), ("👎 Recusou", f"/recusado {n}")],
            [("💰 Já recebi", f"/pago {n}"), ("🌐 Editar no navegador", f"/editarweb {n}")]]

CONFIRMAR = {"ok", "sim", "s", "confirma", "confirmo", "confirmar", "pode", "pode gerar", "gerar", "gera",
             "isso", "beleza", "blz", "manda", "certo", "ta certo", "esta certo", "fechado", "perfeito"}
CANCELAR = {"cancelar", "cancela", "cancelado", "descartar", "esquece"}
ACEITE = {"aceito", "aceita", "li e aceito", "eu aceito", "sim", "ok", "concordo"}
PULAR = {"pular", "pula", "nao", "nao tenho", "-", "nenhum", "nenhuma", "depois"}


# Comandos para corrigir os dados do perfil: comando -> (campo, rótulo, tamanho máximo)
CAMPOS_PERFIL = {"/nome": ("nome", "Nome", 120), "/profissao": ("profissao", "Profissão", 80),
                 "/telefone": ("telefone", "Telefone", 40), "/cidade": ("cidade", "Cidade", 80),
                 "/pagamento": ("pagamento_padrao", "Forma de pagamento", 200)}
EXEMPLOS_PERFIL = {"/nome": "Elétrica Silva", "/profissao": "Eletricista", "/telefone": "(46) 99999-0000",
                   "/cidade": "Realeza - PR", "/pagamento": "Pix ou cartão, 50% de entrada"}


def _norm(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^\w\s-]", "", sem_acento.lower()).strip()


class Nucleo:
    def __init__(self, Sessao, ia: IA, pasta_arquivos: str = config.PASTA_ARQUIVOS):
        self.Sessao = Sessao
        self.ia = ia
        self.pasta = pasta_arquivos

    # ------------------------------------------------------------------ entrada
    def processar(self, canal_id: str, msg: Mensagem) -> list[Resposta]:
        with self.Sessao() as s:
            prof = s.scalar(select(Profissional).where(Profissional.canal_id == canal_id))
            if prof is None:
                prof = Profissional(canal_id=canal_id, estado="NOVO")
                s.add(prof)
                s.flush()
            try:
                respostas = self._processar(s, prof, msg)
                s.commit()
                return respostas
            except Exception as erro:
                log.exception("Erro processando mensagem de %s", canal_id)
                s.rollback()
                if getattr(erro, "_falha_ia", False) and prof.id:
                    try:
                        eventos.registrar(s, prof.id, "falha_ia", erro=type(erro).__name__)
                        s.commit()
                    except Exception:
                        log.exception("Não consegui registrar a falha da IA")
                return [Resposta("Ops, tive um problema para processar isso. Pode tentar de novo?")]

    def _processar(self, s, prof: Profissional, msg: Mensagem) -> list[Resposta]:
        if msg.foto:
            resposta = self._salvar_logo(prof, msg.foto)
            if prof.estado == "CADASTRO_LOGO":
                return [resposta] + self._pedir_tabela(prof)
            return [resposta]

        respostas: list[Resposta] = []
        texto = (msg.texto or "").strip()
        if msg.audio:
            texto = self.ia.transcrever(msg.audio, msg.audio_nome)
            respostas.append(Resposta(f'🎙️ Entendi: "{texto}"'))
        if not texto:
            return respostas + [Resposta("Me mande um texto ou um áudio 🙂")]
        if msg.encaminhada_de is not None and not texto.startswith("/"):
            quem = f" {msg.encaminhada_de}" if msg.encaminhada_de else ""
            texto = f"[Mensagem ENCAMINHADA do cliente{quem}] {texto}"

        if texto.startswith("/"):
            return respostas + self._comando(s, prof, texto)
        if _norm(texto) in CANCELAR and prof.rascunho:
            return respostas + self._cancelar(prof)

        tratar = {
            "NOVO": self._boas_vindas,
            **self._etapas_cadastro(),
            "AGUARDANDO_PRECO": self._receber_preco,
            "CONFIRMANDO": self._confirmando,
            "ESCOLHENDO_ORCAMENTO": self._escolher_orcamento,
        }.get(prof.estado, self._ocioso)
        if tratar == self._ocioso and prof.termos_aceitos_em is None:  # conta de antes dos termos existirem
            return respostas + self._pedir_termos(prof)
        return respostas + tratar(s, prof, texto)

    def _interpretar(self, texto, tabela, rascunho=None, contexto=""):
        """Chama a IA e garante o formato da resposta, venha ela de qual modelo vier."""
        try:
            return completar(self.ia.interpretar(texto, tabela, rascunho=rascunho, contexto=contexto))
        except Exception as erro:
            erro._falha_ia = True  # processar() registra o evento depois do rollback
            raise

    # ------------------------------------------------------------------ cadastro
    def _etapas_cadastro(self):
        return {
            "CADASTRO_NOME": self._cad_nome,
            "CADASTRO_PROFISSAO": self._cad_profissao,
            "CADASTRO_TELEFONE": self._cad_telefone,
            "CADASTRO_CIDADE": self._cad_cidade,
            "CADASTRO_PAGAMENTO": self._cad_pagamento,
            "CADASTRO_PIX": self._cad_pix,
            "CADASTRO_LOGO": self._cad_logo,
            "CADASTRO_TABELA": self._cad_tabela,
            "CADASTRO_TERMOS": self._cad_termos,
        }

    def _boas_vindas(self, s, prof, texto=""):
        prof.estado = "CADASTRO_NOME"
        return [Resposta(textos.BOAS_VINDAS)]

    def _cad_nome(self, s, prof, texto):
        # "1. Victor" -> "Victor" (a lista do checklist é numerada e muita gente responde copiando a numeração)
        linhas = [re.sub(r"^\d{1,2}\s*[.)\-:]\s+", "", linha.strip()) for linha in texto.splitlines() if linha.strip()]
        if len(linhas) > 1:
            return self._cadastro_em_lote(s, prof, linhas)
        prof.nome = texto[:120]
        prof.estado = "CADASTRO_PROFISSAO"
        return [Resposta(textos.PERGUNTA_PROFISSAO.format(nome=prof.nome))]

    def _cadastro_em_lote(self, s, prof, linhas):
        extrair = getattr(self.ia, "extrair_cadastro", None)
        if extrair:
            try:
                campos = extrair("\n".join(linhas))
            except Exception:
                log.exception("Falha ao extrair o cadastro em lote; seguindo linha a linha")
            else:
                return self._aplicar_cadastro(s, prof, campos)
        return self._cadastro_por_linhas(s, prof, linhas)

    def _aplicar_cadastro(self, s, prof, campos: dict):
        """Preenche o que a IA reconheceu no checklist e pergunta só o que faltou."""
        avisos = []
        prof.nome = (campos.get("nome") or prof.nome or "")[:120] or None
        prof.profissao = (campos.get("profissao") or "")[:80] or None
        prof.telefone = (campos.get("telefone") or "")[:40] or None
        prof.cidade = (campos.get("cidade") or "")[:80] or None
        prof.pagamento_padrao = (campos.get("pagamento") or "")[:200] or None
        if campos.get("pix"):
            r = self._definir_pix(prof, campos["pix"])
            if not r.texto.startswith("✅"):
                avisos.append(r)
        anotados = "\n".join(f"• {nome}: {valor}" for nome, valor in self._campos_perfil(prof) if valor)
        resposta = [Resposta("📋 Anotei assim:\n" + anotados +
                             "\n\nSe algo saiu errado, dá para corrigir depois em /perfil.")] + avisos
        if not prof.nome:
            prof.estado = "CADASTRO_NOME"
            return resposta + [Resposta("Qual o seu nome ou o nome da sua empresa?")]
        if not prof.profissao:
            prof.estado = "CADASTRO_PROFISSAO"
            return resposta + [Resposta(textos.PERGUNTA_PROFISSAO.format(nome=prof.nome))]
        if not prof.cidade:
            prof.estado = "CADASTRO_CIDADE"
            return resposta + [Resposta(textos.PERGUNTA_CIDADE)]
        if not prof.pix_chave and not avisos:
            prof.estado = "CADASTRO_PIX"
            return resposta + [Resposta(textos.PERGUNTA_PIX, botoes=PULAR_BOTAO)]
        if avisos:
            prof.estado = "CADASTRO_PIX"
            return resposta
        prof.estado = "CADASTRO_LOGO"
        return resposta + [Resposta(textos.PERGUNTA_LOGO, botoes=PULAR_BOTAO)]

    @staticmethod
    def _campos_perfil(prof):
        modelo = pdf_mod.MODELOS.get(prof.modelo_pdf or pdf_mod.MODELO_PADRAO, ("",))[0]
        cor = pdf_mod.CORES.get(prof.cor_pdf or pdf_mod.COR_PADRAO, ("",))[0]
        return [("Nome", prof.nome), ("Profissão", prof.profissao), ("Telefone", prof.telefone),
                ("Cidade", prof.cidade), ("Pagamento", prof.pagamento_padrao), ("Pix", prof.pix_chave),
                ("Logo", "salva" if prof.logo_path else None), ("Visual do PDF", f"{modelo}, {cor.lower()}")]

    def _cadastro_por_linhas(self, s, prof, linhas):
        """Respondeu o checklist de uma vez, uma resposta por linha: aplica cada linha na etapa da vez.

        Se uma linha não servir (ex: Pix inválida), para ali e mostra o erro; o resto é perguntado depois.
        """
        etapas = self._etapas_cadastro()
        respostas = []
        for linha in linhas:
            etapa = etapas.get(prof.estado)
            if etapa is None:
                break
            antes = prof.estado
            respostas = etapa(s, prof, linha)
            if prof.estado == antes:
                break
        campos = [("Nome", prof.nome), ("Profissão", prof.profissao), ("Telefone", prof.telefone),
                  ("Cidade", prof.cidade), ("Pagamento", prof.pagamento_padrao), ("Pix", prof.pix_chave),
                  ("Logo", "salva" if prof.logo_path else None)]
        anotados = "\n".join(f"• {nome}: {valor}" for nome, valor in campos if valor)
        return [Resposta("📋 Anotei de uma vez:\n" + anotados)] + respostas

    def _cad_profissao(self, s, prof, texto):
        prof.profissao = texto[:80]
        prof.estado = "CADASTRO_TELEFONE"
        return [Resposta(textos.PERGUNTA_TELEFONE, botoes=PULAR_BOTAO)]

    def _cad_telefone(self, s, prof, texto):
        prof.telefone = None if _norm(texto) in PULAR else texto[:40]
        prof.estado = "CADASTRO_CIDADE"
        return [Resposta(textos.PERGUNTA_CIDADE)]

    def _cad_cidade(self, s, prof, texto):
        prof.cidade = None if _norm(texto) in PULAR else texto[:80]
        prof.estado = "CADASTRO_PAGAMENTO"
        return [Resposta(textos.PERGUNTA_PAGAMENTO, botoes=PULAR_BOTAO)]

    def _cad_pagamento(self, s, prof, texto):
        prof.pagamento_padrao = None if _norm(texto) in PULAR else texto[:200]
        prof.estado = "CADASTRO_PIX"
        return [Resposta(textos.PERGUNTA_PIX, botoes=PULAR_BOTAO)]

    def _cad_pix(self, s, prof, texto):
        respostas = []
        if _norm(texto) not in PULAR:
            resultado = self._definir_pix(prof, texto)
            if resultado.texto.startswith("✅"):
                respostas.append(resultado)
            else:
                return [resultado]
        prof.estado = "CADASTRO_LOGO"
        return respostas + [Resposta(textos.PERGUNTA_LOGO, botoes=PULAR_BOTAO)]

    def _cad_logo(self, s, prof, texto):
        # A foto em si é tratada em _processar; aqui só chega texto
        if _norm(texto) in PULAR or _norm(texto).startswith(("sem", "nao tenho", "nao")):  # "sem logo"
            return self._pedir_tabela(prof)
        return [Resposta(textos.LOGO_ESPERANDO, botoes=PULAR_BOTAO)]

    def _pedir_tabela(self, prof):
        prof.estado = "CADASTRO_TABELA"
        servicos = catalogo.servicos_da_profissao(prof.profissao)
        if servicos:
            lista = "\n".join(f"{n}. {d}{f' (por {u})' if u != 'un' else ''}" for n, (d, u, _) in enumerate(servicos, 1))
            return [Resposta(textos.TABELA_COM_CATALOGO.format(profissao=prof.profissao.lower(), lista=lista),
                             botoes=[[("⏭️ Pular por agora", "pular")]])]
        return [Resposta(textos.TABELA_SEM_CATALOGO, botoes=[[("⏭️ Pular por agora", "pular")]])]

    def _definir_pix(self, prof, texto) -> Resposta:
        resultado = pix.normalizar_chave(re.sub(r"(?i)^\s*(cpf|cnpj|celular|telefone|e-?mail)[:\s]*", "", texto))
        if resultado is None:
            return Resposta(textos.PIX_INVALIDA)
        chave, tipo = resultado
        if tipo == "ambigua":
            return Resposta(textos.PIX_AMBIGUA)
        prof.pix_chave = chave
        return Resposta(f"✅ Chave Pix ({tipo}) salva: {chave}\nConfira com atenção: é para ela que o dinheiro vai.")

    def _cad_tabela(self, s, prof, texto):
        respostas = []
        if _norm(texto) not in PULAR:
            servicos = catalogo.servicos_da_profissao(prof.profissao)
            contexto = "O profissional está cadastrando a tabela de preços."
            if servicos:
                lista = "; ".join(f"{n}. {d} ({u})" for n, (d, u, _) in enumerate(servicos, 1))
                contexto += (f" Ele recebeu esta lista numerada de serviços comuns: {lista}. Se responder só com números,"
                             " associe na ordem da lista. Use a descrição e a unidade da lista quando o serviço for dela."
                             " Inclua só os serviços com valor dito.")
            dados = self._interpretar(texto, [], contexto=contexto)
            if not dados["precos"]:
                return [Resposta("Não consegui identificar preços aí 🤔 Tente algo como "
                                 "\"tomada 40, chuveiro 120\" ou responda PULAR.")]
            respostas.append(Resposta(self._salvar_precos(s, prof, dados["precos"])))
        return respostas + self._pedir_termos(prof)

    def _pedir_termos(self, prof) -> list[Resposta]:
        prof.estado = "CADASTRO_TERMOS"
        return [Resposta(textos.PEDIR_TERMOS.format(termos=f"{config.BASE_URL}/termos",
                                                    privacidade=f"{config.BASE_URL}/privacidade"),
                         botoes=[[("✅ Li e aceito", "aceito")]])]

    def _cad_termos(self, s, prof, texto):
        if _norm(texto) not in ACEITE:
            return [Resposta("Para usar, é preciso aceitar os termos. Toque em \"Li e aceito\" ou responda ACEITO.",
                             botoes=[[("✅ Li e aceito", "aceito")]])]
        if prof.termos_aceitos_em is None:
            eventos.registrar(s, prof.id, "cadastro_concluido")
        prof.termos_aceitos_em = datetime.now()
        prof.estado = "OCIOSO"
        ja_usou = s.scalar(select(func.count()).select_from(Orcamento).where(Orcamento.profissional_id == prof.id))
        if ja_usou:
            return [Resposta("✅ Obrigado! Agora é só mandar o orçamento de novo.")]
        return [Resposta(textos.CADASTRO_PRONTO, botoes=BOTOES_MENU)]

    # ------------------------------------------------------------------ uso normal
    def _ocioso(self, s, prof, texto):
        dados = self._interpretar(texto, self._tabela_para_ia(prof))
        if dados["intencao"] == "tabela_precos" and dados["precos"]:
            return [Resposta(self._salvar_precos(s, prof, dados["precos"]))]
        if dados["intencao"] == "pagamento":
            return self._pagamento_por_texto(s, prof, dados)
        # Encaminhada do cliente sem lista de serviços é sempre pedido de mudança ("consegue por 600?"),
        # mesmo que a IA classifique como orçamento novo
        encaminhada = texto.startswith("[Mensagem ENCAMINHADA")
        if dados["intencao"] == "editar" or (encaminhada and not (dados["intencao"] == "orcamento" and dados["itens"])):
            return self._pedir_edicao(s, prof, dados, texto)
        if dados["intencao"] == "orcamento" and dados["itens"]:
            bloqueio = self._limite_atingido(s, prof)
            if bloqueio:
                return bloqueio
            return self._seguir_rascunho(s, prof, self._montar(prof, dados))
        return [Resposta("Não entendi como orçamento 🤔 Descreva o serviço e para quem é, por exemplo:\n"
                         "\"Orçamento pro João: instalar 2 chuveiros e trocar 4 tomadas\".\n\n/ajuda para ver tudo.")]

    def _seguir_rascunho(self, s, prof, rascunho):
        """Depois de montar/corrigir: pergunta preços que faltam ou mostra o resumo para conferência."""
        if not rascunho["itens"]:
            self._limpar_rascunho(prof)
            return [Resposta("O orçamento ficou sem itens, então descartei. Mande um novo quando quiser.")]
        faltando = calculo.pendentes(rascunho)
        if faltando:
            self._guardar_rascunho(prof, rascunho)
            prof.estado = "AGUARDANDO_PRECO"
            return [Resposta(self._pergunta_preco(rascunho["itens"][faltando[0]]))]
        self._guardar_rascunho(prof, calculo.fixar_desconto(rascunho))
        rascunho = prof.rascunho
        prof.estado = "CONFIRMANDO"
        return [Resposta(self._resumo(rascunho), botoes=BOTOES_RESUMO)]

    def _receber_preco(self, s, prof, texto):
        rascunho = copy.deepcopy(prof.rascunho)
        idx = calculo.pendentes(rascunho)[0]
        item = rascunho["itens"][idx]
        valor = calculo.ler_valor(texto)
        if valor is None:
            return [Resposta("Não entendi o valor. Me mande só o número, ex: 80 ou 80,50 "
                             "(ou CANCELAR para descartar o orçamento).")]
        novo = self._novo_item(prof, item["descricao"], item.get("unidade"), valor, [])
        s.flush()
        item.update(item_preco_id=novo.id, preco_centavos=valor, origem="tabela")
        resp = [Resposta(f'💾 Guardei na sua tabela: {item["descricao"]} = {calculo.reais(valor)}')]
        return resp + self._seguir_rascunho(s, prof, rascunho)

    def _confirmando(self, s, prof, texto):
        if _norm(texto) in CONFIRMAR or _norm(texto).startswith("ok"):
            return self._finalizar(s, prof)
        # Qualquer outra coisa é tratada como correção do orçamento
        eventos.registrar(s, prof.id, "correcao")
        dados = self._interpretar(texto, self._tabela_para_ia(prof), rascunho=prof.rascunho)
        if dados["intencao"] == "tabela_precos" and dados["precos"] and not dados["itens"]:
            msg = self._salvar_precos(s, prof, dados["precos"])
            rascunho = self._reaplicar_precos(prof, prof.rascunho)
            self._guardar_rascunho(prof, rascunho)
            return [Resposta(msg), Resposta(self._resumo(rascunho), botoes=BOTOES_RESUMO)]
        if not dados["itens"]:
            return [Resposta("Não entendi a correção 🤔 Diga o que mudar, por exemplo: \"são 8 tomadas\", "
                             "\"tira o chuveiro\" ou \"dá 10% de desconto\".", botoes=BOTOES_RESUMO)]
        return self._seguir_rascunho(s, prof, self._montar(prof, dados))

    # ------------------------------------------------------------------ edição de orçamento já enviado
    def _pedir_edicao(self, s, prof, dados, instrucao):
        """Pedido de mudança num orçamento já enviado: descobre qual e aplica."""
        orc = self._localizar_orcamento(s, prof, dados)
        if orc:
            return self._iniciar_edicao(s, prof, orc, instrucao)
        recentes = self._recentes(s, prof, 5)
        if not recentes:
            return [Resposta("Você ainda não tem orçamentos para alterar. Mande um áudio descrevendo o serviço!")]
        self._guardar_rascunho(prof, {"instrucao_pendente": instrucao})
        prof.estado = "ESCOLHENDO_ORCAMENTO"
        linhas = [self._linha_orc(o) for o in recentes]
        return [Resposta("Em qual orçamento aplico essa mudança? Responda com o número:\n\n" + "\n".join(linhas))]

    def _escolher_orcamento(self, s, prof, texto):
        m = re.search(r"\d+", texto)
        orc = self._buscar_orcamento(s, prof, m.group() if m else "")
        if orc is None:
            return [Resposta("Não achei. Responda só o número do orçamento (ou CANCELAR).")]
        instrucao = (prof.rascunho or {}).get("instrucao_pendente", "")
        return self._iniciar_edicao(s, prof, orc, instrucao)

    def _iniciar_edicao(self, s, prof, orc, instrucao: str | None):
        atual = self._orc_para_rascunho(prof, orc)
        if not instrucao:
            self._guardar_rascunho(prof, atual)
            prof.estado = "CONFIRMANDO"
            return [Resposta(self._resumo(atual).rsplit("\n\n", 1)[0] +
                             "\n\nO que você quer mudar? Pode falar, escrever ou encaminhar aqui a mensagem do cliente.",
                             botoes=[[("↩️ Deixar como está", "cancelar")]])]
        dados = self._interpretar(instrucao, self._tabela_para_ia(prof), rascunho=atual,
                                    contexto=f"Alteração do orçamento Nº {orc.numero}, que já foi enviado ao cliente.")
        if not dados["itens"]:
            self._guardar_rascunho(prof, atual)
            prof.estado = "CONFIRMANDO"
            return [Resposta(f"Abri o orçamento Nº {orc.numero:04d}, mas não entendi o que mudar. "
                             "Diga a alteração (ex: \"dá 10% de desconto\", \"tira o chuveiro\") ou CANCELAR.")]
        novo = calculo.montar_rascunho(dados, self._tabela_precos(prof))
        novo["editando_id"] = orc.id
        novo["editando_numero"] = orc.numero
        return self._seguir_rascunho(s, prof, novo)

    def _localizar_orcamento(self, s, prof, dados):
        if dados.get("numero_orcamento"):
            orc = self._buscar_orcamento(s, prof, str(dados["numero_orcamento"]))
            if orc:
                return orc
        nome = (dados.get("cliente") or {}).get("nome")
        if nome:
            return s.scalar(select(Orcamento).join(Cliente, Orcamento.cliente_id == Cliente.id)
                            .where(Orcamento.profissional_id == prof.id,
                                   func.lower(Cliente.nome).contains(nome.lower()))
                            .order_by(Orcamento.numero.desc()).limit(1))
        return None

    def _orc_para_rascunho(self, prof, orc) -> dict:
        tabela = self._tabela_precos(prof)
        itens = []
        for i in orc.itens:
            da_tabela = i.item_preco_id in tabela and tabela[i.item_preco_id]["preco_centavos"] == i.preco_unit_centavos
            itens.append({"descricao": i.descricao, "quantidade": i.quantidade, "unidade": i.unidade,
                          "tipo": i.tipo or "servico",
                          "item_preco_id": i.item_preco_id if i.item_preco_id in tabela else None,
                          "preco_centavos": i.preco_unit_centavos, "origem": "tabela" if da_tabela else "informado"})
        if orc.desconto_percentual:
            desconto = {"tipo": "percentual", "valor": orc.desconto_percentual}
        elif orc.desconto_centavos:
            tipo = "valor" if orc.desconto_centavos > 0 else "acrescimo"
            desconto = {"tipo": tipo, "valor": abs(orc.desconto_centavos) / 100}
        else:
            desconto = None
        cli = orc.cliente
        return {"cliente": {"nome": cli.nome if cli else None, "endereco": cli.endereco if cli else None,
                            "telefone": cli.telefone if cli else None},
                "itens": itens, "observacoes": orc.observacoes, "desconto": desconto,
                "condicoes": orc.condicoes or [], "editando_id": orc.id, "editando_numero": orc.numero}

    def _finalizar(self, s, prof):
        r = prof.rascunho
        cliente = None
        nome_cli = (r["cliente"] or {}).get("nome")
        if nome_cli:
            cliente = s.scalar(select(Cliente).where(Cliente.profissional_id == prof.id,
                                                     func.lower(Cliente.nome) == nome_cli.lower()))
            if cliente is None:
                cliente = Cliente(profissional_id=prof.id, nome=nome_cli)
                s.add(cliente)
            cliente.endereco = r["cliente"].get("endereco") or cliente.endereco
            cliente.telefone = r["cliente"].get("telefone") or cliente.telefone

        desconto = r.get("desconto") or {}
        campos = dict(cliente=cliente, status="enviado", total_centavos=calculo.total(r),
                      enviado_em=datetime.now(), lembretes=0,
                      desconto_centavos=calculo.valor_desconto(r),
                      desconto_percentual=desconto.get("valor") if desconto.get("tipo") == "percentual" else None,
                      observacoes=r.get("observacoes"), validade=date.today() + timedelta(days=config.VALIDADE_DIAS),
                      condicoes=(calculo.limpar_condicoes(r.get("condicoes")) if r.get("condicoes_finais")
                                 else calculo.juntar_condicoes(prof.condicoes_padrao, r.get("condicoes"))))

        orc = s.get(Orcamento, r["editando_id"]) if r.get("editando_id") else None
        if orc and orc.profissional_id == prof.id:  # revisão de um orçamento já enviado
            for k, v in campos.items():
                setattr(orc, k, v)
            orc.revisao = (orc.revisao or 1) + 1
            orc.itens.clear()
            s.flush()
        else:
            numero = (s.scalar(select(func.max(Orcamento.numero))
                               .where(Orcamento.profissional_id == prof.id)) or 0) + 1
            orc = Orcamento(profissional_id=prof.id, numero=numero, pagamento=prof.pagamento_padrao, **campos)
        numero = orc.numero
        for i in r["itens"]:
            orc.itens.append(OrcamentoItem(item_preco_id=i["item_preco_id"], descricao=i["descricao"],
                                           tipo=i.get("tipo") or "servico",
                                           quantidade=i["quantidade"], unidade=i.get("unidade"),
                                           preco_unit_centavos=i["preco_centavos"],
                                           subtotal_centavos=calculo.subtotal(i)))
        s.add(orc)
        s.flush()
        orc.pdf_path = gerar_pdf(prof, orc, self._caminho_pdf(prof, orc))
        eventos.registrar(s, prof.id, "orcamento_gerado", orcamento_id=orc.id, revisao=orc.revisao)
        self._limpar_rascunho(prof)
        if orc.revisao > 1:
            msg = (f"✅ Orçamento Nº {numero:04d} atualizado (revisão {orc.revisao}). "
                   "Encaminhe o novo PDF para o cliente.")
        else:
            msg = f"✅ Orçamento Nº {numero:04d} pronto! É só encaminhar para o cliente."
        respostas = [Resposta(arquivo=orc.pdf_path),
                     Resposta(msg + "\n\n📲 Para mandar: segure o PDF acima, toque em Encaminhar (ou Compartilhar) "
                              "e escolha o cliente no WhatsApp.\n\nQuando ele responder, me conte pelos botões. "
                              "Se pedir mudança, encaminhe a mensagem dele aqui.", botoes=botoes_pos_envio(numero))]
        link = links.url(links.criar(s, prof, "cliente", orc))
        respostas += [Resposta("🔗 Mensagem pronta para o cliente (encaminhe junto com o PDF). Pelo link ele vê, "
                               "aprova e paga pelo celular:"),
                      Resposta(textos.LINK_CLIENTE.format(numero=numero, link=link, assinatura=self._assinatura(prof)))]
        if prof.pix_chave:
            respostas += [Resposta("💸 Pix copia e cola deste orçamento (pode encaminhar ao cliente junto com o PDF):"),
                          Resposta(self._pix_do_orcamento(prof, orc))]
        else:
            respostas.append(Resposta("Dica: cadastre sua chave com /pix e os próximos orçamentos já saem com "
                                      "QR Code e Pix copia e cola."))
        return respostas

    # ------------------------------------------------------------------ comandos
    def _comando(self, s, prof, texto):
        partes = texto.split()
        cmd = partes[0].lower().split("@")[0]  # Telegram pode mandar /cmd@NomeDoBot
        arg = partes[1] if len(partes) > 1 else ""

        if cmd == "/apagarconta":
            return self._apagar_conta(s, prof, arg)
        if (prof.estado == "NOVO" or prof.estado.startswith("CADASTRO")) and cmd not in ("/start", "/ajuda"):
            return [Resposta("Vamos terminar seu cadastro primeiro 🙂 Responda a pergunta anterior.")]
        if cmd == "/start":
            if prof.estado == "NOVO" or prof.estado.startswith("CADASTRO"):
                return self._boas_vindas(s, prof)
            return [Resposta(f"Oi, {prof.nome}! 👋\n\n" + textos.MENU, botoes=BOTOES_MENU)]
        if cmd in ("/ajuda", "/menu"):
            return [Resposta(textos.MENU, botoes=BOTOES_MENU)]
        if cmd == "/comandos":
            return [Resposta(AJUDA)]
        if cmd == "/exemplo":
            return [Resposta(textos.EXEMPLO)]
        if cmd == "/corrigir":
            if prof.estado != "CONFIRMANDO":
                return [Resposta("Não tem orçamento aberto agora. Para mudar um que já foi enviado, use /editar N.")]
            return [Resposta(textos.COMO_CORRIGIR)]
        if cmd == "/editarweb":
            if arg and not arg.isdigit():
                return [Resposta("Use /editarweb N (veja os números em /orcamentos).")]
            url = self._link_editor(s, prof, int(arg) if arg else None)
            if url is None:
                return [Resposta("Não achei esse orçamento. Use /editarweb N (veja os números em /orcamentos)."
                                 if arg else "Não tem orçamento aberto agora. Use /editarweb N para um já enviado.")]
            return [Resposta(textos.LINK_EDITOR.format(link=url))]
        if cmd == "/perfil":
            dados = "\n".join(f"• {nome}: {valor or '—'}" for nome, valor in self._campos_perfil(prof))
            return [Resposta("👤 Seus dados (aparecem no orçamento):\n\n" + dados + "\n\n" + textos.COMO_MUDAR_PERFIL,
                             botoes=[[("🌐 Editar tudo no navegador", "/perfilweb")],
                                     [("🎨 Mudar o visual do PDF", "/modelo")]])]
        if cmd == "/perfilweb":
            return [Resposta(textos.LINK_PERFIL.format(link=links.url(links.criar(s, prof, "perfil"))))]
        if cmd in CAMPOS_PERFIL:
            campo, rotulo, limite = CAMPOS_PERFIL[cmd]
            valor = texto.split(None, 1)[1].strip() if len(partes) > 1 else ""
            if not valor:
                return [Resposta(f"Mande {cmd} seguido do novo valor. Ex: {cmd} {EXEMPLOS_PERFIL[cmd]}")]
            setattr(prof, campo, None if _norm(valor) in ("remover", "apagar") else valor[:limite])
            return [Resposta(f"✅ {rotulo} atualizado: {getattr(prof, campo) or 'removido'}")]
        if cmd == "/modelo":
            if arg in pdf_mod.MODELOS:
                prof.modelo_pdf = arg
                return [Resposta(f"✅ Seus orçamentos agora saem no modelo {pdf_mod.MODELOS[arg][0]}. "
                                 "Quer trocar a cor também?", botoes=self._botoes_cores())]
            return self._previas_modelos(prof)
        if cmd == "/condicoes":
            return self._mostrar_condicoes(prof)
        if cmd == "/condicao":
            resto = texto.split(None, 1)[1].strip() if len(partes) > 1 else ""
            if _norm(resto).startswith("remover "):
                alvo = _norm(resto[8:])
                antes = prof.condicoes_padrao or []
                prof.condicoes_padrao = [c for c in antes if _norm(c["rotulo"]) != alvo]
                if len(prof.condicoes_padrao) == len(antes):
                    return [Resposta("Não achei essa condição. Veja as suas em /condicoes.")]
                return [Resposta("🗑️ Condição removida.")] + self._mostrar_condicoes(prof)
            if ":" not in resto:
                return [Resposta("Mande assim: /condicao Garantia: 90 dias na mão de obra")]
            rotulo, valor = resto.split(":", 1)
            nova = calculo.limpar_condicoes([{"rotulo": rotulo, "texto": valor}])
            if not nova:
                return [Resposta("Mande assim: /condicao Garantia: 90 dias na mão de obra")]
            prof.condicoes_padrao = calculo.juntar_condicoes(prof.condicoes_padrao, nova)
            return [Resposta(f"✅ \"{nova[0]['rotulo']}: {nova[0]['texto']}\" vai em todos os orçamentos.")]
        if cmd == "/cor":
            if arg not in pdf_mod.CORES:
                return [Resposta("Escolha a cor:", botoes=self._botoes_cores())]
            prof.cor_pdf = arg
            modelo = prof.modelo_pdf or pdf_mod.MODELO_PADRAO
            png = pdf_mod.gerar_previa(prof, self._pasta_previas(prof), modelo, arg)
            return [Resposta(f"✅ Cor {pdf_mod.CORES[arg][0].lower()} salva. Assim fica o seu orçamento:", imagem=png,
                             botoes=[[("🎨 Ver outra cor", "/cor"), ("📄 Ver outros modelos", "/modelo")]])]
        if cmd == "/cancelar":
            return self._cancelar(prof)
        if cmd == "/precos":
            itens = self._itens_ordenados(prof)
            if not itens:
                return [Resposta("Sua tabela está vazia. Mande algo como \"tomada 40, chuveiro 120\".")]
            linhas = [f"{n}. {i.descricao}{f' ({i.unidade})' if i.unidade else ''} - {calculo.reais(i.preco_centavos)}"
                      + (f"  🔁 a cada {i.recorrencia_meses} meses" if i.recorrencia_meses else "")
                      for n, i in enumerate(itens, 1)]
            return [Resposta("💲 Sua tabela:\n\n" + "\n".join(linhas) +
                             "\n\nPara mudar, é só falar: \"chuveiro agora é 130\". Para tirar: /remover N\n"
                             "Serviço que se repete? /retorno N 6 (eu te lembro de oferecer de novo após 6 meses)")]
        if cmd == "/retorno":
            itens = self._itens_ordenados(prof)
            meses = partes[2] if len(partes) > 2 else ""
            if not arg.isdigit() or not 1 <= int(arg) <= len(itens) or not meses.isdigit():
                return [Resposta("Use /retorno N meses, com o número do item em /precos. Ex: /retorno 3 6\n"
                                 "Para desligar: /retorno 3 0")]
            item = itens[int(arg) - 1]
            if int(meses) == 0:
                item.recorrencia_meses = None
                return [Resposta(f"Ok, não vou mais lembrar de oferecer \"{item.descricao}\" de novo.")]
            item.recorrencia_meses = int(meses)
            item.recorrencia_texto = item.recorrencia_texto or f"de novo: {item.descricao.lower()}"
            return [Resposta(f"🔁 Combinado: {item.recorrencia_meses} meses depois de cada \"{item.descricao}\", "
                             "eu te lembro de oferecer de novo ao cliente, com mensagem pronta.")]
        if cmd == "/remover":
            itens = self._itens_ordenados(prof)
            if not arg.isdigit() or not 1 <= int(arg) <= len(itens):
                return [Resposta("Use /remover N, com o número que aparece em /precos.")]
            item = itens[int(arg) - 1]
            prof.itens_preco.remove(item)
            return [Resposta(f"🗑️ Removi \"{item.descricao}\" da tabela.")]
        if cmd == "/orcamentos":
            orcs = s.scalars(select(Orcamento).where(Orcamento.profissional_id == prof.id)
                             .order_by(Orcamento.numero.desc()).limit(10)).all()
            if not orcs:
                return [Resposta("Você ainda não tem orçamentos. Mande um áudio descrevendo o serviço!")]
            emoji = {"enviado": "📤", "aprovado": "✅", "recusado": "❌", "pago": "💰"}
            def situacao(o):
                if o.status == "aprovado" and o.recebido_centavos:
                    return f"aprovado (falta {calculo.reais(o.saldo_centavos)})"
                return o.status
            linhas = [f"{emoji.get(o.status, '')} {self._linha_orc(o)} - {situacao(o)}" for o in orcs]
            return [Resposta("Últimos orçamentos:\n\n" + "\n".join(linhas))]
        if cmd == "/editar":
            orc = self._buscar_orcamento(s, prof, arg)
            if orc is None:
                return [Resposta("Use /editar N (veja os números em /orcamentos). Você também pode já dizer a "
                                 "mudança: /editar 3 dá 10% de desconto")]
            instrucao = texto.split(None, 2)[2] if len(partes) > 2 else None
            return self._iniciar_edicao(s, prof, orc, instrucao)
        if cmd in ("/aprovado", "/recusado", "/pdf"):
            orc = self._buscar_orcamento(s, prof, arg)
            if orc is None:
                return [Resposta(f"Não achei esse orçamento. Use {cmd} N (veja os números em /orcamentos).")]
            if cmd == "/pdf":
                if not orc.pdf_path or not os.path.exists(orc.pdf_path):
                    orc.pdf_path = gerar_pdf(prof, orc, self._caminho_pdf(prof, orc))
                return [Resposta(arquivo=orc.pdf_path)]
            if cmd == "/aprovado":
                if orc.status == "pago":
                    return [Resposta(f"O orçamento Nº {orc.numero:04d} já está pago 💰")]
                orc.status, orc.aprovado_em, orc.cobrancas = "aprovado", datetime.now(), 0
                return [Resposta(textos.APROVADO.format(numero=orc.numero, n=orc.numero),
                                 botoes=[[("💰 Já recebi tudo", f"/pago {orc.numero}")]])]
            orc.status = "recusado"
            return [Resposta(f"Anotado: orçamento Nº {orc.numero:04d} recusado.")]
        if cmd == "/pago":
            orc = self._buscar_orcamento(s, prof, arg)
            if orc is None:
                return [Resposta("Use /pago N (ou /pago N 300 se foi só uma parte). Veja os números em /areceber.")]
            valor = calculo.ler_valor(texto.split(None, 2)[2]) if len(partes) > 2 else None
            return self._registrar_pagamento(s, prof, orc, valor)
        if cmd == "/recibo":
            orc = self._buscar_orcamento(s, prof, arg)
            if orc is None or not orc.pagamentos:
                return [Resposta("Não achei recebimento nesse orçamento. Registre com /pago N.")]
            pag = orc.pagamentos[-1]
            if not pag.recibo_path or not os.path.exists(pag.recibo_path):
                pag.recibo_path = gerar_recibo(prof, orc, pag, len(orc.pagamentos),
                                               self._caminho_recibo(prof, orc, len(orc.pagamentos)))
            return [Resposta(arquivo=pag.recibo_path)]
        if cmd == "/areceber":
            abertos = self._a_receber(s, prof)
            if not abertos:
                return [Resposta("Nada a receber no momento 👌")]
            linhas = [f"Nº {o.numero:04d} - {o.cliente.nome if o.cliente else 'sem cliente'} - falta "
                      f"{calculo.reais(o.saldo_centavos)}" for o in abertos]
            total = sum(o.saldo_centavos for o in abertos)
            return [Resposta("💰 A receber:\n\n" + "\n".join(linhas) + f"\n\nTotal: {calculo.reais(total)}\n"
                             "Recebeu? /pago N   |   Precisa cobrar? /cobrar N")]
        if cmd == "/cobrar":
            orc = self._buscar_orcamento(s, prof, arg)
            if orc is None or orc.saldo_centavos == 0:
                return [Resposta("Use /cobrar N com um orçamento que ainda tem saldo (veja /areceber).")]
            return self._mensagens_cobranca(prof, orc, None)
        if cmd == "/resumo":
            return [Resposta(self._texto_resumo(s, prof, datetime.now()) or "Ainda não há movimento para resumir.")]
        if cmd == "/pix":
            if not arg:
                atual = f"Sua chave Pix: {prof.pix_chave}" if prof.pix_chave else "Você ainda não tem chave Pix cadastrada."
                return [Resposta(atual + "\n\nPara trocar: /pix SUA_CHAVE   |   para tirar dos orçamentos: /pix remover")]
            if _norm(arg) in ("remover", "tirar", "apagar"):
                prof.pix_chave = None
                return [Resposta("Chave Pix removida. Os próximos orçamentos saem sem Pix.")]
            return [self._definir_pix(prof, texto.split(None, 1)[1])]
        if cmd == "/adiar":
            orc = self._buscar_orcamento(s, prof, arg)
            if orc is None:
                return [Resposta("Use /adiar N (veja os números em /orcamentos).")]
            orc.enviado_em, orc.lembretes = datetime.now(), 0
            dias = config.FOLLOWUP_DIAS[0] if config.FOLLOWUP_DIAS else 3
            return [Resposta(f"Combinado, te lembro do orçamento Nº {orc.numero:04d} de novo em {dias} dias.")]
        return [Resposta("Comando desconhecido. /ajuda para ver os comandos.")]

    # ------------------------------------------------------------------ lembretes (follow-up)
    def verificar_followups(self, agora: datetime | None = None, prefixo_canal: str = "") -> list[tuple[str, list[Resposta]]]:
        """Chamado periodicamente pelo adaptador do canal. Devolve [(canal_id, respostas)] para enviar.

        Para cada orçamento ainda "enviado", dá um lembrete quando passam FOLLOWUP_DIAS[0] dias, outro em
        FOLLOWUP_DIAS[1] etc. Só dentro de HORARIO_LEMBRETES, no fuso configurado.
        """
        agora_naive = agora or datetime.now()  # mesmo relógio usado ao gravar enviado_em
        local = agora_naive.astimezone(ZoneInfo(config.FUSO))  # só para a janela de horário
        inicio, fim = config.HORARIO_LEMBRETES
        if not inicio <= local.hour < fim:
            return []
        saida = []
        with self.Sessao() as s:
            pendentes = self._orcamentos_com_prof(s, prefixo_canal, Orcamento.status == "enviado",
                                                  Orcamento.lembretes < len(config.FOLLOWUP_DIAS))
            for orc, prof in pendentes:
                decorrido = agora_naive - (orc.enviado_em or orc.criado_em)
                etapa = self._etapa_devida(decorrido, config.FOLLOWUP_DIAS, orc.lembretes, folga_dias=30)
                if etapa is None:
                    continue
                orc.lembretes = len(config.FOLLOWUP_DIAS) if etapa == "encerrar" else etapa + 1
                if etapa != "encerrar":
                    saida.append((prof.canal_id, self._mensagens_lembrete(prof, orc, decorrido.days, etapa)))
            s.commit()
        return saida

    @staticmethod
    def _etapa_devida(decorrido: timedelta, dias: list[int], feitas: int, folga_dias: int):
        """Qual lembrete mandar agora: só o mais recente que já venceu (se o bot ficou desligado, não manda
        vários em sequência). Muito tempo depois do último prazo, encerra sem avisar ("encerrar").
        Devolve o índice do lembrete, "encerrar" ou None (nada a fazer)."""
        vencidas = [i for i, d in enumerate(dias) if decorrido >= timedelta(days=d)]
        if not vencidas or vencidas[-1] < feitas:
            return None
        if decorrido > timedelta(days=dias[-1] + folga_dias):
            return "encerrar"
        return vencidas[-1]

    def _mensagens_lembrete(self, prof, orc, dias, etapa) -> list[Resposta]:
        nome_cli = orc.cliente.nome if orc.cliente else None
        total = calculo.reais(orc.total_centavos)
        aviso = textos.LEMBRETE_PRESTADOR.format(numero=orc.numero, numero_curto=orc.numero, total=total,
                                                 cliente=nome_cli or "sem nome", dias=dias)
        modelo = textos.LEMBRETE_CLIENTE_1 if etapa == 0 else textos.LEMBRETE_CLIENTE_2
        assinatura = self._assinatura(prof)
        texto_cliente = modelo.format(saudacao=f", {nome_cli}" if nome_cli else "", numero=orc.numero, total=total,
                                      validade=f"{orc.validade:%d/%m}", assinatura=assinatura)
        n = orc.numero
        botoes = [[("👍 Aprovou", f"/aprovado {n}"), ("👎 Recusou", f"/recusado {n}")],
                  [("⏰ Lembrar depois", f"/adiar {n}")]]
        return [Resposta(aviso, botoes=botoes), Resposta(texto_cliente)]

    # ------------------------------------------------------------------ pagamentos e recibo
    def _pagamento_por_texto(self, s, prof, dados):
        valor = round(dados["valor_pago"] * 100) if dados.get("valor_pago") else None
        orc = self._localizar_orcamento(s, prof, dados)
        if orc is None:
            abertos = self._a_receber(s, prof)
            sufixo = f" {calculo.reais(valor).replace('R$ ', '')}" if valor else ""
            lista = "\n".join(f"Nº {o.numero:04d} - {o.cliente.nome if o.cliente else 'sem cliente'} - falta "
                              f"{calculo.reais(o.saldo_centavos)}" for o in abertos)
            return [Resposta("De qual orçamento foi esse pagamento? Responda com /pago N" + sufixo +
                             (f"\n\n{lista}" if lista else ""))]
        return self._registrar_pagamento(s, prof, orc, valor)

    def _registrar_pagamento(self, s, prof, orc, valor: int | None):
        saldo = orc.saldo_centavos
        if saldo == 0 and orc.pagamentos:
            return [Resposta(f"O orçamento Nº {orc.numero:04d} já está quitado 💰 (/recibo {orc.numero})")]
        valor = valor or saldo
        agora = datetime.now()
        if orc.status in ("enviado", "recusado"):
            orc.aprovado_em = orc.aprovado_em or agora
        pag = Pagamento(valor_centavos=valor, recebido_em=agora)
        orc.pagamentos.append(pag)
        s.flush()
        orc.status = "pago" if orc.saldo_centavos == 0 else "aprovado"
        seq = len(orc.pagamentos)
        pag.recibo_path = gerar_recibo(prof, orc, pag, seq, self._caminho_recibo(prof, orc, seq))
        if orc.status == "pago":
            msg = f"✅ Recebimento de {calculo.reais(valor)} registrado. Orçamento Nº {orc.numero:04d} quitado! 🎉"
        else:
            msg = (f"✅ Recebimento de {calculo.reais(valor)} registrado no orçamento Nº {orc.numero:04d}. "
                   f"Falta {calculo.reais(orc.saldo_centavos)}.")
        if valor > saldo > 0:
            msg += f"\n(Obs: o valor é maior que o saldo, que era {calculo.reais(saldo)}.)"
        return [Resposta(arquivo=pag.recibo_path), Resposta(msg + "\nO recibo está aí, pronto pra encaminhar ao cliente.")]

    def _a_receber(self, s, prof):
        aprovados = s.scalars(select(Orcamento).where(Orcamento.profissional_id == prof.id,
                                                      Orcamento.status == "aprovado")
                              .order_by(Orcamento.numero)).all()
        return [o for o in aprovados if o.saldo_centavos > 0]

    def _mensagens_cobranca(self, prof, orc, dias: int | None) -> list[Resposta]:
        nome_cli = orc.cliente.nome if orc.cliente else None
        saldo = calculo.reais(orc.saldo_centavos)
        respostas = []
        if dias is not None:
            respostas.append(Resposta(textos.COBRANCA_PRESTADOR.format(
                cliente=nome_cli or "cliente sem nome", numero=orc.numero, n=orc.numero, dias=dias, saldo=saldo),
                botoes=[[("💰 Já recebi", f"/pago {orc.numero}")]]))
        codigo = (pix.gerar_copia_e_cola(prof.pix_chave, prof.nome or "", prof.cidade or "BRASIL",
                                         orc.saldo_centavos, f"ORC{orc.numero:04d}") if prof.pix_chave else None)
        respostas.append(Resposta(textos.COBRANCA_CLIENTE.format(
            saudacao=f", {nome_cli}" if nome_cli else "", numero=orc.numero, saldo=saldo,
            pix=" Segue o Pix copia e cola logo abaixo." if codigo else "", assinatura=self._assinatura(prof))))
        if codigo:
            respostas.append(Resposta(codigo))
        return respostas

    # ------------------------------------------------------------------ rotinas periódicas
    def rotina_periodica(self, agora: datetime | None = None, prefixo_canal: str = "") -> list[tuple[str, list[Resposta]]]:
        """Tudo que o bot faz sozinho: lembretes de resposta e de cobrança, resumo semanal e reativação.
        O adaptador do canal chama isso a cada ~30 minutos e envia o que voltar."""
        return (self.verificar_followups(agora, prefixo_canal) + self.verificar_cobrancas(agora, prefixo_canal)
                + self.verificar_resumos(agora, prefixo_canal) + self.verificar_reativacoes(agora, prefixo_canal))

    @staticmethod
    def _horario(agora: datetime | None):
        """(agora no relógio do servidor, agora no fuso configurado) ou None fora do horário comercial."""
        agora = agora or datetime.now()
        local = agora.astimezone(ZoneInfo(config.FUSO))
        inicio, fim = config.HORARIO_LEMBRETES
        return (agora, local) if inicio <= local.hour < fim else None

    def _orcamentos_com_prof(self, s, prefixo_canal, *condicoes):
        return s.execute(select(Orcamento, Profissional)
                         .join(Profissional, Orcamento.profissional_id == Profissional.id)
                         .where(Profissional.canal_id.startswith(prefixo_canal), *condicoes)
                         .options(selectinload(Orcamento.cliente), selectinload(Orcamento.itens),
                                  selectinload(Orcamento.pagamentos))).all()

    def verificar_cobrancas(self, agora=None, prefixo_canal="") -> list[tuple[str, list[Resposta]]]:
        horario = self._horario(agora)
        if not horario:
            return []
        agora, _ = horario
        saida = []
        with self.Sessao() as s:
            for orc, prof in self._orcamentos_com_prof(s, prefixo_canal, Orcamento.status == "aprovado",
                                                       Orcamento.cobrancas < len(config.COBRANCA_DIAS)):
                if orc.saldo_centavos == 0:
                    continue
                decorrido = agora - (orc.aprovado_em or orc.enviado_em or orc.criado_em)
                etapa = self._etapa_devida(decorrido, config.COBRANCA_DIAS, orc.cobrancas, folga_dias=60)
                if etapa is None:
                    continue
                orc.cobrancas = len(config.COBRANCA_DIAS) if etapa == "encerrar" else etapa + 1
                if etapa != "encerrar":
                    saida.append((prof.canal_id, self._mensagens_cobranca(prof, orc, decorrido.days)))
            s.commit()
        return saida

    def verificar_resumos(self, agora=None, prefixo_canal="") -> list[tuple[str, list[Resposta]]]:
        horario = self._horario(agora)
        if not horario:
            return []
        agora, local = horario
        if local.weekday() != config.RESUMO_DIA or local.hour < config.RESUMO_HORA:
            return []
        saida = []
        with self.Sessao() as s:
            profs = s.scalars(select(Profissional).where(Profissional.canal_id.startswith(prefixo_canal),
                                                         Profissional.estado.notlike("CADASTRO%"))).all()
            for prof in profs:
                if prof.ultimo_resumo == local.date():
                    continue
                texto = self._texto_resumo(s, prof, agora)
                prof.ultimo_resumo = local.date()
                if texto:
                    saida.append((prof.canal_id, [Resposta(texto)]))
            s.commit()
        return saida

    def _texto_resumo(self, s, prof, agora: datetime) -> str | None:
        inicio = agora - timedelta(days=7)
        orcs = s.scalars(select(Orcamento).where(Orcamento.profissional_id == prof.id)).all()
        if not orcs:
            return None
        enviados = [o for o in orcs if o.criado_em >= inicio]
        aprovados = [o for o in orcs if o.aprovado_em and o.aprovado_em >= inicio]
        pagamentos = [p for o in orcs for p in o.pagamentos]
        recebido_semana = sum(p.valor_centavos for p in pagamentos if p.recebido_em >= inicio)
        recebido_ano = sum(p.valor_centavos for p in pagamentos if p.recebido_em.year == agora.year)
        a_receber = sum(o.saldo_centavos for o in orcs if o.status == "aprovado")
        sem_resposta = sum(1 for o in orcs if o.status == "enviado")
        r = calculo.reais
        linhas = [f"📊 Resumo da semana ({inicio:%d/%m} a {agora:%d/%m})", "",
                  f"📝 Orçamentos feitos: {len(enviados)} ({r(sum(o.total_centavos for o in enviados))})",
                  f"✅ Aprovados: {len(aprovados)} ({r(sum(o.total_centavos for o in aprovados))})",
                  f"💵 Recebido: {r(recebido_semana)}",
                  f"⏳ A receber: {r(a_receber)}" + (" (/areceber)" if a_receber else ""),
                  f"📤 Sem resposta: {sem_resposta}", "",
                  f"Recebido em {agora.year}: {r(recebido_ano)}"]
        limite = config.LIMITE_MEI * 100
        if limite and recebido_ano >= 0.8 * limite:
            linhas.append(f"⚠️ Isso já é {recebido_ano * 100 // limite}% do limite anual do MEI ({r(limite)}). "
                          "Vale conversar com um contador.")
        return "\n".join(linhas)

    def verificar_reativacoes(self, agora=None, prefixo_canal="") -> list[tuple[str, list[Resposta]]]:
        horario = self._horario(agora)
        if not horario:
            return []
        agora, _ = horario
        saida = []
        with self.Sessao() as s:
            candidatos = self._orcamentos_com_prof(s, prefixo_canal, Orcamento.status.in_(["aprovado", "pago"]),
                                                   Orcamento.reativado_em.is_(None))
            # Carregado uma vez só (e não uma consulta por orçamento): recorrência dos itens e último orçamento
            # de cada cliente, para saber se ele já voltou.
            recorrencias = {i.id: (i.recorrencia_meses, i.recorrencia_texto) for i in s.scalars(
                select(ItemPreco).where(ItemPreco.recorrencia_meses.is_not(None)))}
            ultimo_por_cliente = dict(s.execute(select(Orcamento.cliente_id, func.max(Orcamento.numero))
                                                .where(Orcamento.cliente_id.is_not(None))
                                                .group_by(Orcamento.cliente_id)).all())
            inicio_dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)
            feitas_hoje = dict(s.execute(select(Orcamento.profissional_id, func.count(Orcamento.id))
                                         .where(Orcamento.reativado_em >= inicio_dia)
                                         .group_by(Orcamento.profissional_id)).all())
            for orc, prof in sorted(candidatos, key=lambda par: par[0].aprovado_em or par[0].criado_em, reverse=True):
                if feitas_hoje.get(prof.id, 0) >= config.REATIVACOES_POR_DIA:
                    continue  # já mandou o suficiente hoje: o resto fica para amanhã
                recorrente = self._item_recorrente(orc, recorrencias)
                if not recorrente:
                    continue
                meses, servico, retorno = recorrente
                decorrido = agora - (orc.aprovado_em or orc.enviado_em or orc.criado_em)
                if decorrido < timedelta(days=round(meses * 30.44)):
                    continue
                orc.reativado_em = agora
                if orc.cliente_id and ultimo_por_cliente.get(orc.cliente_id, 0) > orc.numero:
                    continue  # o cliente já fez outro orçamento depois: não precisa lembrar
                feitas_hoje[prof.id] = feitas_hoje.get(prof.id, 0) + 1
                meses = max(meses, round(decorrido.days / 30.44))  # o texto diz quanto tempo passou de verdade
                nome_cli = orc.cliente.nome if orc.cliente else None
                aviso = textos.REATIVACAO_PRESTADOR.format(meses=meses, servico=servico, numero=orc.numero,
                                                           cliente=nome_cli or "um cliente", retorno=retorno)
                msg = textos.REATIVACAO_CLIENTE.format(saudacao=f", {nome_cli}" if nome_cli else "", meses=meses,
                                                       servico=servico.lower(), retorno=retorno,
                                                       assinatura=self._assinatura(prof))
                saida.append((prof.canal_id, [Resposta(aviso), Resposta(msg)]))
            s.commit()
        return saida

    @staticmethod
    def _item_recorrente(orc, recorrencias: dict) -> tuple[int, str, str] | None:
        """(meses, serviço feito, o que oferecer) do item recorrente com menor prazo, ou None."""
        opcoes = []
        for item in orc.itens:
            if item.item_preco_id in recorrencias:
                meses, texto = recorrencias[item.item_preco_id]
                opcoes.append((meses, item.descricao, texto or "uma nova visita"))
            elif item.item_preco_id is None and (rec := catalogo.recorrencia(item.descricao)):
                opcoes.append((rec[0], item.descricao, rec[1]))
        return min(opcoes) if opcoes else None

    # ------------------------------------------------------------------ auxiliares
    def _assinatura(self, prof) -> str:
        return (prof.nome or "") + (f" - {prof.telefone}" if prof.telefone else "")

    def _caminho_recibo(self, prof, orc, seq) -> str:
        return os.path.join(self.pasta, "pdfs", str(prof.id), f"recibo_{orc.numero:04d}_{seq}.pdf")

    def _cancelar(self, prof):
        if prof.estado.startswith("CADASTRO"):
            return [Resposta("Vamos terminar seu cadastro primeiro 🙂")]
        numero = (prof.rascunho or {}).get("editando_numero")
        self._limpar_rascunho(prof)
        if numero:
            return [Resposta(f"Alteração descartada. O orçamento Nº {numero:04d} continua como estava.")]
        return [Resposta("Orçamento descartado. Mande um novo quando quiser.")]

    @staticmethod
    def _agora() -> datetime:
        return datetime.now()

    def _orcamentos_no_mes(self, s, prof, agora: datetime) -> int:
        """Orçamentos NOVOS do mês (revisão mantém o criado_em original, então não conta de novo)."""
        inicio = agora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return s.scalar(select(func.count()).select_from(Orcamento).where(
            Orcamento.profissional_id == prof.id, Orcamento.criado_em >= inicio)) or 0

    def _limite_atingido(self, s, prof) -> list[Resposta] | None:
        if prof.plano == "piloto":
            return None
        agora = self._agora()
        if self._orcamentos_no_mes(s, prof, agora) < config.LIMITE_GRATIS:
            return None
        eventos.registrar(s, prof.id, "limite_atingido")
        proximo = (agora.replace(day=1) + timedelta(days=32)).replace(day=1)
        return [Resposta(textos.LIMITE_ATINGIDO.format(limite=config.LIMITE_GRATIS, renova=f"{proximo:%d/%m}"))]

    def _apagar_conta(self, s, prof, arg) -> list[Resposta]:
        if arg != "confirmar":
            return [Resposta(textos.APAGAR_CONTA, botoes=[[("🗑️ Apagar tudo", "/apagarconta confirmar")]])]
        orcs = s.scalars(select(Orcamento).where(Orcamento.profissional_id == prof.id)).all()
        ids = [o.id for o in orcs]
        if ids:
            s.execute(delete(Aceite).where(Aceite.orcamento_id.in_(ids)))
        # links do cliente continuam existindo, sem orçamento: a página mostra "não está mais disponível"
        s.execute(update(Link).where(Link.profissional_id == prof.id, Link.tipo == "cliente").values(orcamento_id=None))
        s.execute(delete(Link).where(Link.profissional_id == prof.id, Link.tipo != "cliente"))
        for o in orcs:
            s.delete(o)  # itens e pagamentos vão junto (cascade)
        s.execute(delete(Cliente).where(Cliente.profissional_id == prof.id))
        s.execute(delete(Evento).where(Evento.profissional_id == prof.id))
        for caminho in (os.path.join(self.pasta, "pdfs", str(prof.id)), os.path.join(self.pasta, "previas", str(prof.id))):
            shutil.rmtree(caminho, ignore_errors=True)
        if prof.logo_path and os.path.exists(prof.logo_path):
            os.remove(prof.logo_path)
        s.delete(prof)  # tabela de preços vai junto (cascade)
        return [Resposta(textos.CONTA_APAGADA)]

    def _salvar_logo(self, prof, foto: bytes):
        pasta = os.path.join(self.pasta, "logos")
        os.makedirs(pasta, exist_ok=True)
        caminho = os.path.join(pasta, f"{prof.id}.jpg")
        with open(caminho, "wb") as f:
            f.write(foto)
        prof.logo_path = caminho
        return Resposta("🖼️ Logo salva! Ela vai aparecer nos próximos orçamentos.")

    def _salvar_precos(self, s, prof, precos: list[dict]) -> str:
        existentes = {}
        for item in prof.itens_preco:
            for nome in [item.descricao, *(item.sinonimos or [])]:
                existentes[_norm(nome)] = item
        linhas = []
        for p in precos:
            if p["preco"] <= 0:
                continue
            centavos = round(p["preco"] * 100)
            item = existentes.get(_norm(p["descricao"])) or next(
                (existentes[_norm(x)] for x in p.get("sinonimos", []) if _norm(x) in existentes), None)
            if item:
                item.preco_centavos = centavos
                item.sinonimos = sorted(set(item.sinonimos or []) | set(p.get("sinonimos", [])))
                linhas.append(f"✏️ {item.descricao}: {calculo.reais(centavos)}")
            else:
                item = self._novo_item(prof, p["descricao"], p.get("unidade"), centavos, p.get("sinonimos", []))
                existentes[_norm(item.descricao)] = item
                linhas.append(f"➕ {item.descricao}: {calculo.reais(centavos)}")
        s.flush()
        return "💲 Tabela atualizada:\n" + "\n".join(linhas) if linhas else "Nenhum preço válido encontrado."

    def _novo_item(self, prof, descricao, unidade, centavos, sinonimos) -> ItemPreco:
        """Cria item na tabela, juntando sinônimos e recorrência do catálogo quando o serviço é de lá."""
        extras = next((sin for d, _, sin in catalogo.servicos_da_profissao(prof.profissao)
                       if _norm(d) == _norm(descricao)), [])
        rec = catalogo.recorrencia(descricao)
        item = ItemPreco(descricao=descricao, unidade=unidade, preco_centavos=centavos,
                         sinonimos=sorted(set(sinonimos) | set(extras)),
                         recorrencia_meses=rec[0] if rec else None, recorrencia_texto=rec[1] if rec else None)
        prof.itens_preco.append(item)
        return item

    def _tabela_para_ia(self, prof) -> list[dict]:
        """O que a IA enxerga da tabela: SEM preços."""
        return [{"id": i.id, "descricao": i.descricao, "unidade": i.unidade, "sinonimos": i.sinonimos or []}
                for i in prof.itens_preco]

    def _tabela_precos(self, prof) -> dict[int, dict]:
        return {i.id: {"descricao": i.descricao, "unidade": i.unidade, "preco_centavos": i.preco_centavos,
                       "tipo": i.tipo or "servico"} for i in prof.itens_preco}

    def _reaplicar_precos(self, prof, rascunho):
        r = copy.deepcopy(rascunho)
        tabela = self._tabela_precos(prof)
        for i in r["itens"]:
            if i.get("origem") == "tabela" and i.get("item_preco_id") in tabela:
                i["preco_centavos"] = tabela[i["item_preco_id"]]["preco_centavos"]
        return r

    def _itens_ordenados(self, prof):
        return sorted(prof.itens_preco, key=lambda i: _norm(i.descricao))

    def _buscar_orcamento(self, s, prof, arg):
        if not arg.isdigit():
            return None
        return s.scalar(select(Orcamento).where(Orcamento.profissional_id == prof.id,
                                                Orcamento.numero == int(arg)))

    def _montar(self, prof, dados):
        """Monta o rascunho a partir da IA, mantendo o vínculo se for revisão de orçamento já enviado."""
        novo = calculo.montar_rascunho(dados, self._tabela_precos(prof))
        for chave in ("editando_id", "editando_numero"):
            if (prof.rascunho or {}).get(chave):
                novo[chave] = prof.rascunho[chave]
        return novo

    def _recentes(self, s, prof, n):
        return s.scalars(select(Orcamento).where(Orcamento.profissional_id == prof.id)
                         .order_by(Orcamento.numero.desc()).limit(n)).all()

    @staticmethod
    def _linha_orc(o) -> str:
        rev = f" (rev. {o.revisao})" if (o.revisao or 1) > 1 else ""
        return (f"Nº {o.numero:04d}{rev} - {o.cliente.nome if o.cliente else 'sem cliente'} - "
                f"{calculo.reais(o.total_centavos)}")

    @staticmethod
    def _pix_do_orcamento(prof, orc) -> str:
        return pix.gerar_copia_e_cola(prof.pix_chave, prof.nome or "", prof.cidade or "BRASIL",
                                      orc.total_centavos, f"ORC{orc.numero:04d}")

    def _caminho_pdf(self, prof, orc) -> str:
        rev = f"_r{orc.revisao}" if (orc.revisao or 1) > 1 else ""
        return os.path.join(self.pasta, "pdfs", str(prof.id), f"orcamento_{orc.numero:04d}{rev}.pdf")

    def _guardar_rascunho(self, prof, rascunho):
        prof.rascunho = copy.deepcopy(rascunho)
        flag_modified(prof, "rascunho")

    def _limpar_rascunho(self, prof):
        prof.rascunho = None
        prof.estado = "OCIOSO"

    @staticmethod
    def _pergunta_preco(item) -> str:
        unidade = f" (por {item['unidade']})" if item.get("unidade") and item["unidade"] != "un" else ""
        return (f'❓ "{item["descricao"]}" ainda não está na sua tabela.\n'
                f"Quanto você cobra{unidade}? Responda só o valor, ex: 80 ou 80,50")

    # ------------------------------------------------------------------ editor pelo navegador
    def _link_editor(self, s, prof, numero: int | None) -> str | None:
        """Link do editor de um orçamento enviado (numero) ou do rascunho em conferência (numero=None)."""
        if numero is None:
            if prof.estado != "CONFIRMANDO" or not prof.rascunho or not prof.rascunho.get("itens"):
                return None
            return links.url(links.criar(s, prof, "editor"))
        orc = self._buscar_orcamento(s, prof, str(numero))
        return links.url(links.criar(s, prof, "editor", orc)) if orc else None

    def link_editor(self, canal_id: str, numero: int | None) -> str | None:
        with self.Sessao() as s:
            prof = s.scalar(select(Profissional).where(Profissional.canal_id == canal_id))
            url = self._link_editor(s, prof, numero) if prof else None
            s.commit()
            return url

    def dados_editor(self, prof, orc) -> dict:
        """Estado atual para preencher o formulário do editor (orc=None: o rascunho em conferência)."""
        r = self._orc_para_rascunho(prof, orc) if orc is not None else copy.deepcopy(prof.rascunho or {})
        condicoes = (r.get("condicoes") or []) if orc is not None else calculo.juntar_condicoes(
            prof.condicoes_padrao, r.get("condicoes"))
        return {"cliente": r.get("cliente") or {}, "itens": r.get("itens") or [], "observacoes": r.get("observacoes"),
                "desconto": r.get("desconto"), "condicoes": condicoes}

    def validar_edicao(self, prof, dados: dict) -> tuple[list[str], dict | None]:
        """Formulário do editor -> (erros, rascunho). Com qualquer erro, o rascunho é None e nada é salvo."""
        erros, itens = [], []
        tabela = self._tabela_precos(prof)
        por_nome = {_norm(v["descricao"]): k for k, v in tabela.items()}
        for n, item in enumerate(dados.get("itens") or [], 1):
            descricao = " ".join(str(item.get("descricao") or "").split())
            if not descricao:
                continue  # linha em branco
            if len(descricao) > 200:
                erros.append(f"Descrição muito longa (máx. 200) no item {n}")
            qtd = calculo._numero(item.get("quantidade"))
            if qtd is None or qtd <= 0:
                erros.append(f"Quantidade precisa ser maior que zero (item {n})")
            preco = calculo.ler_valor(str(item.get("preco") or ""))
            if preco is None and str(item.get("preco") or "").strip() not in ("0", "0,00"):
                erros.append(f"Preço inválido no item {n}")
                preco = None
            preco = preco or 0
            id_ = item.get("item_preco_id")
            id_ = int(id_) if str(id_ or "").isdigit() and int(id_) in tabela else por_nome.get(_norm(descricao))
            origem = "tabela" if id_ is not None and tabela[id_]["preco_centavos"] == preco else "informado"
            tipo = item.get("tipo") if item.get("tipo") in calculo.TIPOS else (
                tabela[id_]["tipo"] if id_ is not None else "servico")
            itens.append({"descricao": descricao, "quantidade": qtd or 0, "tipo": tipo, "unidade": (item.get("unidade") or "").strip()[:30] or None,
                          "item_preco_id": id_, "preco_centavos": preco, "origem": origem})
        if not itens and not erros:
            erros.append("O orçamento precisa ter pelo menos um item")
        desconto = None
        d = dados.get("desconto") or {}
        if d.get("tipo") in ("valor", "percentual") and str(d.get("valor") or "").strip():
            if d["tipo"] == "valor":
                v = calculo.ler_valor(str(d["valor"]))
                if v is None:
                    erros.append("Desconto inválido")
                elif v > 0:
                    desconto = {"tipo": "valor", "valor": v / 100}
            else:
                v = calculo._numero(str(d["valor"]).replace("%", ""))
                if v is None or not 0 <= v < 100:
                    erros.append("Desconto em % precisa ser entre 0 e 99")
                elif v > 0:
                    desconto = {"tipo": "percentual", "valor": v}
        cli = dados.get("cliente") or {}
        cliente = {k: (" ".join(str(cli.get(k) or "").split())[:limite] or None)
                   for k, limite in (("nome", 120), ("endereco", 250), ("telefone", 40))}
        obs = " ".join(str(dados.get("observacoes") or "").split())[:1000] or None
        if erros:
            return erros, None
        return [], {"cliente": cliente, "itens": itens, "observacoes": obs, "desconto": desconto,
                    "condicoes": calculo.limpar_condicoes(dados.get("condicoes")), "condicoes_finais": True}

    def salvar_edicao(self, prof_id: int, orc_id: int | None, dados: dict) -> tuple[list[str], list[Resposta], int | None]:
        """Salva o que veio do editor: gera a revisão (ou o orçamento novo, se for o rascunho) e o PDF.
        Devolve (erros, respostas para o chat, id do orçamento)."""
        with self.Sessao() as s:
            prof = s.get(Profissional, prof_id)
            erros, rascunho = self.validar_edicao(prof, dados)
            if erros:
                return erros, [], None
            guardado = None
            if orc_id is not None:
                orc = s.get(Orcamento, orc_id)
                if orc is None or orc.profissional_id != prof.id:
                    return ["Orçamento não encontrado"], [], None
                rascunho.update(editando_id=orc.id, editando_numero=orc.numero)
                if prof.rascunho:  # ele está no meio de outro orçamento no chat: não pode perder
                    guardado = (prof.estado, copy.deepcopy(prof.rascunho))
            else:
                if prof.estado != "CONFIRMANDO" or not prof.rascunho:
                    return ["Esse rascunho não está mais aberto no chat. Peça um link novo com /editarweb."], [], None
                for chave in ("editando_id", "editando_numero"):
                    if prof.rascunho.get(chave):
                        rascunho[chave] = prof.rascunho[chave]
            self._guardar_rascunho(prof, rascunho)
            respostas = self._finalizar(s, prof)
            numero = rascunho.get("editando_numero") or s.scalar(
                select(func.max(Orcamento.numero)).where(Orcamento.profissional_id == prof.id))
            novo = s.scalar(select(Orcamento).where(Orcamento.profissional_id == prof.id, Orcamento.numero == numero))
            if guardado:
                prof.estado = guardado[0]
                self._guardar_rascunho(prof, guardado[1])
            s.commit()
            return [], [Resposta("🌐 Alteração feita pelo navegador.")] + respostas, novo.id

    def salvar_perfil(self, prof_id: int, dados: dict) -> list[str]:
        """Perfil e tabela vindos do navegador. Devolve os erros; vazio = salvo. Com erro, nada é gravado."""
        with self.Sessao() as s:
            prof = s.get(Profissional, prof_id)
            erros = []
            limpo = lambda v, n: " ".join(str(v or "").split())[:n] or None
            nome = limpo(dados.get("nome"), 120)
            if not nome:
                erros.append("O nome não pode ficar vazio")
            pix_txt = (dados.get("pix") or "").strip()
            pix_chave = None
            if pix_txt and pix_txt == prof.pix_chave:
                pix_chave = prof.pix_chave  # a chave salva (já normalizada) voltou sem mudança
            elif pix_txt:
                achou = pix.normalizar_chave(re.sub(r"(?i)^\s*(cpf|cnpj|celular|telefone|e-?mail)[:\s]*", "", pix_txt))
                if achou is None:
                    erros.append("Chave Pix não reconhecida")
                elif achou[1] == "ambigua":
                    erros.append("Esses 11 dígitos podem ser CPF ou celular: escreva como 000.000.000-00 ou (46) 99999-0000")
                else:
                    pix_chave = achou[0]
            sinal_txt = str(dados.get("sinal") if dados.get("sinal") is not None else "").strip().replace("%", "")
            sinal = None
            if sinal_txt:
                sinal = int(sinal_txt) if sinal_txt.isdigit() else -1
                if not 0 <= sinal <= 100:
                    erros.append("O sinal precisa ser de 0 a 100%")
            modelo = dados.get("modelo") if dados.get("modelo") in pdf_mod.MODELOS else prof.modelo_pdf
            cor = dados.get("cor") if dados.get("cor") in pdf_mod.CORES else prof.cor_pdf
            tabela, atuais = [], {i.id: i for i in prof.itens_preco}
            for linha in dados.get("tabela") or []:
                descricao = limpo(linha.get("descricao"), 200)
                id_ = int(linha["id"]) if str(linha.get("id") or "").isdigit() else None
                if id_ is not None and id_ not in atuais:
                    continue  # id de outro profissional ou adulterado: ignora
                if linha.get("remover") or not descricao:
                    tabela.append((id_, None))
                    continue
                preco = calculo.ler_valor(str(linha.get("preco") or ""))
                if preco is None:
                    erros.append(f"Preço inválido em \"{descricao}\"")
                    continue
                tipo = linha.get("tipo") if linha.get("tipo") in calculo.TIPOS else "servico"
                tabela.append((id_, {"descricao": descricao, "unidade": limpo(linha.get("unidade"), 30),
                                     "tipo": tipo, "preco_centavos": preco}))
            if erros:
                return erros
            prof.nome, prof.profissao = nome, limpo(dados.get("profissao"), 80)
            prof.telefone, prof.cidade = limpo(dados.get("telefone"), 40), limpo(dados.get("cidade"), 80)
            prof.pagamento_padrao, prof.pix_chave = limpo(dados.get("pagamento"), 200), pix_chave
            prof.sinal_percentual, prof.modelo_pdf, prof.cor_pdf = sinal, modelo, cor
            prof.condicoes_padrao = calculo.limpar_condicoes(dados.get("condicoes"))
            for id_, valores in tabela:
                if valores is None:
                    if id_ is not None:
                        prof.itens_preco.remove(atuais[id_])
                elif id_ is None:
                    novo = self._novo_item(prof, valores["descricao"], valores["unidade"], valores["preco_centavos"], [])
                    novo.tipo = valores["tipo"]
                else:
                    item = atuais[id_]
                    item.descricao, item.unidade = valores["descricao"], valores["unidade"]
                    item.tipo, item.preco_centavos = valores["tipo"], valores["preco_centavos"]
            s.commit()
            return []

    # ------------------------------------------------------------------ chamadas do site
    def aprovado_pelo_cliente(self, s, prof, orc, nome: str) -> list[Resposta]:
        """O cliente aprovou pelo link: avisa o profissional, já com o botão de registrar o sinal."""
        eventos.registrar(s, prof.id, "aprovado_link", orcamento_id=orc.id, revisao=orc.revisao)
        total = calculo.reais(orc.total_centavos)
        sinal = calculo.valor_sinal(orc.total_centavos, prof.sinal_percentual)
        if sinal < orc.total_centavos:
            msg = textos.APROVADO_LINK.format(nome=nome, numero=orc.numero, total=total,
                                              pix=f" Ele vai pagar o sinal de {calculo.reais(sinal)} pelo Pix.")
            botao = ("💰 Já recebi o sinal", f"/pago {orc.numero} {calculo.valor_curto(sinal)}")
        else:
            msg = textos.APROVADO_LINK.format(nome=nome, numero=orc.numero, total=total,
                                              pix=" Ele vai pagar pelo Pix.")
            botao = ("💰 Já recebi", f"/pago {orc.numero}")
        return [Resposta(msg, botoes=[[botao]])]

    def pedido_do_cliente(self, s, prof, orc, nome: str, texto: str) -> list[Resposta]:
        """O cliente pediu alteração pelo link. Se o profissional está livre, já abre a revisão; se está no meio de
        outro orçamento, só avisa (não pode atropelar o rascunho dele)."""
        eventos.registrar(s, prof.id, "alteracao_link", orcamento_id=orc.id)
        aviso = Resposta(f"💬 {nome} pediu uma alteração no orçamento Nº {orc.numero:04d}:\n\"{texto[:500]}\"")
        if prof.estado != "OCIOSO" or prof.rascunho:
            aviso.botoes = [[("✏️ Abrir o orçamento para mudar", f"/editar {orc.numero}")]]
            return [aviso]
        instrucao = f"[Mensagem ENCAMINHADA do cliente {nome}] {texto[:500]}"
        return [aviso] + self._iniciar_edicao(s, prof, orc, instrucao)

    def _mostrar_condicoes(self, prof) -> list[Resposta]:
        atuais = prof.condicoes_padrao or []
        texto = ("📌 Condições que vão em todo orçamento:\n" + "\n".join(f"• {c['rotulo']}: {c['texto']}" for c in atuais)
                 if atuais else "📌 Você ainda não tem condições padrão.")
        tem = {_norm(c["rotulo"]) for c in atuais}
        sugestoes = [(r, t) for r, t in catalogo.condicoes_da_profissao(prof.profissao) if _norm(r) not in tem]
        botoes = [[(f"+ {r}: {t}"[:60], f"/condicao {r}: {t}"[:64])] for r, t in sugestoes][:5]
        return [Resposta(texto + "\n\n" + textos.COMO_CONDICAO, botoes=botoes or None)]

    def _pasta_previas(self, prof) -> str:
        return os.path.join(self.pasta, "previas", str(prof.id))

    def _previas_modelos(self, prof) -> list[Resposta]:
        respostas = [Resposta("🎨 Escolha como seus orçamentos vão sair. Estes são exemplos com os seus dados:")]
        cor = prof.cor_pdf or pdf_mod.COR_PADRAO
        for chave, (nome, descricao) in pdf_mod.MODELOS.items():
            atual = " (o seu atual)" if chave == (prof.modelo_pdf or pdf_mod.MODELO_PADRAO) else ""
            png = pdf_mod.gerar_previa(prof, self._pasta_previas(prof), chave, cor)
            respostas.append(Resposta(f"{nome}{atual}: {descricao}", imagem=png,
                                      botoes=[[(f"Usar o {nome}", f"/modelo {chave}")]]))
        return respostas

    @staticmethod
    def _botoes_cores():
        cores = [(f"{nome}", f"/cor {chave}") for chave, (nome, _) in pdf_mod.CORES.items()]
        return [cores[i:i + 3] for i in range(0, len(cores), 3)]

    @staticmethod
    def _resumo(r) -> str:
        cli = r.get("cliente") or {}
        if r.get("editando_numero"):
            cabecalho = f"✏️ Revisão do orçamento Nº {r['editando_numero']:04d}"
        else:
            cabecalho = "📋 Confira o orçamento"
        para = "\n".join(filter(None, [f"👤 {cli['nome']}" if cli.get("nome") else None,
                                        f"📍 {cli['endereco']}" if cli.get("endereco") else None]))
        linhas = []
        blocos = calculo.subtotais_por_tipo(r)
        misto = len(blocos) > 1
        itens = sorted(r["itens"], key=lambda i: calculo.TIPOS.index(i.get("tipo") or "servico")) if misto else r["itens"]
        tipo_atual = None
        for i in itens:
            if misto and (i.get("tipo") or "servico") != tipo_atual:
                tipo_atual = i.get("tipo") or "servico"
                icone = "🔧" if tipo_atual == "servico" else "📦"
                linhas.append(("\n" if linhas else "") + f"{icone} {calculo.ROTULO_TIPO[tipo_atual]} "
                              f"({calculo.reais(blocos[tipo_atual])})")
            un = f" {i['unidade']}" if i.get("unidade") and i["unidade"] != "un" else ""
            ajustado = " ✏️" if i.get("origem") == "informado" else ""
            qtd = calculo.qtd_fmt(i["quantidade"])
            linhas.append(f"▪️ {i['descricao']}\n     {qtd}{un} × {calculo.reais(i['preco_centavos'])}{ajustado}"
                          f" = {calculo.reais(calculo.subtotal(i))}")
        valores = ""
        desconto = calculo.valor_desconto(r)
        if desconto:
            sinal = "-" if desconto > 0 else "+"
            valores = (f"\n\nSubtotal: {calculo.reais(calculo.subtotal_itens(r))}"
                       f"\n{calculo.rotulo_desconto(r)}: {sinal}{calculo.reais(abs(desconto))}")
        nota = "\n\n✏️ = preço só deste orçamento (sua tabela não muda)" if any(
            i.get("origem") == "informado" for i in r["itens"]) else ""
        obs = f"\n\n📝 {r['observacoes']}" if r.get("observacoes") else ""
        condicoes = r.get("condicoes") or []
        if condicoes:
            obs += "\n\n" + "\n".join(f"📌 {c['rotulo']}: {c['texto']}" for c in condicoes)
        topo = cabecalho + (f"\n{para}" if para else "")
        return (f"{topo}\n\n" + "\n".join(linhas) + valores +
                f"\n\n💰 Total: {calculo.reais(calculo.total(r))}{nota}{obs}"
                "\n\nEstá certo? Se não, me diga o que mudar (por áudio ou texto).")
