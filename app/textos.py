"""Textos fixos do bot, num lugar só (facilita ajustar o tom e, no futuro, traduzir)."""

AJUDA = """Como usar:

📝 Novo orçamento: mande um áudio ou texto descrevendo o serviço.
   Ex: "Orçamento pra Dona Maria, Rua das Flores 120. Trocar 6 tomadas e instalar 2 chuveiros."

✏️ Ajustar antes de gerar: "são 8 tomadas", "tira o chuveiro", "a fiação faço por 300",
   "dá 10% de desconto", "fecha em 700"

🤝 Cliente pediu mudança? Encaminhe aqui a mensagem ou o áudio dele (ou diga
   "no orçamento 3 o cliente quer pagar 600") e eu monto a revisão pra você conferir.

💲 Atualizar preços da tabela: "chuveiro agora é 130, ventilador de teto 90"

🖼️ Logo: mande uma foto da sua logo e ela vai para os PDFs.

⏰ Eu te aviso quando um orçamento ficar sem resposta ou um pagamento atrasar, com mensagem pronta pro cliente.

💰 Recebeu? "recebi 850 da Dona Maria" ou /pago N, e eu gero o recibo.

📊 Toda segunda de manhã te mando o resumo da semana.

🔁 Serviço que se repete (ex: limpeza de ar a cada 6 meses)? Eu te lembro de oferecer de novo.

Comandos:
/precos - ver sua tabela de preços
/remover N - remover o item N da tabela
/retorno N meses - item N da tabela se repete a cada X meses
/orcamentos - últimos orçamentos
/pdf N - reenviar o PDF do orçamento N
/editar N - alterar um orçamento já enviado
/aprovado N  ou  /recusado N - marcar resultado
/adiar N - adiar o lembrete do orçamento N
/pago N [valor] - registrar recebimento (gera recibo)
/recibo N - reenviar o último recibo
/areceber - o que falta receber
/cobrar N - mensagem de cobrança pronta (com Pix)
/resumo - resumo dos últimos 7 dias
/pix - ver ou trocar sua chave Pix
/perfil - ver e corrigir seus dados
/modelo - escolher o visual do PDF
/cor - escolher a cor do PDF
/cancelar - descartar o orçamento em andamento"""

BOAS_VINDAS = ("Olá! 👋 Eu faço orçamentos profissionais em PDF a partir de um áudio seu, com Pix pronto pro "
               "cliente pagar.\n\n"
               "Primeiro, um cadastro rápido. Pode responder tudo numa mensagem só, do seu jeito:\n\n"
               "• Seu nome ou nome da empresa\n"
               "• Profissão (ex: eletricista, mecânico)\n"
               "• Telefone de contato\n"
               "• Cidade onde atende\n"
               "• Forma de pagamento (ex: Pix ou cartão, 50% de entrada)\n"
               "• Chave Pix\n\n"
               "Se preferir ir por partes, me diga primeiro: qual o seu nome ou o nome da sua empresa? 🙂")

PERGUNTA_PROFISSAO = "Prazer, {nome}! Qual a sua profissão ou área? (ex: Eletricista, Pintor)"
PERGUNTA_TELEFONE = "Qual telefone de contato deve aparecer no orçamento? (ou responda PULAR)"
PERGUNTA_CIDADE = "Em qual cidade você atende? (vai no orçamento e no Pix)"
PERGUNTA_PAGAMENTO = ("Qual forma de pagamento você costuma oferecer? "
                      "(ex: \"Pix ou cartão, 50% de entrada\") ou responda PULAR")
PERGUNTA_PIX = ("Qual a sua chave Pix? Com ela, cada orçamento já sai com QR Code e Pix copia e cola "
                "no valor certo, e o dinheiro cai direto na sua conta (sem taxa).\n\n"
                "Pode ser celular, CPF, CNPJ, e-mail ou chave aleatória. (ou responda PULAR)")
PERGUNTA_LOGO = ("Tem logo da empresa? Mande uma foto dela e ela vai no topo de todos os orçamentos e recibos.\n\n"
                 "(ou responda PULAR; dá para mandar depois a qualquer hora)")
LOGO_ESPERANDO = "Mande a logo como foto (não como arquivo), ou responda PULAR."
PIX_INVALIDA = ("Não reconheci essa chave 🤔 Mande do jeito que está no seu banco, ex:\n"
                "celular (46) 99999-0000, CPF 000.000.000-00, e-mail ou chave aleatória. (ou PULAR)")
PIX_AMBIGUA = ("Esses 11 dígitos podem ser CPF ou celular. Pra não errar a conta, mande de novo assim:\n"
               "• CPF: 000.000.000-00\n• Celular: (46) 99999-0000")

TABELA_COM_CATALOGO = ("Agora seus preços. Estes são serviços comuns de {profissao}:\n\n{lista}\n\n"
                       "Mande quanto você cobra, por áudio ou texto, do seu jeito. Pode ser só os números na ordem "
                       "(\"40, 120, 60...\") ou \"tomada 40, chuveiro 120\". O que você não faz, é só não mencionar. "
                       "Também pode incluir outros serviços.\n\n(ou responda PULAR e eu pergunto os preços conforme "
                       "aparecerem nos orçamentos)")
TABELA_SEM_CATALOGO = ("Agora sua tabela de preços. Mande um áudio ou texto com o que você cobra, do jeito que "
                       "falaria pra alguém.\n\nEx: \"Troca de tomada 40, instalação de chuveiro 120, "
                       "ponto de luz 60, diária 250\"\n\nNão precisa ser completa: quando aparecer um serviço novo "
                       "num orçamento, eu pergunto o preço e guardo. (ou responda PULAR)")

LEMBRETE_PRESTADOR = ("⏰ O orçamento Nº {numero:04d} ({cliente}, {total}) está sem resposta há {dias} dias.\n\n"
                      "Encaminhe a mensagem abaixo para o cliente, ou use /aprovado {numero_curto}, "
                      "/recusado {numero_curto} ou /adiar {numero_curto}.")
LEMBRETE_CLIENTE_1 = ("Olá{saudacao}! Tudo bem? Passando para saber se você conseguiu ver o orçamento que enviei "
                      "(Nº {numero:04d}, {total}). Se quiser ajustar alguma coisa, é só me falar. "
                      "Fico à disposição!\n{assinatura}")
LEMBRETE_CLIENTE_2 = ("Olá{saudacao}! O orçamento Nº {numero:04d} ({total}) vale até {validade}. "
                      "Se fizer sentido pra você, já consigo reservar uma data na agenda. "
                      "Quer que eu marque?\n{assinatura}")

APROVADO = ("🎉 Boa! Orçamento Nº {numero:04d} aprovado.\nQuando receber, me avise: /pago {n} "
            "(ou /pago {n} 300 se for só uma parte) e eu gero o recibo. Se demorar, eu te lembro de cobrar.")

COBRANCA_PRESTADOR = ("💰 O serviço de {cliente} (Nº {numero:04d}) foi aprovado há {dias} dias e ainda falta receber "
                      "{saldo}.\n\nJá recebeu? Use /pago {n} (ou /pago {n} 300 se foi só uma parte).\n"
                      "Se precisar cobrar, encaminhe a mensagem abaixo:")
COBRANCA_CLIENTE = ("Olá{saudacao}! Tudo bem? Passando para lembrar do pagamento do serviço (orçamento Nº {numero:04d}), "
                    "no valor de {saldo}.{pix} Qualquer dúvida, estou à disposição. Obrigado!\n{assinatura}")

REATIVACAO_PRESTADOR = ("🔁 Faz {meses} meses que você fez \"{servico}\" para {cliente} (orçamento Nº {numero:04d}). "
                        "Boa hora pra oferecer {retorno}! Mensagem pronta pra encaminhar:")
REATIVACAO_CLIENTE = ("Olá{saudacao}! Tudo bem? Já faz {meses} meses do serviço que fiz pra você ({servico}). "
                      "Se quiser, já consigo agendar {retorno}. É só me responder!\n{assinatura}")

LINK_CLIENTE = ("Olá! Segue o orçamento Nº {numero:04d}. Por este link você vê tudo, aprova e paga pelo celular:\n"
                "{link}\n{assinatura}")
LINK_EDITOR = ("🌐 Abra para editar tudo no navegador (vale por 7 dias, não compartilhe):\n{link}\n\n"
               "Ao salvar, eu gero o PDF novo e mando aqui.")
APROVADO_LINK = "✅ {nome} aprovou o orçamento Nº {numero:04d} ({total}) pelo link!{pix}"

CADASTRO_PRONTO = ("✅ Cadastro pronto! Já pode mandar seu primeiro orçamento.\n\n"
                   "🎙️ Grave um áudio falando para quem é e o que vai fazer, por exemplo:\n"
                   "\"Orçamento pra Dona Maria, Rua das Flores 120. Trocar 6 tomadas e instalar 2 chuveiros.\"\n\n"
                   "Eu monto, você confere e eu gero o PDF.")

MENU = ("🎙️ Para fazer um orçamento, é só mandar um áudio (ou texto) dizendo para quem é e o que vai fazer.\n\n"
        "Depois eu te mostro o resumo para conferir, você corrige o que quiser e eu gero o PDF com Pix.\n\n"
        "O resto está nos botões abaixo 👇")

EXEMPLO = ("📝 Como pedir um orçamento\n\n"
           "Fale do jeito que você explicaria pra alguém. Exemplos:\n\n"
           "• \"Orçamento pro Seu Carlos, Gol 2015: troca de óleo, pastilha dianteira e alinhamento\"\n"
           "• \"Pra Dona Maria, Rua das Flores 120: 6 tomadas e 2 chuveiros, a fiação da cozinha eu faço por 300\"\n"
           "• \"Pintura de 2 quartos pro João, dá 10% de desconto\"\n\n"
           "💡 Dicas:\n"
           "• Preço dito no áudio vale só para aquele orçamento (sua tabela não muda).\n"
           "• Serviço que não está na tabela? Eu pergunto o preço e guardo.\n"
           "• Cliente pediu desconto? Encaminhe a mensagem dele aqui que eu ajusto.")

COMO_CORRIGIR = ("✏️ Me diga o que mudar, por áudio ou texto. Exemplos:\n\n"
                 "• \"são 8 tomadas\"\n• \"tira o chuveiro\"\n• \"a pastilha é 220\"\n"
                 "• \"dá 10% de desconto\" ou \"fecha em 700\"\n• \"o cliente é o João, Rua X 45\"")

COMO_MUDAR_PERFIL = ("Para corrigir, mande o comando com o valor certo:\n"
                     "/nome Elétrica Silva\n/profissao Eletricista\n/telefone (46) 99999-0000\n"
                     "/cidade Realeza - PR\n/pagamento Pix ou cartão, 50% de entrada\n/pix SUA_CHAVE\n"
                     "Para trocar a logo, é só mandar a foto nova.")
