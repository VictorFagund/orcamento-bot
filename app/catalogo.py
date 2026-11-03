"""Serviços comuns por profissão, oferecidos no cadastro. SEM PREÇOS: quem define o valor é sempre o profissional."""
import re
import unicodedata

# ofício: (palavras que identificam a profissão, [(descrição, unidade, sinônimos)])
CATALOGO = {
    # A ordem importa: vence o primeiro que casar.
    # Ar-condicionado primeiro: "mecânico de refrigeração" é técnico de ar, não de carro.
    "ar-condicionado": (["ar condic", "ar-condic", "refriger", "climatiz"], [
        ("Instalação de split até 12.000 BTUs", "un", ["instalar ar", "instalação de split", "ar de 9 mil", "ar de 12 mil"]),
        ("Instalação de split acima de 12.000 BTUs", "un", ["ar de 18 mil", "ar de 24 mil", "split grande"]),
        ("Limpeza / higienização", "un", ["limpeza", "higienização", "manutenção preventiva"]),
        ("Carga de gás", "un", ["gás", "recarga", "carga de gás"]),
        ("Desinstalação", "un", ["desinstalar", "tirar o ar"]),
        ("Tubulação adicional", "m", ["tubulação", "metro de tubo", "cobre"]),
        ("Visita técnica", "un", ["visita", "diagnóstico"]),
    ]),
    # Mecânico antes do eletricista: "eletricista automotivo" é de oficina, não de casa
    "mecanico": (["mecanic", "oficina", "automotiv", "auto center", "autocenter"], [
        ("Troca de óleo e filtro", "un", ["óleo", "trocar óleo", "filtro de óleo"]),
        ("Troca de pastilha de freio", "par", ["pastilha", "freio", "pastilha de freio"]),
        ("Troca de disco de freio", "par", ["disco", "disco de freio"]),
        ("Troca de amortecedor", "un", ["amortecedor", "suspensão"]),
        ("Troca de embreagem", "un", ["embreagem", "kit de embreagem"]),
        ("Troca de correia dentada", "un", ["correia", "correia dentada"]),
        ("Troca de bateria", "un", ["bateria"]),
        ("Alinhamento e balanceamento", "un", ["alinhamento", "balanceamento"]),
        ("Diagnóstico com scanner", "un", ["scanner", "diagnóstico", "luz da injeção", "injeção eletrônica"]),
        ("Revisão preventiva", "un", ["revisão", "revisão geral", "check-up"]),
        ("Mão de obra", "hora", ["mão de obra", "hora de serviço", "hora"]),
    ]),
    "eletricista": (["eletric", "eletrot"], [
        ("Troca de tomada ou interruptor", "un", ["tomada", "interruptor", "trocar tomada"]),
        ("Instalação de chuveiro", "un", ["chuveiro", "trocar chuveiro", "resistência do chuveiro"]),
        ("Ponto de luz", "un", ["ponto de luz", "instalar lâmpada", "luminária"]),
        ("Instalação de ventilador de teto", "un", ["ventilador", "ventilador de teto"]),
        ("Passagem de fiação", "m", ["fiação", "fio", "cabo", "puxar fio"]),
        ("Troca de disjuntor", "un", ["disjuntor"]),
        ("Montagem de quadro de distribuição", "un", ["quadro de luz", "quadro de distribuição", "quadro"]),
        ("Visita técnica", "un", ["visita", "diagnóstico", "orçamento no local"]),
        ("Diária", "diária", ["diária", "dia de trabalho"]),
    ]),
    "encanador": (["encanad", "hidraul", "bombeiro hidr"], [
        ("Troca de torneira", "un", ["torneira"]),
        ("Troca de sifão", "un", ["sifão"]),
        ("Desentupimento", "un", ["desentupir", "entupido", "desentupimento"]),
        ("Conserto de vazamento", "un", ["vazamento", "goteira no cano"]),
        ("Instalação de vaso sanitário", "un", ["vaso", "privada", "vaso sanitário"]),
        ("Troca de reparo de descarga", "un", ["descarga", "caixa acoplada", "reparo"]),
        ("Passagem de cano", "m", ["cano", "tubulação", "encanamento"]),
        ("Instalação de caixa d'água", "un", ["caixa d'água", "caixa de água"]),
        ("Visita técnica", "un", ["visita", "diagnóstico"]),
    ]),
    "pintor": (["pintor", "pintura"], [
        ("Pintura de parede", "m²", ["pintar parede", "pintura interna", "parede"]),
        ("Pintura de teto", "m²", ["teto", "pintar teto", "forro"]),
        ("Pintura externa / fachada", "m²", ["fachada", "muro", "pintura externa"]),
        ("Massa corrida", "m²", ["massa", "massa corrida", "emassar"]),
        ("Textura ou grafiato", "m²", ["textura", "grafiato"]),
        ("Pintura de porta", "un", ["porta"]),
        ("Pintura de grade ou portão", "un", ["grade", "portão"]),
        ("Diária", "diária", ["diária"]),
    ]),
    "pedreiro": (["pedreir", "construc", "alvenar", "obra"], [
        ("Assentamento de piso", "m²", ["piso", "assentar piso", "porcelanato"]),
        ("Assentamento de revestimento de parede", "m²", ["azulejo", "revestimento"]),
        ("Reboco", "m²", ["reboco", "rebocar"]),
        ("Contrapiso", "m²", ["contrapiso"]),
        ("Levantar parede (alvenaria)", "m²", ["parede", "alvenaria", "levantar parede", "tijolo"]),
        ("Rejunte", "m²", ["rejunte", "rejuntar"]),
        ("Demolição", "m²", ["demolir", "quebrar", "demolição"]),
        ("Diária", "diária", ["diária"]),
    ]),
    "marceneiro": (["marcen", "carpint", "moveis planej", "móveis planej"], [
        ("Armário sob medida", "m²", ["armário", "guarda-roupa", "roupeiro"]),
        ("Cozinha planejada", "m linear", ["cozinha", "armário de cozinha"]),
        ("Prateleira", "un", ["prateleira", "nicho"]),
        ("Conserto de porta ou gaveta", "un", ["dobradiça", "corrediça", "gaveta", "regular porta"]),
        ("Instalação de porta", "un", ["porta", "instalar porta"]),
        ("Montagem de móveis", "un", ["montar móvel", "montagem"]),
        ("Diária", "diária", ["diária"]),
    ]),
    "gesseiro": (["gess", "drywall"], [
        ("Forro de gesso", "m²", ["forro", "forro de gesso", "rebaixamento"]),
        ("Parede de drywall", "m²", ["drywall", "parede de gesso", "divisória"]),
        ("Sanca", "m", ["sanca", "moldura"]),
        ("Cortineiro", "m", ["cortineiro"]),
        ("Reparo em gesso", "un", ["reparo", "buraco no gesso", "trinca"]),
    ]),
    "montador": (["montad", "montagem de mov"], [
        ("Montagem de guarda-roupa", "un", ["guarda-roupa", "roupeiro"]),
        ("Montagem de cama ou cômoda", "un", ["cama", "cômoda", "criado-mudo"]),
        ("Montagem de rack ou painel", "un", ["rack", "painel de tv", "estante"]),
        ("Desmontagem", "un", ["desmontar", "desmontagem"]),
        ("Instalação de suporte de TV", "un", ["suporte de tv", "pendurar tv"]),
        ("Instalação de cortina ou varão", "un", ["cortina", "varão", "persiana"]),
    ]),
    "serralheiro": (["serralh", "solda"], [
        ("Portão de ferro", "m²", ["portão", "portão de ferro"]),
        ("Grade de janela", "m²", ["grade", "grade de janela"]),
        ("Corrimão", "m", ["corrimão"]),
        ("Motor de portão eletrônico", "un", ["motor do portão", "portão eletrônico", "automatizar portão"]),
        ("Solda / conserto", "un", ["solda", "soldar", "conserto"]),
        ("Pintura de portão ou grade", "un", ["pintar portão", "pintar grade"]),
    ]),
    "vidraceiro": (["vidrac", "vidro", "box de banh"], [
        ("Box de banheiro", "un", ["box", "box de banheiro"]),
        ("Troca de vidro", "m²", ["vidro", "trocar vidro", "vidro quebrado"]),
        ("Espelho", "m²", ["espelho"]),
        ("Janela de vidro temperado", "m²", ["janela", "temperado"]),
        ("Porta de vidro", "un", ["porta de vidro"]),
    ]),
    "jardineiro": (["jardin", "paisag", "rocad"], [
        ("Corte de grama", "m²", ["grama", "cortar grama", "roçada"]),
        ("Poda de árvore", "un", ["poda", "podar", "árvore"]),
        ("Manutenção de jardim", "visita", ["manutenção", "jardim"]),
        ("Plantio de grama", "m²", ["plantar grama", "plantio"]),
        ("Limpeza de terreno", "m²", ["limpeza de terreno", "terreno", "capina"]),
    ]),
    "diarista": (["diarist", "faxin", "limpeza resid", "domestic"], [
        ("Faxina completa", "un", ["faxina", "faxina completa"]),
        ("Limpeza pós-obra", "un", ["pós-obra", "limpeza de obra"]),
        ("Passar roupa", "hora", ["passar roupa", "roupa"]),
        ("Diária", "diária", ["diária"]),
    ]),
    "dedetizacao": (["dedetiz", "controle de prag", "pragas", "desinset"], [
        ("Dedetização", "un", ["dedetização", "dedetizar", "barata", "formiga"]),
        ("Descupinização", "un", ["cupim", "descupinização"]),
        ("Desratização", "un", ["rato", "desratização"]),
        ("Limpeza de caixa d'água", "un", ["caixa d'água", "limpar caixa"]),
    ]),
    "chaveiro": (["chaveir"], [
        ("Abertura de porta", "un", ["abrir porta", "abertura", "trancado"]),
        ("Cópia de chave", "un", ["cópia", "copiar chave"]),
        ("Troca de fechadura", "un", ["fechadura", "trocar fechadura"]),
        ("Troca de segredo", "un", ["segredo", "miolo"]),
        ("Chave de carro", "un", ["chave de carro", "chave codificada"]),
    ]),
}


def _norm(texto: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode())


def servicos_da_profissao(profissao: str | None) -> list[tuple[str, str, list[str]]]:
    p = _norm(profissao or "")
    for chaves, servicos in CATALOGO.values():
        if any(_norm(c) in p for c in chaves):
            return servicos
    return []


# Serviços que costumam se repetir: (meses até oferecer de novo, o que oferecer).
# Usado para lembrar o profissional de reativar clientes antigos. Ele pode mudar com /retorno.
RECORRENTES = {
    "Limpeza / higienização": (6, "a limpeza do ar-condicionado"),
    "Instalação de split até 12.000 BTUs": (6, "a limpeza do ar-condicionado"),
    "Instalação de split acima de 12.000 BTUs": (6, "a limpeza do ar-condicionado"),
    "Instalação de caixa d'água": (6, "a limpeza da caixa d'água"),
    "Montagem de quadro de distribuição": (12, "uma revisão da parte elétrica"),
    "Pintura externa / fachada": (36, "uma nova pintura da fachada"),
    "Troca de óleo e filtro": (6, "a troca de óleo"),
    "Revisão preventiva": (12, "a revisão do carro"),
    "Dedetização": (6, "uma nova dedetização"),
    "Limpeza de caixa d'água": (6, "a limpeza da caixa d'água"),
}


def recorrencia(descricao: str) -> tuple[int, str] | None:
    alvo = _norm(descricao or "")
    return next((v for d, v in RECORRENTES.items() if _norm(d) == alvo), None)
