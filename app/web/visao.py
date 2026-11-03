"""Monta os dados que as páginas mostram a partir do banco (o template só formata)."""
import base64
import io
from datetime import date

from .. import calculo, pdf, pix
from ..calculo import qtd_fmt, reais


def cores(prof) -> dict:
    rgb = pdf.CORES.get(prof.cor_pdf or pdf.COR_PADRAO, pdf.CORES[pdf.COR_PADRAO])[1]
    hexa = lambda c: "#%02x%02x%02x" % c
    return {"cor": hexa(rgb), "cor_clara": hexa(pdf._clara(rgb, .92)), "modelo": prof.modelo_pdf or pdf.MODELO_PADRAO}


def qr_data_uri(texto: str) -> str:
    import qrcode
    buf = io.BytesIO()
    qrcode.make(texto, box_size=6, border=2).save(buf)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def situacao(orc, hoje: date | None = None) -> str:
    """aberto | aprovado | recusado | pago | vencido"""
    hoje = hoje or date.today()
    if orc.status == "pago":
        return "pago"
    if orc.status == "recusado":
        return "recusado"
    if orc.status == "aprovado":
        return "aprovado"
    return "vencido" if orc.validade < hoje else "aberto"


def orcamento(prof, orc) -> dict:
    itens = [{"descricao": i.descricao, "tipo": i.tipo or "servico",
              "qtd": qtd_fmt(i.quantidade) + (f" {i.unidade}" if i.unidade and i.unidade != "un" else ""),
              "unit": reais(i.preco_unit_centavos), "subtotal": reais(i.subtotal_centavos)} for i in orc.itens]
    desconto = orc.desconto_centavos or 0
    sinal = calculo.valor_sinal(orc.total_centavos, prof.sinal_percentual)
    pix_codigo = (pix.gerar_copia_e_cola(prof.pix_chave, prof.nome or "", prof.cidade or "BRASIL", sinal,
                                         f"ORC{orc.numero:04d}") if prof.pix_chave and sinal > 0 else None)
    pct = 50 if prof.sinal_percentual is None else prof.sinal_percentual
    return {
        **cores(prof),
        "prof": prof, "numero": f"{orc.numero:04d}", "revisao": orc.revisao or 1,
        "data": f"{orc.criado_em:%d/%m/%Y}", "validade": f"{orc.validade:%d/%m/%Y}",
        "cliente": orc.cliente, "itens": itens,
        "grupos": [(rotulo, [i for i in itens if i["tipo"] == t],
                    reais(sum(x.subtotal_centavos for x in orc.itens if (x.tipo or "servico") == t)))
                   for t, rotulo in (("servico", "Mão de obra"), ("peca", "Peças e materiais"))
                   if any(i["tipo"] == t for i in itens)],
        "subtotal": reais(orc.total_centavos + desconto) if desconto else None,
        "desconto": reais(abs(desconto)) if desconto else None, "acrescimo": desconto < 0,
        "total": reais(orc.total_centavos), "pagamento": orc.pagamento, "observacoes": orc.observacoes,
        "condicoes": orc.condicoes or [],
        "situacao": situacao(orc),
        "sinal": reais(sinal), "sinal_pct": pct if 0 < pct < 100 else None,
        "pix_codigo": pix_codigo, "pix_qr": qr_data_uri(pix_codigo) if pix_codigo else None,
    }
