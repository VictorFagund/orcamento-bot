"""Modelo de dados. Valores em dinheiro são guardados em CENTAVOS (inteiro) para evitar erro de arredondamento."""
import os
from datetime import date, datetime

from sqlalchemy import JSON, ForeignKey, String, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


class Base(DeclarativeBase):
    pass


class Profissional(Base):
    __tablename__ = "profissional"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Identificador no canal, ex: "telegram:12345" ou "whatsapp:5546999999999"
    canal_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    nome: Mapped[str | None] = mapped_column(String(120))
    profissao: Mapped[str | None] = mapped_column(String(80))
    telefone: Mapped[str | None] = mapped_column(String(40))
    pagamento_padrao: Mapped[str | None] = mapped_column(String(200))
    cidade: Mapped[str | None] = mapped_column(String(80))
    pix_chave: Mapped[str | None] = mapped_column(String(80))  # já normalizada (app/pix.py)
    ultimo_resumo: Mapped[date | None]  # dia do último resumo semanal enviado
    logo_path: Mapped[str | None] = mapped_column(String(300))
    modelo_pdf: Mapped[str | None] = mapped_column(String(20))  # visual do orçamento (app/pdf.py MODELOS)
    cor_pdf: Mapped[str | None] = mapped_column(String(20))
    # Em que ponto da conversa a pessoa está (cadastro, conferindo orçamento etc.)
    estado: Mapped[str] = mapped_column(String(40), default="CADASTRO_NOME")
    # Orçamento em montagem, antes de virar PDF
    rascunho: Mapped[dict | None] = mapped_column(JSON)
    criado_em: Mapped[datetime] = mapped_column(default=datetime.now)

    itens_preco: Mapped[list["ItemPreco"]] = relationship(back_populates="profissional", cascade="all, delete-orphan")


class ItemPreco(Base):
    """Tabela de preços do profissional. É a ÚNICA fonte de preço do sistema."""

    __tablename__ = "item_preco"

    id: Mapped[int] = mapped_column(primary_key=True)
    profissional_id: Mapped[int] = mapped_column(ForeignKey("profissional.id"), index=True)
    descricao: Mapped[str] = mapped_column(String(200))
    unidade: Mapped[str | None] = mapped_column(String(30))
    preco_centavos: Mapped[int]
    # Outras formas de falar o mesmo item: ["ponto de tomada", "trocar tomada"]
    sinonimos: Mapped[list] = mapped_column(JSON, default=list)
    # Serviço que se repete (ex: limpeza de ar a cada 6 meses): base para reativar clientes antigos
    recorrencia_meses: Mapped[int | None]
    recorrencia_texto: Mapped[str | None] = mapped_column(String(120))  # ex: "a limpeza do ar-condicionado"

    profissional: Mapped[Profissional] = relationship(back_populates="itens_preco")


class Cliente(Base):
    __tablename__ = "cliente"

    id: Mapped[int] = mapped_column(primary_key=True)
    profissional_id: Mapped[int] = mapped_column(ForeignKey("profissional.id"), index=True)
    nome: Mapped[str] = mapped_column(String(120))
    endereco: Mapped[str | None] = mapped_column(String(250))
    telefone: Mapped[str | None] = mapped_column(String(40))


class Orcamento(Base):
    __tablename__ = "orcamento"

    id: Mapped[int] = mapped_column(primary_key=True)
    profissional_id: Mapped[int] = mapped_column(ForeignKey("profissional.id"), index=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("cliente.id"))
    numero: Mapped[int]  # sequencial por profissional: 1, 2, 3...
    status: Mapped[str] = mapped_column(String(20), default="enviado")  # enviado | aprovado | recusado | pago
    total_centavos: Mapped[int]
    # Desconto aplicado sobre a soma dos itens (negativo = acréscimo). Percentual guardado só para exibir "10%".
    desconto_centavos: Mapped[int] = mapped_column(default=0)
    desconto_percentual: Mapped[float | None]
    revisao: Mapped[int] = mapped_column(default=1)  # sobe a cada alteração depois de enviado
    observacoes: Mapped[str | None] = mapped_column(String(1000))
    pagamento: Mapped[str | None] = mapped_column(String(200))
    validade: Mapped[date]
    pdf_path: Mapped[str | None] = mapped_column(String(300))
    criado_em: Mapped[datetime] = mapped_column(default=datetime.now)
    enviado_em: Mapped[datetime | None]  # última vez que foi gerado/revisado (base para os lembretes)
    lembretes: Mapped[int] = mapped_column(default=0)  # quantos lembretes de follow-up já foram dados
    aprovado_em: Mapped[datetime | None]
    cobrancas: Mapped[int] = mapped_column(default=0)  # quantos lembretes de cobrança já foram dados
    reativado_em: Mapped[datetime | None]  # quando o profissional foi lembrado de oferecer o serviço de novo

    cliente: Mapped[Cliente | None] = relationship()
    itens: Mapped[list["OrcamentoItem"]] = relationship(cascade="all, delete-orphan", order_by="OrcamentoItem.id")
    pagamentos: Mapped[list["Pagamento"]] = relationship(cascade="all, delete-orphan", order_by="Pagamento.id")

    @property
    def recebido_centavos(self) -> int:
        return sum(p.valor_centavos for p in self.pagamentos)

    @property
    def saldo_centavos(self) -> int:
        return max(self.total_centavos - self.recebido_centavos, 0)


class OrcamentoItem(Base):
    __tablename__ = "orcamento_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    orcamento_id: Mapped[int] = mapped_column(ForeignKey("orcamento.id"), index=True)
    item_preco_id: Mapped[int | None] = mapped_column(ForeignKey("item_preco.id"))
    descricao: Mapped[str] = mapped_column(String(200))
    quantidade: Mapped[float]
    unidade: Mapped[str | None] = mapped_column(String(30))
    preco_unit_centavos: Mapped[int]
    subtotal_centavos: Mapped[int]


class Pagamento(Base):
    """Cada recebimento registrado (permite pagamento parcial: entrada + restante)."""

    __tablename__ = "pagamento"

    id: Mapped[int] = mapped_column(primary_key=True)
    orcamento_id: Mapped[int] = mapped_column(ForeignKey("orcamento.id"), index=True)
    valor_centavos: Mapped[int]
    recebido_em: Mapped[datetime] = mapped_column(default=datetime.now)
    recibo_path: Mapped[str | None] = mapped_column(String(300))


class Link(Base):
    """Link secreto do site: orçamento para o cliente, editor do orçamento ou perfil do profissional."""

    __tablename__ = "link"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    tipo: Mapped[str] = mapped_column(String(10))  # cliente | editor | perfil
    profissional_id: Mapped[int] = mapped_column(ForeignKey("profissional.id"), index=True)
    orcamento_id: Mapped[int | None] = mapped_column(ForeignKey("orcamento.id"))
    expira_em: Mapped[datetime | None]  # None = não expira (link do cliente)
    criado_em: Mapped[datetime] = mapped_column(default=datetime.now)


def iniciar_banco(url: str):
    """Cria as tabelas (se não existirem) e devolve uma fábrica de sessões."""
    if url.startswith("sqlite:///"):
        pasta = os.path.dirname(url.replace("sqlite:///", ""))
        if pasta:
            os.makedirs(pasta, exist_ok=True)
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    _migrar(engine)
    return sessionmaker(engine, expire_on_commit=False)


# Colunas adicionadas depois da primeira versão: cria se o banco for antigo.
# (Quando o projeto crescer, troque isso pelo Alembic.)
_NOVAS_COLUNAS = {
    "profissional": {
        "cidade": "VARCHAR(80)",
        "pix_chave": "VARCHAR(80)",
        "ultimo_resumo": "DATE",
        "modelo_pdf": "VARCHAR(20)",
        "cor_pdf": "VARCHAR(20)",
    },
    "item_preco": {
        "recorrencia_meses": "INTEGER",
        "recorrencia_texto": "VARCHAR(120)",
    },
    "orcamento": {
        "enviado_em": "DATETIME",
        "lembretes": "INTEGER NOT NULL DEFAULT 0",
        "aprovado_em": "DATETIME",
        "cobrancas": "INTEGER NOT NULL DEFAULT 0",
        "reativado_em": "DATETIME",
        "desconto_centavos": "INTEGER NOT NULL DEFAULT 0",
        "desconto_percentual": "FLOAT",
        "revisao": "INTEGER NOT NULL DEFAULT 1",
    },
}


def _migrar(engine):
    insp = inspect(engine)
    with engine.begin() as con:
        for tabela, colunas in _NOVAS_COLUNAS.items():
            existentes = {c["name"] for c in insp.get_columns(tabela)}
            for nome, tipo in colunas.items():
                if nome not in existentes:
                    con.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}"))
