"""Gera notas fiscais SINTÉTICAS com gabarito: DANFE (NF-e, A4) e cupom de NFC-e.

Notas reais têm dados pessoais e fiscais; para medir um extrator é preciso saber a resposta
certa de cada campo. Por isso o conjunto é gerado: empresas e pessoas fictícias, mas CNPJ,
CPF e chave de acesso com dígitos verificadores válidos, valores que fecham e o leiaute dos
documentos reais. Cada nota sai em uma de três versões:

  - pdf:       PDF digital, com texto selecionável (o caso fácil)
  - foto_boa:  imagem bem enquadrada, com leve inclinação e compressão
  - foto_ruim: inclinada, em perspectiva, desfocada, com sombra e ruído (foto de celular)
"""

from __future__ import annotations

import io
import json
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from .documentos import completar_cnpj, completar_cpf, montar_chave
from .modelo import Item, Nota

VARIANTES = ("pdf", "foto_boa", "foto_ruim")

# ---------------------------------------------------------------- dados fictícios


@dataclass(frozen=True)
class Emitente:
    nome: str
    fantasia: str
    endereco: str
    cidade: str
    cnpj: str
    ie: str
    catalogo: tuple[tuple[str, str, float], ...]  # (descrição, unidade, preço base)


_CATALOGOS = {
    "mercado": (
        ("ARROZ BRANCO TIPO 1 5KG", "UN", 27.9), ("FEIJAO CARIOCA 1KG", "UN", 8.49),
        ("OLEO DE SOJA 900ML", "UN", 7.99), ("CAFE TORRADO MOIDO 500G", "UN", 24.9),
        ("LEITE INTEGRAL UHT 1L", "UN", 5.29), ("ACUCAR REFINADO 1KG", "UN", 4.99),
        ("BANANA PRATA", "KG", 6.98), ("TOMATE ITALIANO", "KG", 8.49),
        ("PAO FRANCES", "KG", 16.9), ("DETERGENTE LIQUIDO 500ML", "UN", 2.79),
        ("PAPEL HIGIENICO FOLHA DUPLA 12UN", "PCT", 21.9), ("MACARRAO ESPAGUETE 500G", "UN", 5.49),
    ),
    "farmacia": (
        ("DIPIRONA MONOIDRATADA 500MG 10CP", "CX", 8.9), ("PROTETOR SOLAR FPS50 200ML", "UN", 59.9),
        ("ESCOVA DENTAL MACIA", "UN", 12.5), ("CREME DENTAL 90G", "UN", 6.79),
        ("SABONETE LIQUIDO 250ML", "UN", 14.9), ("ALGODAO HIDROFILO 50G", "UN", 5.2),
        ("VITAMINA C 1G 10CP EFERV", "TB", 18.9),
    ),
    "posto": (
        ("GASOLINA COMUM", "L", 6.29), ("ETANOL HIDRATADO", "L", 4.19),
        ("OLEO DIESEL S10", "L", 6.09), ("ADITIVO RADIADOR 1L", "UN", 29.9),
        ("LAVAGEM SIMPLES", "UN", 40.0),
    ),
    "papelaria": (
        ("CADERNO UNIVERSITARIO 10M 200FLS", "UN", 32.9), ("CANETA ESFEROGRAFICA AZUL", "UN", 2.5),
        ("LAPIS PRETO N2", "UN", 1.6), ("PAPEL SULFITE A4 500FLS", "PCT", 29.9),
        ("MARCA TEXTO AMARELO", "UN", 4.9), ("PASTA CATALOGO 50 PLASTICOS", "UN", 22.0),
    ),
    "informatica": (
        ("MOUSE OPTICO USB", "UN", 49.9), ("TECLADO ABNT2 USB", "UN", 89.9),
        ("CABO HDMI 2.0 2M", "UN", 39.9), ("SSD SATA 480GB", "UN", 229.0),
        ("PEN DRIVE 64GB", "UN", 44.9), ("HEADSET COM MICROFONE", "UN", 149.0),
    ),
}

_EMITENTES = [
    ("SUPERMERCADO BOM PRECO LTDA", "SUPERMERCADO BOM PRECO", "AV. BRASIL, 1520 - CENTRO", "CAMPINAS - SP", "mercado"),
    ("FARMACIA VIDA SAUDAVEL LTDA", "DROGARIA VIDA SAUDAVEL", "R. XV DE NOVEMBRO, 311 - CENTRO", "SOROCABA - SP", "farmacia"),
    ("AUTO POSTO ESTRELA DO SUL LTDA", "POSTO ESTRELA DO SUL", "ROD. SP-340, KM 128", "MOGI MIRIM - SP", "posto"),
    ("PAPELARIA CADERNO AZUL ME", "CADERNO AZUL", "R. BARAO DE JAGUARA, 88 - CENTRO", "CAMPINAS - SP", "papelaria"),
    ("BITS E BYTES INFORMATICA LTDA", "BITS E BYTES", "AV. PAULISTA, 2073 - BELA VISTA", "SAO PAULO - SP", "informatica"),
    ("MERCADINHO SAO JORGE EIRELI", "MERCADINHO SAO JORGE", "R. DAS PALMEIRAS, 45 - VILA NOVA", "ITU - SP", "mercado"),
    ("COMERCIAL ANDRADE DE ALIMENTOS LTDA", "ANDRADE ATACADO", "AV. INDEPENDENCIA, 900", "SOROCABA - SP", "mercado"),
]

_DESTINATARIOS_PJ = ["ESCRITORIO CONTABIL SILVA E SOUZA LTDA", "OFICINA MECANICA TRES IRMAOS ME", "COLEGIO NOVO SABER LTDA"]
_DESTINATARIOS_PF = ["MARIANA COSTA RIBEIRO", "JOAO PEDRO ALMEIDA", "ANA LUIZA FERREIRA", "CARLOS EDUARDO NUNES"]


def _emitentes(rng: random.Random) -> list[Emitente]:
    saida = []
    for nome, fantasia, endereco, cidade, tipo in _EMITENTES:
        cnpj = completar_cnpj(f"{rng.randrange(10**8):08d}0001")
        ie = f"{rng.randrange(10**12):012d}"
        saida.append(Emitente(nome, fantasia, endereco, cidade, cnpj, ie, _CATALOGOS[tipo]))
    return saida


# ---------------------------------------------------------------- formatação brasileira


def moeda(valor: float) -> str:
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def quantidade(q: float, casas: int = 4) -> str:
    return f"{q:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_cnpj(c: str) -> str:
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def fmt_cpf(c: str) -> str:
    return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"


def fmt_chave(c: str) -> str:
    return " ".join(c[i : i + 4] for i in range(0, 44, 4))


# ---------------------------------------------------------------- conteúdo de uma nota


@dataclass
class NotaGerada:
    nota: Nota
    emitente: Emitente
    emissao: datetime
    destinatario_nome: str | None
    unidades: list[str]


def _sortear_nota(rng: random.Random, emitentes: list[Emitente], tipo: str, numero: int) -> NotaGerada:
    emit = rng.choice(emitentes)
    dia = date(2026, 1, 1) + timedelta(days=rng.randrange(0, 290))
    emissao = datetime.combine(dia, time(rng.randrange(7, 21), rng.randrange(60), rng.randrange(60)))
    serie = rng.choice([1, 1, 1, 2, 3])
    modelo = "55" if tipo == "NFE" else "65"
    chave = montar_chave("35", emissao.strftime("%y%m"), emit.cnpj, modelo, serie, numero, f"{rng.randrange(10**8):08d}")

    n_itens = rng.randint(2, 7) if tipo == "NFE" else rng.randint(1, 9)
    escolhidos = rng.sample(emit.catalogo, k=min(n_itens, len(emit.catalogo)))
    itens, unidades = [], []
    for descricao, unidade, preco in escolhidos:
        q = round(rng.uniform(5, 60), 3) if unidade == "L" else (
            round(rng.uniform(0.3, 3.0), 3) if unidade == "KG" else float(rng.randint(1, 6))
        )
        unit = round(preco * rng.uniform(0.92, 1.12), 2)
        itens.append(Item(descricao=descricao, quantidade=q, valor_unitario=unit, valor_total=round(q * unit, 2)))
        unidades.append(unidade)
    total = round(sum(i.valor_total for i in itens), 2)

    if tipo == "NFE":
        if rng.random() < 0.5:
            dest_doc, dest_nome = completar_cnpj(f"{rng.randrange(10**8):08d}0001"), rng.choice(_DESTINATARIOS_PJ)
        else:
            dest_doc, dest_nome = completar_cpf(f"{rng.randrange(10**9):09d}"), rng.choice(_DESTINATARIOS_PF)
    elif rng.random() < 0.45:  # na NFC-e o consumidor muitas vezes não se identifica
        dest_doc, dest_nome = completar_cpf(f"{rng.randrange(10**9):09d}"), None
    else:
        dest_doc, dest_nome = None, None

    nota = Nota(
        tipo=tipo, chave_acesso=chave, numero=numero, serie=serie, data_emissao=dia,
        emitente_nome=emit.nome, emitente_cnpj=emit.cnpj, destinatario_documento=dest_doc,
        valor_total=total, itens=itens,
    )
    return NotaGerada(nota, emit, emissao, dest_nome, unidades)


# ---------------------------------------------------------------- desenho: DANFE (NF-e)


def _caixa(c: Canvas, x, y, w, h, rotulo: str, valor: str = "", tam: float = 8.5, negrito: bool = False):
    c.setLineWidth(0.6)
    c.rect(x, y, w, h)
    c.setFont("Helvetica", 5.5)
    c.drawString(x + 2, y + h - 7, rotulo.upper())
    c.setFont("Helvetica-Bold" if negrito else "Helvetica", tam)
    c.drawString(x + 3, y + 4, valor)


def _desenhar_danfe(c: Canvas, g: NotaGerada) -> None:
    n, e = g.nota, g.emitente
    W, H = A4
    m = 22
    lw = W - 2 * m
    y = H - m

    # canhoto
    c.setLineWidth(0.6)
    c.rect(m, y - 30, lw, 30)
    c.setFont("Helvetica", 6)
    c.drawString(m + 3, y - 10, f"RECEBEMOS DE {e.nome} OS PRODUTOS CONSTANTES DA NOTA FISCAL INDICADA AO LADO")
    c.drawString(m + 3, y - 25, "DATA DE RECEBIMENTO            IDENTIFICACAO E ASSINATURA DO RECEBEDOR")
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(m + lw - 4, y - 18, f"NF-e  Nº {n.numero:09,d}".replace(",", ".") + f"  SÉRIE {n.serie:03d}")
    y -= 40

    # cabeçalho: emitente | DANFE | código de barras
    h = 92
    c.rect(m, y - h, 230, h)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(m + 6, y - 18, e.nome)
    c.setFont("Helvetica", 7.5)
    c.drawString(m + 6, y - 32, e.endereco)
    c.drawString(m + 6, y - 43, e.cidade)
    c.drawString(m + 6, y - 54, "FONE: (19) 3232-4400")

    c.rect(m + 230, y - h, 90, h)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(m + 275, y - 18, "DANFE")
    c.setFont("Helvetica", 6)
    c.drawCentredString(m + 275, y - 28, "DOCUMENTO AUXILIAR DA")
    c.drawCentredString(m + 275, y - 35, "NOTA FISCAL ELETRÔNICA")
    c.setFont("Helvetica", 7)
    c.drawString(m + 238, y - 48, "0 - ENTRADA")
    c.drawString(m + 238, y - 57, "1 - SAÍDA")
    c.rect(m + 295, y - 58, 14, 14)
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(m + 302, y - 54, "1")
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(m + 275, y - 72, "Nº " + f"{n.numero:09,d}".replace(",", "."))
    c.drawCentredString(m + 275, y - 82, f"SÉRIE {n.serie:03d}  FOLHA 1/1")

    bx = m + 320
    c.rect(bx, y - h, lw - 320, h)
    barras = code128.Code128(n.chave_acesso, barHeight=34, barWidth=0.72)
    barras.drawOn(c, bx + 6, y - 44)
    c.setFont("Helvetica", 5.5)
    c.drawString(bx + 4, y - 54, "CHAVE DE ACESSO")
    c.setFont("Helvetica-Bold", 7.6)
    c.drawString(bx + 4, y - 64, fmt_chave(n.chave_acesso))
    c.setFont("Helvetica", 6)
    c.drawString(bx + 4, y - 76, "Consulta de autenticidade no portal nacional da NF-e")
    c.drawString(bx + 4, y - 84, "www.nfe.fazenda.gov.br/portal ou no site da Sefaz Autorizadora")
    y -= h

    _caixa(c, m, y - 20, 330, 20, "Natureza da operação", "VENDA DE MERCADORIA ADQUIRIDA DE TERCEIROS")
    _caixa(c, m + 330, y - 20, lw - 330, 20, "Protocolo de autorização de uso",
           f"1352600{random.Random(n.chave_acesso).randrange(10**8):08d} {g.emissao:%d/%m/%Y %H:%M:%S}")
    y -= 20
    _caixa(c, m, y - 20, 180, 20, "Inscrição estadual", e.ie)
    _caixa(c, m + 180, y - 20, 180, 20, "Insc. estadual do subst. trib.", "")
    _caixa(c, m + 360, y - 20, lw - 360, 20, "CNPJ", fmt_cnpj(e.cnpj), negrito=True)
    y -= 28

    # destinatário
    c.setFont("Helvetica-Bold", 7)
    c.drawString(m, y, "DESTINATÁRIO / REMETENTE")
    y -= 3
    doc = n.destinatario_documento or ""
    doc_fmt = fmt_cnpj(doc) if len(doc) == 14 else fmt_cpf(doc)
    _caixa(c, m, y - 20, 340, 20, "Nome / razão social", g.destinatario_nome or "")
    _caixa(c, m + 340, y - 20, 120, 20, "CNPJ / CPF", doc_fmt)
    _caixa(c, m + 460, y - 20, lw - 460, 20, "Data da emissão", f"{n.data_emissao:%d/%m/%Y}", negrito=True)
    y -= 20
    _caixa(c, m, y - 20, 340, 20, "Endereço", "R. DAS ACACIAS, 210 - JARDIM PAULISTA")
    _caixa(c, m + 340, y - 20, 120, 20, "Município", "CAMPINAS")
    _caixa(c, m + 460, y - 20, lw - 460, 20, "Data da saída", f"{n.data_emissao:%d/%m/%Y}")
    y -= 28

    # cálculo do imposto
    c.setFont("Helvetica-Bold", 7)
    c.drawString(m, y, "CÁLCULO DO IMPOSTO")
    y -= 3
    total = n.valor_total or 0
    icms = round(total * 0.18, 2)
    largura = lw / 5
    for i, (rot, val) in enumerate([
        ("Base de cálculo do ICMS", moeda(total)), ("Valor do ICMS", moeda(icms)),
        ("Valor do frete", "0,00"), ("Valor total dos produtos", moeda(total)), ("Valor total da nota", moeda(total)),
    ]):
        _caixa(c, m + i * largura, y - 22, largura, 22, rot, val, tam=9, negrito=(i == 4))
    y -= 30

    # produtos
    c.setFont("Helvetica-Bold", 7)
    c.drawString(m, y, "DADOS DOS PRODUTOS / SERVIÇOS")
    y -= 3
    cols = [("CÓDIGO", 48), ("DESCRIÇÃO DO PRODUTO / SERVIÇO", 196), ("NCM", 44), ("CFOP", 32), ("UN", 24),
            ("QUANT.", 56), ("V. UNITÁRIO", 62), ("V. TOTAL", lw - 462)]
    x = m
    c.setFont("Helvetica-Bold", 5.8)
    for nome, w in cols:
        c.rect(x, y - 12, w, 12)
        c.drawString(x + 2, y - 9, nome)
        x += w
    y -= 12
    c.setFont("Helvetica", 7)
    for idx, (item, un) in enumerate(zip(n.itens, g.unidades, strict=True)):
        valores = [f"{1000 + idx * 37}", item.descricao or "", "21069090", "5102", un,
                   quantidade(item.quantidade or 0), moeda(item.valor_unitario or 0), moeda(item.valor_total or 0)]
        x = m
        for (_, w), v in zip(cols, valores, strict=True):
            c.rect(x, y - 13, w, 13)
            c.drawString(x + 2, y - 9.5, v) if v and not v[0].isdigit() else c.drawRightString(x + w - 2, y - 9.5, v)
            x += w
        y -= 13
    y -= 14

    c.setFont("Helvetica-Bold", 7)
    c.drawString(m, y, "DADOS ADICIONAIS")
    c.rect(m, y - 60, lw, 56)
    c.setFont("Helvetica", 6.5)
    c.drawString(m + 4, y - 14, "INFORMACOES COMPLEMENTARES: DOCUMENTO EMITIDO POR ME OU EPP OPTANTE PELO SIMPLES NACIONAL.")
    c.drawString(m + 4, y - 24, "NAO GERA DIREITO A CREDITO FISCAL DE IPI.")


# ---------------------------------------------------------------- desenho: cupom NFC-e


def _desenhar_nfce(c: Canvas, g: NotaGerada, altura: float) -> None:
    n, e = g.nota, g.emitente
    W = 226
    y = altura - 16

    def linha(texto: str, tam: float = 6.8, fonte: str = "Helvetica", centro: bool = False, dy: float = 9):
        nonlocal y
        c.setFont(fonte, tam)
        (c.drawCentredString(W / 2, y, texto) if centro else c.drawString(8, y, texto))
        y -= dy

    def tracos():
        nonlocal y
        c.setDash(1.5, 1.5)
        c.line(8, y + 4, W - 8, y + 4)
        c.setDash()
        y -= 6

    linha(e.nome, 7.4, "Helvetica-Bold", centro=True)
    linha(f"CNPJ: {fmt_cnpj(e.cnpj)}  IE: {e.ie}", centro=True)
    linha(e.endereco, centro=True)
    linha(e.cidade, centro=True)
    tracos()
    linha("Documento Auxiliar da Nota Fiscal de Consumidor Eletrônica", 6.2, centro=True)
    tracos()
    linha("#  CÓDIGO  DESCRIÇÃO   QTD  UN  VL UNIT  VL TOTAL", 5.8, "Helvetica-Bold")
    for i, (item, un) in enumerate(zip(n.itens, g.unidades, strict=True), start=1):
        linha(f"{i:03d} {7890000 + i * 1311}  {item.descricao}", 6.3, dy=8)
        c.setFont("Helvetica", 6.3)
        c.drawString(30, y, f"{quantidade(item.quantidade or 0, 3)} {un} X {moeda(item.valor_unitario or 0)}")
        c.drawRightString(W - 8, y, moeda(item.valor_total or 0))
        y -= 10
    tracos()
    c.setFont("Helvetica", 6.8)
    c.drawString(8, y, "Qtd. total de itens")
    c.drawRightString(W - 8, y, str(len(n.itens)))
    y -= 10
    c.setFont("Helvetica-Bold", 8.2)
    c.drawString(8, y, "VALOR A PAGAR R$")
    c.drawRightString(W - 8, y, moeda(n.valor_total or 0))
    y -= 11
    c.setFont("Helvetica", 6.8)
    c.drawString(8, y, "FORMA DE PAGAMENTO")
    c.drawRightString(W - 8, y, "VALOR PAGO")
    y -= 9
    c.drawString(8, y, random.Random(n.chave_acesso).choice(["Cartão de Débito", "PIX", "Dinheiro", "Cartão de Crédito"]))
    c.drawRightString(W - 8, y, moeda(n.valor_total or 0))
    y -= 8
    tracos()
    linha("Consulte pela Chave de Acesso em", 6.2, centro=True, dy=8)
    linha("www.fazenda.sp.gov.br/nfce/consulta", 6.2, centro=True)
    linha(fmt_chave(n.chave_acesso), 6.4, "Helvetica-Bold", centro=True, dy=11)
    if n.destinatario_documento:
        linha(f"CONSUMIDOR - CPF: {fmt_cpf(n.destinatario_documento)}", 6.6, centro=True)
    else:
        linha("CONSUMIDOR NÃO IDENTIFICADO", 6.6, centro=True)
    linha(f"NFC-e nº {n.numero:09d}  Série {n.serie:03d}  {g.emissao:%d/%m/%Y %H:%M:%S}", 6.6, "Helvetica-Bold", centro=True)
    linha("Protocolo de autorização: 1352600" + n.chave_acesso[-8:], 6.2, centro=True)
    codigo = qr.QrCodeWidget(f"https://www.fazenda.sp.gov.br/nfce/qrcode?p={n.chave_acesso}|2|1|1")
    lado = 96
    x0, y0, x1, y1 = codigo.getBounds()
    desenho = Drawing(lado, lado, transform=[lado / (x1 - x0), 0, 0, lado / (y1 - y0), 0, 0])
    desenho.add(codigo)
    renderPDF.draw(desenho, c, (W - lado) / 2, y - lado - 2)


def _pdf(g: NotaGerada) -> bytes:
    buf = io.BytesIO()
    if g.nota.tipo == "NFE":
        c = Canvas(buf, pagesize=A4)
        _desenhar_danfe(c, g)
    else:
        altura = 300 + 18 * len(g.nota.itens)
        c = Canvas(buf, pagesize=(226, altura))
        _desenhar_nfce(c, g, altura)
    c.setTitle(f"Nota {g.nota.numero}")
    c.showPage()
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------- "fotografar" o documento


def _fotografar(pdf: bytes, rng: random.Random, ruim: bool) -> bytes:
    pagina = pdfium.PdfDocument(pdf)[0]
    # o cupom é estreito: uma foto de celular dele tem mais pixels por milímetro que a de um A4
    estreito = pagina.get_width() < 300
    escala = (2.0 if ruim else 2.4) * (2.2 if estreito else 1.0)
    img = pagina.render(scale=escala).to_pil().convert("RGB")

    # papel levemente amarelado e fundo de mesa em volta
    papel = Image.new("RGB", img.size, (246, 243, 236) if ruim else (250, 249, 246))
    img = Image.composite(img, papel, img.convert("L").point(lambda v: 255 - v))
    margem = int(min(img.size) * (0.09 if ruim else 0.04))
    mesa = Image.new("RGB", (img.width + 2 * margem, img.height + 2 * margem),
                     rng.choice([(92, 74, 60), (60, 62, 68), (180, 170, 150)]))
    mesa.paste(img, (margem, margem))
    img = mesa

    angulo = rng.uniform(-5.5, 5.5) if ruim else rng.uniform(-1.6, 1.6)
    img = img.rotate(angulo, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=img.getpixel((2, 2)))

    if ruim:
        # perspectiva: a câmera não estava paralela ao papel
        w, h = img.size
        d = lambda: rng.uniform(0, 0.05)  # noqa: E731
        quad = (w * d(), h * d(), w * d(), h * (1 - d()), w * (1 - d()), h * (1 - d()), w * (1 - d()), h * d())
        img = img.transform((w, h), Image.Transform.QUAD, quad, resample=Image.Resampling.BICUBIC)
        # sombra de um lado (a mão, a luminária)
        sombra = Image.new("L", img.size, 0)
        desenho = ImageDraw.Draw(sombra)
        for i in range(img.width):
            desenho.line([(i, 0), (i, img.height)], fill=int(110 * max(0, 1 - i / (img.width * 0.55))))
        img = Image.composite(Image.new("RGB", img.size, (30, 30, 30)), img, sombra.point(lambda v: v // 2))
        # desfoque proporcional à resolução: o mesmo "fora de foco" em qualquer tamanho de imagem
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.55, 0.8) * escala))
        img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.75, 0.9))
        # ruído de sensor
        ruido = Image.effect_noise(img.size, rng.uniform(14, 24)).convert("RGB")
        img = Image.blend(img, ruido, 0.08)
    else:
        img = img.filter(ImageFilter.GaussianBlur(0.2 * escala))

    saida = io.BytesIO()
    img.save(saida, "JPEG", quality=55 if ruim else 85)
    return saida.getvalue()


# ---------------------------------------------------------------- conjunto


def gerar_conjunto(destino: Path, quantidade_notas: int = 60, semente: int = 2026) -> Path:
    """Gera as notas em `destino/documentos/` e o gabarito em `destino/gabarito.jsonl`."""
    rng = random.Random(semente)
    emitentes = _emitentes(rng)
    pasta = destino / "documentos"
    pasta.mkdir(parents=True, exist_ok=True)
    gabarito = destino / "gabarito.jsonl"

    with open(gabarito, "w", encoding="utf-8") as saida:
        for i in range(quantidade_notas):
            tipo = "NFE" if i % 2 == 0 else "NFCE"
            variante = VARIANTES[i % 3]
            g = _sortear_nota(rng, emitentes, tipo, numero=rng.randrange(1000, 999999))
            pdf = _pdf(g)
            ident = f"nota-{i + 1:03d}"
            if variante == "pdf":
                arquivo = f"{ident}.pdf"
                (pasta / arquivo).write_bytes(pdf)
            else:
                arquivo = f"{ident}.jpg"
                (pasta / arquivo).write_bytes(_fotografar(pdf, rng, ruim=variante == "foto_ruim"))
            registro = {"id": ident, "arquivo": arquivo, "variante": variante,
                        "nota": json.loads(g.nota.model_dump_json())}
            saida.write(json.dumps(registro, ensure_ascii=False) + "\n")
    return gabarito
