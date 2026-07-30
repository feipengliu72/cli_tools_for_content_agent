"""PDF text extraction and file conversion."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import fitz

# PyMuPDF span flag bit: bold (2**4). See span["flags"].
_FLAG_BOLD = 2**4

# A heading line is expected to be short and single-line.
_MAX_HEADING_CHARS = 64

# Treat sizes within this delta as the same logical size.
_SIZE_EPS = 0.6

# Above this many heading candidates on a single page, the page is treated as a
# borderless table / dense financial grid (which find_tables cannot detect) and
# all its candidates are demoted to plain text. Real documents stay well below
# this (the densest validated page is a 17-entry table of contents).
_MAX_HEADINGS_PER_PAGE = 20

# Drop C0 controls (except tab/LF/CR). PDFs often emit NUL / DLE for footnotes
# or math glyphs; editors then refuse to open the markdown as text.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# PyMuPDF table markdown uses <br>; papers also emit literal XML/HTML-like tags
# (<problem>, <section>, ...). Preview mode parses those as HTML and breaks.
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


class PdfParser:
    @staticmethod
    def _sanitize_text(text: str) -> str:
        text = _CTRL_RE.sub("", text)
        text = _BR_RE.sub(" / ", text)
        return text.replace("<", "&lt;").replace(">", "&gt;")

    def to_markdown(self, doc: "fitz.Document") -> str:
        """Convert an open PDF document to Markdown text."""
        lines, tables = self._collect_lines(doc)
        body_size = self._body_size(lines)
        size_to_level = self._build_size_levels(lines, body_size)
        dense_pages = self._dense_pages(lines, body_size, size_to_level)
        parts = self._render(lines, tables, body_size, size_to_level, dense_pages)
        return "\n\n".join(parts).strip() + "\n"

    # --- extraction -------------------------------------------------------

    def _collect_lines(self, doc: "fitz.Document") -> tuple[list[dict], list[dict]]:
        """Flatten the doc into line records, merging horizontally adjacent
        blocks (e.g. a section number "3" and its title "Model Architecture").

        Also detect tables: lines inside a table region are tagged so they are
        never promoted to headings, and each table is rendered as markdown and
        emitted in document order.

        Two-column pages are detected per-page; each line (and table) is
        tagged with a ``column`` field so that the merge and render stages
        can keep the two columns separate."""
        lines: list[dict] = []
        tables: list[dict] = []
        for page_no, page in enumerate(doc):
            page_width = page.rect.width
            try:
                found = page.find_tables().tables
            except Exception:
                found = []
            regions = [t.bbox for t in found]
            # Extract raw text lines *before* building table dicts so we can
            # use the text-line x-centers to detect the column layout.
            raw: list[dict] = []
            for block in page.get_text("dict")["blocks"]:
                if block.get("type") != 0:  # 0 = text block
                    continue
                for line in block["lines"]:
                    rec = self._line_record(line, page_width)
                    if rec is not None:
                        rec["page"] = page_no
                        rec["in_table"] = self._inside_any(rec, regions)
                        raw.append(rec)
            # --- column detection & assignment for this page ---
            is_two_col, sep_x = self._detect_page_columns(raw, page_width)
            for rec in raw:
                rec["column"] = self._assign_column(rec, is_two_col, sep_x, page_width)
            # --- graphic (image / vector-drawing) region detection ---
            graphic_regions = self._detect_graphic_regions(page)
            caption_regions = self._detect_caption_regions(raw, page_width)
            for rec in raw:
                rec["in_graphic"] = self._inside_graphic(rec, graphic_regions)
                rec["in_caption_region"] = self._inside_graphic(
                    rec, caption_regions)
            # Tables store column info as well so the render pass can order them.
            for order, t in enumerate(found):
                try:
                    md = t.to_markdown().strip()
                except Exception:
                    md = ""
                if md:
                    tx0, ty0, tx1, ty1 = t.bbox
                    tw = tx1 - tx0
                    if tw > page_width * 0.55:
                        tab_col = -1
                    elif not is_two_col:
                        tab_col = 0
                    else:
                        tab_col = 0 if ((tx0 + tx1) / 2) < sep_x else 1
                    tab_in_graphic = self._inside_bbox(
                        (tx0, ty0, tx1, ty1),
                        graphic_regions + caption_regions)
                    tables.append(
                        {"page": page_no, "y0": ty0, "x0": tx0,
                         "order": order, "markdown": self._sanitize_text(md),
                         "column": tab_col, "in_graphic": tab_in_graphic}
                    )
            # Merge same-row lines *within each column*.
            lines.extend(self._merge_same_row(raw))
        return lines, tables

    @staticmethod
    def _inside_any(rec: dict, regions: list[tuple]) -> bool:
        """True if the line's center sits within any table bounding box."""
        cx = (rec["x0"] + rec["x1"]) / 2
        cy = (rec["y0"] + rec["y1"]) / 2
        for x0, y0, x1, y1 in regions:
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                return True
        return False

    @staticmethod
    def _detect_page_columns(lines: list[dict], page_width: float) -> tuple[bool, float]:
        """Detect whether a page uses a two-column layout and return the
        x-separator that best splits left from right columns.

        Full-width lines (width > 55 % of page) are excluded from the
        analysis so that title / abstract blocks do not hide the bimodal
        distribution of x-centers.

        The separator is chosen by scanning all gaps between consecutive
        x-centers in the middle 60 % of the page and picking the one whose
        *balance-weighted* gap is largest — i.e. a gap that cleanly splits
        the centres into two similarly-sized groups is preferred over a
        slightly wider gap created by a handful of outliers."""
        centers: list[float] = []
        for rec in lines:
            w = rec["x1"] - rec["x0"]
            if w > page_width * 0.55:
                continue
            centers.append((rec["x0"] + rec["x1"]) / 2)

        if len(centers) < 10:
            return False, 0.0

        mid = page_width / 2
        left_cnt = sum(1 for c in centers if c < mid)
        right_cnt = sum(1 for c in centers if c > mid)
        total = len(centers)
        if left_cnt < total * 0.20 or right_cnt < total * 0.20:
            return False, 0.0

        # Scan gaps in the middle 60 % of the page, scoring each by
        #   score = gap × balance   where balance = min(L,R) / max(L,R)
        # so that a gap that cleanly bisects the data wins over one
        # caused by a handful of outliers.
        centers_sorted = sorted(centers)
        best_score = 0.0
        best_sep = mid
        lo = page_width * 0.2
        hi = page_width * 0.8
        for i in range(len(centers_sorted) - 1):
            c1, c2 = centers_sorted[i], centers_sorted[i + 1]
            gm = (c1 + c2) / 2
            if not (lo <= gm <= hi):
                continue
            gap = c2 - c1
            left_n = i + 1
            right_n = total - left_n
            balance = min(left_n, right_n) / max(left_n, right_n)
            score = gap * balance
            if score > best_score:
                best_score = score
                best_sep = gm

        if best_score < page_width * 0.01:
            return False, 0.0
        return True, best_sep

    @staticmethod
    def _assign_column(rec: dict, is_two_column: bool, sep_x: float, page_width: float) -> int:
        """Tag a line record with its column: -1 = full-width, 0 = left, 1 = right."""
        w = rec["x1"] - rec["x0"]
        if w > page_width * 0.55:
            return -1
        if not is_two_column:
            return 0
        return 0 if ((rec["x0"] + rec["x1"]) / 2) < sep_x else 1

    @staticmethod
    def _detect_graphic_regions(page: "fitz.Page", margin: float = 20.0,
                                merge_gap: float = 30.0) -> list[tuple]:
        """Return bounding boxes covering embedded-image regions.

        Only raster / embedded image blocks (``type == 1``) are used.
        Vector-graphic drawings are deliberately excluded because they
        cannot be reliably distinguished from table borders at scale:
        bordered-table pages often contain hundreds of cell-rectangle
        paths that would merge into a single page-spanning region and
        suppress all table text."""
        raw: list[tuple] = []

        # Raster / embedded image blocks ...............................
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") == 1:
                x0, y0, x1, y1 = block["bbox"]
                raw.append((x0 - margin, y0 - margin,
                            x1 + margin, y1 + margin))

        if not raw:
            return []

        # Merge nearby / overlapping regions ..............................
        raw.sort(key=lambda b: (b[1], b[0]))  # by y0 then x0
        merged: list[list] = [list(raw[0])]
        for b in raw[1:]:
            prev = merged[-1]
            if (b[0] <= prev[2] + merge_gap
                    and b[1] <= prev[3] + merge_gap
                    and prev[0] <= b[2] + merge_gap
                    and prev[1] <= b[3] + merge_gap):
                prev[0] = min(prev[0], b[0])
                prev[1] = min(prev[1], b[1])
                prev[2] = max(prev[2], b[2])
                prev[3] = max(prev[3], b[3])
            else:
                merged.append(list(b))
        return [tuple(m) for m in merged]

    @staticmethod
    def _inside_graphic(rec: dict, regions: list[tuple]) -> bool:
        """True if the line's centre sits inside any graphic region."""
        return PdfParser._inside_bbox(
            (rec["x0"], rec["y0"], rec["x1"], rec["y1"]), regions)

    @staticmethod
    def _inside_bbox(bbox: tuple, regions: list[tuple]) -> bool:
        """True if the bbox centre sits inside any of *regions*."""
        if not regions:
            return False
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        for x0, y0, x1, y1 in regions:
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                return True
        return False

    @staticmethod
    def _detect_caption_regions(raw_lines: list[dict],
                                page_width: float) -> list[tuple]:
        """Return regions anchored by ``Figure N:`` / ``Fig. N:`` captions.

        Each region extends 250 pt above the caption (full page width) so
        that short figure-internal labels are caught.  Text outside these
        regions, or long body-text paragraphs that happen to sit inside
        them, are *not* suppressed — the render pass applies an additional
        length check (``len(text) < 60``) before dropping a line."""
        import re
        cap_re = re.compile(r'^(Figure|Fig\.)\s*\d+[:.]')
        regions: list[tuple] = []
        for rec in raw_lines:
            if cap_re.match(rec["text"].strip()):
                cap_y = rec["y0"]
                regions.append((0.0, max(0.0, cap_y - 250.0),
                                page_width, cap_y - 5.0))
        return regions

    def _line_record(self, line: dict, page_width: float) -> dict | None:
        # Preserve spaces: PyMuPDF emits whitespace as its own spans, so build
        # the text from all spans and keep non-blank ones only for font stats.
        text = self._sanitize_text(
            "".join(s["text"] for s in line["spans"])
        ).strip()
        if not text:
            return None
        spans = [s for s in line["spans"] if s["text"].strip()]
        if not spans:
            return None
        # Dominant span = the one carrying the most characters.
        dominant = max(spans, key=lambda s: len(s["text"]))
        total_chars = sum(len(s["text"]) for s in spans)
        bold_chars = sum(len(s["text"]) for s in spans if s["flags"] & _FLAG_BOLD)
        x0, y0, x1, y1 = line["bbox"]
        return {
            "text": text,
            "size": round(dominant["size"], 1),
            "bold_ratio": bold_chars / total_chars if total_chars else 0.0,
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "dir": tuple(line.get("dir", (1.0, 0.0))),
            "page_width": page_width,
        }

    def _merge_same_row(self, recs: list[dict]) -> list[dict]:
        """Join records sharing a baseline (same y0, similar size) so a split
        "1" + "Introduction" becomes one heading candidate.

        Only merges records that belong to the *same* column so that
        two-column pages are kept cleanly separated."""
        recs = sorted(recs, key=lambda r: (round(r["y0"], 0), r["x0"]))
        merged: list[dict] = []
        for rec in recs:
            prev = merged[-1] if merged else None
            if (
                prev is not None
                and abs(prev["y0"] - rec["y0"]) < 3.0
                and abs(prev["size"] - rec["size"]) < _SIZE_EPS
                and prev["dir"] == rec["dir"]
                and prev.get("column", 0) == rec.get("column", 0)
                and prev.get("in_graphic", False) == rec.get("in_graphic", False)
                and prev.get("in_caption_region", False) == rec.get("in_caption_region", False)
                and rec["x0"] - prev["x1"] < 40.0
            ):
                prev["text"] = f"{prev['text']} {rec['text']}".strip()
                prev["x1"] = rec["x1"]
                prev["bold_ratio"] = max(prev["bold_ratio"], rec["bold_ratio"])
            else:
                merged.append(rec)
        return merged

    # --- size analysis ----------------------------------------------------

    def _body_size(self, lines: list[dict]) -> float:
        """Most common font size by character count = body text baseline."""
        hist: Counter[float] = Counter()
        for rec in lines:
            if rec.get("in_table"):
                continue
            hist[rec["size"]] += len(rec["text"])
        if not hist:
            return 0.0
        return hist.most_common(1)[0][0]

    def _build_size_levels(self, lines: list[dict], body_size: float) -> dict[float, int]:
        """Map each distinct above-body size to a heading level (largest = #).
        Marginal lines (watermarks) are excluded so they don't steal a level."""
        sizes = {
            rec["size"]
            for rec in lines
            if rec["size"] > body_size + _SIZE_EPS
            and not rec.get("in_table")
            and not self._is_marginal(rec)
            and self._is_heading_text(rec)
        }
        ordered = sorted(sizes, reverse=True)
        return {size: idx + 1 for idx, size in enumerate(ordered)}

    # --- classification ---------------------------------------------------

    def _is_marginal(self, rec: dict) -> bool:
        """Drop rotated / page-edge stamps (e.g. arXiv vertical watermark)."""
        if abs(rec["dir"][0]) < 0.99:  # not horizontal text
            return True
        if rec["x0"] < 15.0 and rec["x1"] < 60.0:  # hugging the left margin
            return True
        return False

    def _is_heading_text(self, rec: dict) -> bool:
        text = rec["text"]
        if not (0 < len(text) <= _MAX_HEADING_CHARS):
            return False
        # Reject multi-sentence prose (e.g. license notices share a heading size).
        if text.rstrip().endswith((".", ",", ";", ":")):
            return False
        if text.count(". ") >= 1:
            return False
        # Reject digit-dominated lines (table cells/numeric rows).
        letters = sum(c.isalpha() for c in text)
        digits = sum(c.isdigit() for c in text)
        if letters == 0 or digits > letters:
            return False
        return True

    def _heading_level(
        self, rec: dict, body_size: float, size_to_level: dict[float, int]
    ) -> int | None:
        if not self._is_heading_text(rec):
            return None
        # Larger-than-body font -> ranked heading level.
        if rec["size"] in size_to_level:
            return size_to_level[rec["size"]]
        # Body-size but bold -> deepest+1 subsection (e.g. "3.1 ...").
        if rec["bold_ratio"] >= 0.8 and abs(rec["size"] - body_size) <= _SIZE_EPS:
            return (max(size_to_level.values()) if size_to_level else 1) + 1
        return None

    def _dense_pages(
        self, lines: list[dict], body_size: float, size_to_level: dict[float, int]
    ) -> set[int]:
        """Pages whose heading-candidate count exceeds the table threshold.
        These are borderless financial grids that find_tables cannot see."""
        per_page: Counter[int] = Counter()
        for rec in lines:
            if rec.get("in_table"):
                continue
            if self._heading_level(rec, body_size, size_to_level):
                per_page[rec["page"]] += 1
        return {pg for pg, n in per_page.items() if n > _MAX_HEADINGS_PER_PAGE}

    # --- rendering --------------------------------------------------------

    def _render(
        self,
        lines: list[dict],
        tables: list[dict],
        body_size: float,
        size_to_level: dict[float, int],
        dense_pages: set[int],
    ) -> list[str]:
        # Merge text lines and table blocks into one stream ordered by page.
        #
        # For *two-column* pages we render full-width items first, then the
        # left column top-to-bottom, then the right column top-to-bottom so
        # that the reading flow within each column stays intact.
        #
        # A two-column page often has a *header* at the top (title, authors,
        # abstract) where the text isn't yet split into columns.  We detect
        # the header / body boundary by looking for the largest vertical gap
        # in the page's y-positions; everything above that gap keeps its
        # natural y-order while everything below uses column-major ordering.
        #
        # Build per-page metadata .......................................
        page_is_two_col: dict[int, bool] = {}
        page_body_start: dict[int, float] = {}
        for rec in lines:
            pg = rec["page"]
            page_is_two_col[pg] = page_is_two_col.get(pg, False) or rec.get("column", 0) == 1
        for pg, is_two_col in page_is_two_col.items():
            if not is_two_col:
                page_body_start[pg] = 0.0
                continue
            pg_lines = [r for r in lines if r["page"] == pg and r.get("column", -1) >= 0]
            y_vals = sorted(set(r["y0"] for r in pg_lines))
            body_start = 0.0
            best_gap = 0.0
            best_mid = 0.0
            for i in range(len(y_vals) - 1):
                gap = y_vals[i + 1] - y_vals[i]
                if gap > best_gap:
                    best_gap = gap
                    best_mid = (y_vals[i] + y_vals[i + 1]) / 2
            if best_gap > 40.0:
                body_start = best_mid
            page_body_start[pg] = body_start

        # Build sorted item stream .....................................
        items: list[tuple] = []
        for rec in lines:
            if rec.get("in_table") or self._is_marginal(rec):
                continue  # in-table text is replaced by the rendered table
            # Skip text inside graphic regions (figures / diagrams), but
            # keep captions so that "Figure N: …" lines are preserved.
            if rec.get("in_graphic"):
                txt = rec["text"]
                if not (txt.startswith(("Figure ", "Fig. ", "Table "))
                        and any(c.isdigit() for c in txt[:20])):
                    continue
            # Caption-anchored suppression: short fragments sitting above a
            # "Figure N:" caption are likely diagram labels.  Longer
            # paragraphs are body text and stay.  Additionally, even short
            # text that ends with sentence-ending punctuation (.!?。！？) is
            # treated as a body-text fragment — important for Chinese PDFs
            # where 60 chars can already be a substantial paragraph.
            if rec.get("in_caption_region") and len(rec["text"]) < 60:
                txt = rec["text"]
                if not (txt.startswith(("Figure ", "Fig. ", "Table "))
                        and any(c.isdigit() for c in txt[:20])):
                    stripped = txt.rstrip()
                    if stripped and stripped[-1] in ".!?。！？":
                        pass  # body-text fragment — keep it
                    else:
                        continue
            col = rec.get("column", 0)
            col_pri = 0 if col == -1 else (col + 1)  # full:0 left:1 right:2
            pg = rec["page"]
            # Header zone: force before body columns, ordered by y only.
            if (
                page_is_two_col.get(pg, False)
                and page_body_start.get(pg, 0.0) > 0
                and rec["y0"] < page_body_start[pg]
            ):
                items.append((pg, -1, rec["y0"], 0, rec))
            else:
                # In the body zone, full-width items (col == -1) are
                # treated as left-column for y-ordering so they interleave
                # with the left column at their natural vertical position
                # instead of being forced before *all* left-column lines.
                if col == -1:
                    col_pri = 1
                items.append((pg, col_pri, rec["y0"], 0, rec))
        for tab in tables:
            col = tab.get("column", -1)
            col_pri = 0 if col == -1 else (col + 1)
            pg = tab["page"]
            if (
                page_is_two_col.get(pg, False)
                and page_body_start.get(pg, 0.0) > 0
                and tab["y0"] < page_body_start[pg]
            ):
                items.append((pg, -1, tab["y0"], tab["order"], tab))
            else:
                if col == -1:
                    col_pri = 1
                items.append((pg, col_pri, tab["y0"], tab["order"], tab))
        items.sort(key=lambda it: (it[0], it[1], it[2], it[3]))

        parts: list[str] = []
        for *_unused, payload in items:
            if "markdown" in payload:  # a table block
                if not payload.get("in_graphic"):
                    parts.append(payload["markdown"])
                continue
            rec = payload
            if rec["page"] in dense_pages:
                level = None  # borderless-table page: keep everything as text
            else:
                level = self._heading_level(rec, body_size, size_to_level)
            if level:
                parts.append("#" * min(level, 6) + " " + rec["text"])
            else:
                text = rec["text"]
                if text.lstrip().startswith("#"):  # escape literal leading '#'
                    text = "\\" + text.lstrip()
                parts.append(text)
        return parts


class Pdf2mdError(Exception):
    """Domain error for pdf2md conversion failures."""


def extract_text_local(path: Path) -> str:
    """Extract Markdown text from a PDF (layout-aware via PyMuPDF only)."""
    path = Path(path)

    try:
        with path.open("rb") as f:
            header = f.read(4)
    except OSError as e:
        raise Pdf2mdError(f"读取文件头失败: {e}") from e

    if header != b"%PDF":
        raise Pdf2mdError(
            f"文件不是有效的 PDF 格式（缺少 PDF 文件头签名）: {path}"
        )

    try:
        with fitz.open(path) as doc:
            return PdfParser().to_markdown(doc)
    except Pdf2mdError:
        raise
    except Exception as e:  # noqa: BLE001 — surface PyMuPDF failures as domain errors
        raise Pdf2mdError(f"PDF 解析失败: {e}") from e


def extract_text(path: Path) -> str:
    """Extract Markdown from a PDF (local parse; callers needing OCR use fallback)."""
    return extract_text_local(path)


def convert(
    input_path: Path,
    output_path: Path,
    *,
    ocr: bool = True,
) -> dict:
    """Extract PDF text and write it to output_path. Returns a result dict.

    OCR-first strategy (MinerU via repo config.json): try OCR by default;
    fall back to local PyMuPDF parsing on OCR failure. Use ``ocr=False``
    for ``--no-ocr``.
    """
    from pdf2md.fallback import extract_text as extract_with_fallback

    input_path = Path(input_path)
    output_path = Path(output_path)

    text, meta = extract_with_fallback(
        input_path,
        ocr=ocr,
        output_dir=output_path.parent.resolve(),
    )

    try:
        if output_path.parent and str(output_path.parent) not in ("", "."):
            output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    except OSError as e:
        raise Pdf2mdError(f"写入输出文件失败: {e}") from e

    result = {
        "ok": True,
        "input": str(input_path),
        "output": str(output_path),
        "chars": len(text),
        "parser": meta.get("parser", "local"),
    }
    if meta.get("fallback_reason"):
        result["fallback_reason"] = meta["fallback_reason"]
    return result
