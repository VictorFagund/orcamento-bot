"""Pix "copia e cola" estático (BR Code), gerado localmente: sem banco, sem API, sem taxa.

Segue o padrão EMV QRCPS do Banco Central. O dinheiro cai direto na conta do profissional.
"""
import re
import unicodedata


def _campo(id_: str, valor: str) -> str:
    return f"{id_}{len(valor):02d}{valor}"


def _crc16(texto: str) -> str:
    """CRC16-CCITT (polinômio 0x1021, inicial 0xFFFF), exigido pelo BR Code."""
    crc = 0xFFFF
    for byte in texto.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def _ascii(texto: str, limite: int) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9 ]", "", sem_acento).strip()[:limite] or "NA"


def _cpf_valido(d: str) -> bool:
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10 % 11) % 10 != int(d[n]):
            return False
    return True


def normalizar_chave(chave: str) -> tuple[str, str] | None:
    """Devolve (chave no formato do Pix, tipo) ou None se não parecer uma chave válida.

    Se forem 11 dígitos sem formatação que podem ser tanto CPF quanto celular, devolve ("", "ambigua")
    para o bot perguntar, em vez de adivinhar (uma chave errada manda o dinheiro para o lugar errado).
    """
    bruto = (chave or "").strip()
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", bruto):
        return bruto.lower(), "e-mail"
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", bruto):
        return bruto.lower(), "chave aleatória"
    digitos = re.sub(r"\D", "", bruto)
    parece_telefone = bruto.startswith("+") or "(" in bruto or bool(re.fullmatch(r"\d{2}\s+\d{4,5}-?\d{4}", bruto))
    parece_cpf = bool(re.fullmatch(r"\d{3}\.\d{3}\.\d{3}-\d{2}", bruto))
    if len(digitos) == 14 and not parece_telefone:
        return digitos, "CNPJ"
    if len(digitos) == 11 and not parece_telefone and _cpf_valido(digitos):
        if parece_cpf or digitos[2] != "9":  # celular brasileiro: DDD + 9xxxx-xxxx
            return digitos, "CPF"
        return "", "ambigua"
    if len(digitos) in (10, 11) and not parece_cpf:  # DDD + número
        return f"+55{digitos}", "celular"
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        return f"+{digitos}", "celular"
    return None


def gerar_copia_e_cola(chave: str, nome: str, cidade: str, valor_centavos: int | None = None,
                       identificador: str = "***") -> str:
    """Monta o código Pix copia e cola. `chave` já normalizada (normalizar_chave)."""
    conta = _campo("00", "br.gov.bcb.pix") + _campo("01", chave)
    txid = re.sub(r"[^A-Za-z0-9]", "", identificador)[:25] or "***"
    payload = (
        _campo("00", "01")
        + _campo("26", conta)
        + _campo("52", "0000")
        + _campo("53", "986")  # Real
        + (_campo("54", f"{valor_centavos / 100:.2f}") if valor_centavos else "")
        + _campo("58", "BR")
        + _campo("59", _ascii(nome, 25))
        + _campo("60", _ascii(cidade, 15))
        + _campo("62", _campo("05", txid))
        + "6304"
    )
    return payload + _crc16(payload)


def gerar_qrcode(texto: str, caminho: str) -> str:
    import qrcode

    qrcode.make(texto, box_size=8, border=2).save(caminho)
    return caminho
