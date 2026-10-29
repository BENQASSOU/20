"""Text extraction from PDF, DOCX and TXT documents.

Everything here is pure Python so it runs unchanged inside the Android APK.
Pages are kept separate so citations can carry a page number.
"""

import os
import re
import zipfile
import xml.etree.ElementTree as ET

SUPPORTED_EXT = (".pdf", ".docx", ".txt", ".md")


class ExtractionError(Exception):
    pass


class ExtractedDoc:
    """Plain text of a document with page boundaries.

    `pages` is a list of page texts; `text` joins them with form feeds so
    character offsets can be mapped back to page numbers.
    """

    def __init__(self, pages, source_type, scanned=False):
        self.pages = pages
        self.source_type = source_type
        self.scanned = scanned
        self.text = "\f".join(pages)
        self._starts = []
        pos = 0
        for p in pages:
            self._starts.append(pos)
            pos += len(p) + 1

    def page_of(self, offset):
        page = 1
        for i, start in enumerate(self._starts):
            if offset >= start:
                page = i + 1
            else:
                break
        return page

    @property
    def char_count(self):
        return len(self.text)


def _clean(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("­", "")  # soft hyphen
    # re-join words hyphenated across line breaks: "pénali-\ntés"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("Module pypdf indisponible") from exc
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:
                raise ExtractionError("PDF protégé par mot de passe") from exc
        pages = []
        for page in reader.pages:
            try:
                pages.append(_clean(page.extract_text() or ""))
            except Exception:
                pages.append("")
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("PDF illisible : %s" % exc) from exc
    total = sum(len(p) for p in pages)
    # Fewer than ~80 characters per page means images only (scan).
    scanned = bool(pages) and total < 80 * len(pages)
    return ExtractedDoc(pages, "pdf", scanned=scanned)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_docx(path):
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ExtractionError("Fichier DOCX invalide") from exc
    root = ET.fromstring(xml)
    lines = []
    body = root.find(_W + "body")
    if body is None:
        return ExtractedDoc([""], "docx")
    for block in body.iter():
        if block.tag == _W + "p":
            parts = []
            for node in block.iter():
                if node.tag == _W + "t" and node.text:
                    parts.append(node.text)
                elif node.tag == _W + "tab":
                    parts.append("\t")
                elif node.tag in (_W + "br", _W + "cr"):
                    parts.append("\n")
            lines.append("".join(parts))
    # Word documents have no fixed pages; split on explicit page breaks.
    text = "\n".join(lines)
    pages = [_clean(p) for p in text.split("\f")] or [""]
    return ExtractedDoc(pages, "docx")


def extract_txt(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    pages = [_clean(p) for p in text.split("\f")]
    return ExtractedDoc(pages, "txt")


def extract(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return extract_pdf(path)
    if ext == ".docx":
        return extract_docx(path)
    if ext in (".txt", ".md"):
        return extract_txt(path)
    if ext == ".doc":
        raise ExtractionError(
            "Format .doc (Word 97) non supporté : enregistrez-le en .docx ou PDF")
    raise ExtractionError("Format non supporté : %s" % ext)


DOC_TYPES = {
    "CPS": "Cahier des Prescriptions Spéciales",
    "CCAG-T": "CCAG Travaux",
    "MARCHE": "Marché / contrat",
    "BPDE": "Bordereau des prix - détail estimatif",
    "RC": "Règlement de consultation",
    "AVENANT": "Avenant",
    "OS": "Ordre de service",
    "PV": "Procès-verbal",
    "DECOMPTE": "Décompte",
    "AUTRE": "Autre document",
}


def guess_doc_type(text, filename=""):
    head = (filename + "\n" + text[:6000]).lower()
    rules = [
        ("CCAG-T", ("cahier des clauses administratives générales", "ccag-t", "ccag travaux")),
        ("CPS", ("cahier des prescriptions spéciales", "c.p.s", "cps")),
        ("BPDE", ("bordereau des prix", "détail estimatif", "bpde")),
        ("RC", ("règlement de consultation",)),
        ("AVENANT", ("avenant n",)),
        ("OS", ("ordre de service",)),
        ("PV", ("procès-verbal", "proces-verbal", "proces verbal")),
        ("DECOMPTE", ("décompte provisoire", "décompte définitif", "decompte")),
        ("MARCHE", ("marché n", "acte d'engagement", "marche n")),
    ]
    for code, keys in rules:
        if any(k in head for k in keys):
            # The CCAG-T is often quoted inside a CPS; prefer CPS when the
            # title says so.
            if code == "CCAG-T" and "prescriptions spéciales" in head:
                return "CPS"
            return code
    return "AUTRE"
