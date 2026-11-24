"""Document ingestion for PDF, EPUB, Markdown-bundle ZIP, Web URL, and Markdown/TXT (v2)."""

from __future__ import annotations

import io
import mimetypes
import posixpath
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from bs4 import BeautifulSoup, NavigableString, Tag
from ebooklib import ITEM_DOCUMENT, ITEM_IMAGE, epub

from ..db import VaultDB, slugify
from .vault import VaultFS

IMAGE_EXTS = {".png", ".gif", ".jpg", ".jpeg", ".svg", ".webp"}

FRONT_BACK_MATTER_PATTERNS = re.compile(
    r"^(?:"
    r"front\s*cover|back\s*cover|cover|half\s*title|halftitle|title\s*page|title|"
    r"copyright|dedication|contents|table\s+of\s+contents|toc|nav|navigation|"
    r"foreword|preface|acknowledg(?:e)?ments?|about\s+the\s+authors?|colophon|"
    r"index|bibliography|references|glossary|keep\s+up\s+to\s+date|front\s+matter|back\s+matter|"
    r"readme|sections|dropdown"
    r")$",
    re.IGNORECASE,
)

FRONT_BACK_FILE_PATTERNS = re.compile(
    r"(?:^|/)(?:cover|title|title-page|halftitle|copyright|ded\d*|dedication|"
    r"nav|toc|bk\d+-toc|contents|colophon|index|gloss|glossary|bm\d+|pref00|"
    r"keep-up-to-date.*|acknowledg.*|.*_images)\.(?:x?html?|xml)$",
    re.IGNORECASE,
)


def _is_front_or_back_matter(title: str, filename: str = "") -> bool:
    cleaned = re.sub(r"[^a-zA-Z0-9\s]+", " ", title).strip()
    if cleaned and FRONT_BACK_MATTER_PATTERNS.match(cleaned):
        return True
    if filename and FRONT_BACK_FILE_PATTERNS.search(filename):
        return True
    return False


def _normalize_text_ws(text: str) -> str:
    return (
        text.replace("\ufeff", "")
        .replace("\u00ad", "")
        .replace("\xa0", " ")
        .replace("\u2009", " ")
        .replace("\u200a", " ")
        .replace("\u200b", "")
    )


def _parse_yaml_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Parse simple YAML frontmatter without external PyYAML dependency."""
    m = re.match(r"^---\s*\n([\s\S]*?)\n---\s*\n?", text)
    if not m:
        return {}, text
    fm_raw = m.group(1)
    body = text[m.end() :]
    meta: Dict[str, Any] = {}
    authors_list: List[str] = []
    in_authors = False
    for raw_line in fm_raw.splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        if in_authors:
            if line.startswith(" ") or line.startswith("\t") or line.strip().startswith("-"):
                nm = re.search(r"name:\s*['\"]?([^'\"]+)['\"]?", line)
                if nm:
                    authors_list.append(nm.group(1).strip())
                elif re.match(r"^\s*-\s+([^:]+)$", line):
                    authors_list.append(re.sub(r"^\s*-\s+", "", line).strip().strip("'\""))
                continue
            else:
                in_authors = False
        kv = re.match(r"^([a-zA-Z0-9_-]+)\s*:\s*(.*)$", line)
        if kv:
            key = kv.group(1).strip()
            val = kv.group(2).strip()
            if key == "authors" and not val:
                in_authors = True
                continue
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            meta[key] = val.replace('\\"', '"')
    if authors_list:
        meta["authors_list"] = authors_list
    return meta, body


def _html_table_to_markdown(table: Tag) -> str:
    rows: List[List[str]] = []
    for tr in table.find_all("tr"):
        cells = [
            re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).replace("|", "\\|")
            for cell in tr.find_all(["th", "td"])
        ]
        if any(cells):
            rows.append(cells)
    if not rows:
        return ""
    col_count = max(len(r) for r in rows)
    norm_rows = [r + [""] * (col_count - len(r)) for r in rows]
    header = "| " + " | ".join(norm_rows[0]) + " |"
    sep = "| " + " | ".join("---" for _ in range(col_count)) + " |"
    body = ["| " + " | ".join(r) + " |" for r in norm_rows[1:]]
    return "\n".join([header, sep, *body])


def _inline_html_to_md(node: Any, resolve_img: Callable[[str], Optional[str]]) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    name = node.name.lower()
    if name in ("script", "style", "noscript"):
        return ""
    if name == "br":
        return "  \n"
    if name == "img":
        src = (node.get("src") or "").strip()
        alt = (node.get("alt") or "Figure").strip()
        resolved = resolve_img(src) if src else None
        if resolved:
            return f"\n\n![{alt}]({resolved})\n\n"
        return ""
    if name == "code":
        txt = node.get_text()
        if "`" in txt:
            return f"`` {txt} ``"
        return f"`{txt}`"
    if name in ("strong", "b"):
        inner = "".join(_inline_html_to_md(c, resolve_img) for c in node.children).strip()
        return f"**{inner}**" if inner else ""
    if name in ("em", "i"):
        inner = "".join(_inline_html_to_md(c, resolve_img) for c in node.children).strip()
        return f"*{inner}*" if inner else ""
    if name == "a":
        inner = "".join(_inline_html_to_md(c, resolve_img) for c in node.children).strip()
        href = (node.get("href") or "").strip()
        if href.startswith("http://") or href.startswith("https://"):
            return f"[{inner or href}]({href})"
        return inner
    if name == "sup":
        inner = "".join(_inline_html_to_md(c, resolve_img) for c in node.children).strip()
        return f"^{inner}" if inner else ""
    return "".join(_inline_html_to_md(c, resolve_img) for c in node.children)


def _html_node_to_markdown(root: Tag, resolve_img: Callable[[str], Optional[str]]) -> str:
    """Convert an XHTML/HTML tree into clean Markdown preserving headings, pre/code, tables, lists, and images."""
    blocks: List[str] = []

    def walk(el: Any) -> None:
        if isinstance(el, NavigableString):
            txt = str(el).strip()
            if txt:
                blocks.append(txt)
            return
        if not isinstance(el, Tag):
            return
        name = el.name.lower()
        if name in ("script", "style", "noscript", "head", "nav", "footer", "svg"):
            return

        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            lvl = min(4, int(name[1]))
            txt = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
            if txt:
                blocks.append(f"{'#' * lvl} {txt}")
            return

        if name == "pre":
            code_tag = el.find("code")
            lang = ""
            if code_tag:
                for cls in (code_tag.get("class") or []):
                    m = re.match(r"(?:language|lang)-([a-zA-Z0-9_+-]+)", str(cls))
                    if m:
                        lang = m.group(1)
                        break
                raw_code = code_tag.get_text()
            else:
                raw_code = el.get_text()
            raw_code = raw_code.strip("\n")
            if raw_code.strip():
                blocks.append(f"```{lang}\n{raw_code}\n```")
            return

        if name == "table":
            md_tbl = _html_table_to_markdown(el)
            if md_tbl:
                blocks.append(md_tbl)
            return

        if name == "figure":
            cap_tag = el.find("figcaption")
            cap = re.sub(r"\s+", " ", cap_tag.get_text(" ", strip=True)) if cap_tag else ""
            tables = el.find_all("table")
            pres = el.find_all("pre")
            imgs = el.find_all("img")
            if cap and (tables or pres) and not imgs:
                blocks.append(f"*{cap}*")
            for tbl in tables:
                md_tbl = _html_table_to_markdown(tbl)
                if md_tbl:
                    blocks.append(md_tbl)
            for pr in pres:
                walk(pr)
            for im in imgs:
                src = (im.get("src") or "").strip()
                alt = (im.get("alt") or cap or "Figure").strip()
                resolved = resolve_img(src) if src else None
                if resolved:
                    blocks.append(f"![{alt}]({resolved})")
            if cap and imgs:
                blocks.append(f"*{cap}*")
            return

        if name == "img":
            src = (el.get("src") or "").strip()
            alt = (el.get("alt") or "Figure").strip()
            resolved = resolve_img(src) if src else None
            if resolved:
                blocks.append(f"![{alt}]({resolved})")
            return

        if name in ("ul", "ol"):
            lines: List[str] = []
            for i, li in enumerate(el.find_all("li", recursive=False), start=1):
                prefix = f"{i}. " if name == "ol" else "- "
                li_txt = re.sub(r"[ \t]+", " ", "".join(_inline_html_to_md(c, resolve_img) for c in li.children)).strip()
                if li_txt:
                    lines.append(f"{prefix}{li_txt}")
            if lines:
                blocks.append("\n".join(lines))
            return

        if name == "blockquote":
            sub_parts: List[str] = []
            for child in el.children:
                if isinstance(child, Tag) and child.name.lower() in ("p", "div"):
                    t = re.sub(r"[ \t]+", " ", "".join(_inline_html_to_md(c, resolve_img) for c in child.children)).strip()
                    if t:
                        sub_parts.append(f"> {t}")
                else:
                    t = re.sub(r"[ \t]+", " ", _inline_html_to_md(child, resolve_img)).strip()
                    if t:
                        sub_parts.append(f"> {t}")
            if sub_parts:
                blocks.append("\n>\n".join(sub_parts))
            return

        if name == "p":
            txt = "".join(_inline_html_to_md(c, resolve_img) for c in el.children)
            txt = re.sub(r"[ \t]+", " ", txt).strip()
            if txt:
                blocks.append(txt)
            return

        # Container tags: div, section, article, body, main, span, etc.
        has_block_children = any(
            isinstance(c, Tag)
            and c.name.lower()
            in ("div", "section", "article", "p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "table", "ul", "ol", "blockquote", "figure")
            for c in el.children
        )
        if has_block_children:
            for child in el.children:
                walk(child)
        else:
            txt = "".join(_inline_html_to_md(c, resolve_img) for c in el.children)
            txt = re.sub(r"[ \t]+", " ", txt).strip()
            if txt:
                blocks.append(txt)

    walk(root)
    # Collapse excessive blank lines
    out = "\n\n".join(b.strip() for b in blocks if b and b.strip())
    return re.sub(r"\n{3,}", "\n\n", out).strip() + "\n"


class IngestionService:
    """Parses uploaded/local/web books into chapter boundaries and slices per-chapter sources."""

    def __init__(self, db: VaultDB, fs: VaultFS):
        self.db = db
        self.fs = fs

    def ingest_upload(
        self,
        filename: str,
        content: bytes,
        title_override: str = "",
        authors_override: str = "",
        topic_areas: List[str] | None = None,
        workspace_id: Optional[str] = None,
        toc_level: Optional[int] = None,
        single_unit: bool = False,
        detect_printed_toc: bool = False,
    ) -> Dict[str, Any]:
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext not in ("pdf", "epub", "zip", "md", "markdown", "txt"):
            raise ValueError(
                f"Unsupported format '.{ext}'. Supported formats are PDF, EPUB, Markdown-bundle ZIP, Markdown, and TXT."
            )
        norm_fmt = "md" if ext == "markdown" else ext
        inferred_title = title_override.strip() or Path(filename).stem.replace("_", " ").replace("-", " ").title()
        authors = authors_override.strip() or "Unknown Author"
        topics = topic_areas or ["General Study"]

        if norm_fmt == "pdf":
            return self._ingest_pdf(
                filename,
                content,
                inferred_title,
                authors,
                topics,
                workspace_id=workspace_id,
                toc_level=toc_level,
                single_unit=single_unit,
                detect_printed_toc=detect_printed_toc,
                explicit_title=bool(title_override.strip()),
                explicit_authors=bool(authors_override.strip()),
            )
        if norm_fmt == "epub":
            return self._ingest_epub(
                filename,
                content,
                inferred_title,
                authors,
                topics,
                workspace_id=workspace_id,
                explicit_title=bool(title_override.strip()),
                explicit_authors=bool(authors_override.strip()),
            )
        if norm_fmt == "zip":
            return self._ingest_markdown_zip(
                filename,
                content,
                inferred_title,
                authors,
                topics,
                workspace_id=workspace_id,
                explicit_title=bool(title_override.strip()),
                explicit_authors=bool(authors_override.strip()),
            )
        return self._ingest_markdown_or_txt(
            filename, content, norm_fmt, inferred_title, authors, topics, workspace_id=workspace_id
        )

    def ingest_local(
        self,
        local_path: str,
        workspace_id: Optional[str] = None,
        title_override: str = "",
        authors_override: str = "",
        topic_areas: List[str] | None = None,
        toc_level: Optional[int] = None,
        single_unit: bool = False,
        detect_printed_toc: bool = False,
        assigned_filter: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        p = Path(local_path).expanduser().resolve()
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(f"Local file not found: {p}")
        content = p.read_bytes()
        book = self.ingest_upload(
            filename=p.name,
            content=content,
            title_override=title_override,
            authors_override=authors_override,
            topic_areas=topic_areas,
            workspace_id=workspace_id,
            toc_level=toc_level,
            single_unit=single_unit,
            detect_printed_toc=detect_printed_toc,
        )
        if assigned_filter is not None:
            patterns = [pat.lower() for pat in assigned_filter]
            scopes: Dict[str, str] = {}
            for ch in book["chapters"]:
                t_low = ch["title"].lower()
                if any(pat in t_low for pat in patterns):
                    scopes[ch["id"]] = "assigned"
                else:
                    scopes[ch["id"]] = "skipped"
            self.db.bulk_update_chapter_scopes(book["id"], scopes)
            self._sync_book_meta(book["id"])
            book = self.db.get_book(book["id"])  # type: ignore[assignment]
        return book

    # ---------- Web URL Importer ----------

    def ingest_url(
        self,
        url: str,
        workspace_id: Optional[str] = None,
        title_override: str = "",
        authors_override: str = "",
        topic_areas: List[str] | None = None,
    ) -> Dict[str, Any]:
        parsed = urllib.parse.urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("URL must begin with http:// or https://.")

        req = urllib.request.Request(
            url.strip(),
            headers={"User-Agent": "Scholia/2.0 (Local Study Studio)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw_html = resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ValueError(f"Unable to fetch URL '{url}': {exc}") from exc

        soup = BeautifulSoup(raw_html, "html.parser")
        title = title_override.strip()
        if not title:
            h1 = soup.find("h1")
            t_tag = soup.find("title")
            title = (h1.get_text(" ", strip=True) if h1 else "") or (t_tag.get_text(" ", strip=True) if t_tag else "") or parsed.netloc
        authors = authors_override.strip()
        if not authors:
            m_auth = soup.find("meta", attrs={"name": re.compile("^author$", re.I)})
            authors = (m_auth.get("content") or "").strip() if m_auth else parsed.netloc
        topics = topic_areas or ["Web Article"]

        book = self.db.create_book(
            title=title[:140],
            authors=authors[:120],
            source_format="web",
            source_filename=f"{slugify(title)}.html",
            source_url=url.strip(),
            page_count=1,
            topic_areas=topics,
            workspace_id=workspace_id,
        )
        ws_slug = book.get("workspace_slug")
        assets_dir = self.fs.book_assets_dir(book["slug"], ws_slug)
        src_path = self.fs.book_source_path(book["slug"], "html", ws_slug)
        src_path.write_text(raw_html, encoding="utf-8")

        downloaded_map: Dict[str, str] = {}

        def resolve_web_img(img_src: str) -> Optional[str]:
            if not img_src or img_src.startswith("data:"):
                return None
            abs_url = urllib.parse.urljoin(url.strip(), img_src)
            if abs_url in downloaded_map:
                return downloaded_map[abs_url]
            try:
                ireq = urllib.request.Request(abs_url, headers={"User-Agent": "Scholia/2.0"})
                with urllib.request.urlopen(ireq, timeout=10) as ir:
                    data = ir.read()
                ext = Path(urllib.parse.urlparse(abs_url).path).suffix.lower()
                if ext not in IMAGE_EXTS:
                    ctype = (ir.headers.get("Content-Type") or "").split(";")[0].strip()
                    ext = mimetypes.guess_extension(ctype) or ".png"
                fname = f"web-img-{len(downloaded_map) + 1:03d}{ext}"
                (assets_dir / fname).write_bytes(data)
                api_url = f"/api/books/{book['id']}/assets/{fname}"
                downloaded_map[abs_url] = api_url
                return api_url
            except Exception:
                return abs_url

        main_node = soup.find("article") or soup.find("main") or soup.body or soup
        md_body = _html_node_to_markdown(main_node, resolve_web_img)
        if not md_body.lstrip().startswith("# "):
            md_body = f"# {title}\n\n*Source: {url.strip()}*\n\n{md_body}"

        rec = self.db.create_chapter(
            book_id=book["id"],
            order_index=1,
            title=title[:120],
            start_page=1,
            end_page=1,
            has_pdf=False,
            status="pending",
            scope="assigned",
        )
        self.fs.chapter_source_md(book["slug"], rec["slug"], ws_slug).write_text(md_body, encoding="utf-8")
        self._sync_book_meta(book["id"], asset_count=len(downloaded_map))
        return self.db.get_book(book["id"])  # type: ignore[return-value]

    # ---------- Markdown-Bundle ZIP Importer (Jekyll / Distill) ----------

    def _ingest_markdown_zip(
        self,
        filename: str,
        content: bytes,
        title: str,
        authors: str,
        topics: List[str],
        workspace_id: Optional[str] = None,
        explicit_title: bool = False,
        explicit_authors: bool = False,
    ) -> Dict[str, Any]:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/") and "__MACOSX" not in n]
            if not names:
                raise ValueError("ZIP archive is empty.")

            # Detect common top-level directory prefix (e.g. "scaling-book/")
            top_parts = {n.split("/")[0] for n in names if "/" in n}
            prefix = f"{next(iter(top_parts))}/" if len(top_parts) == 1 else ""

            def strip_prefix(path_str: str) -> str:
                return path_str[len(prefix) :] if prefix and path_str.startswith(prefix) else path_str

            # Collect markdown files at top-level or chapter folders (ignore _includes, _layouts, _site)
            md_entries: List[Tuple[str, str, Dict[str, Any], str]] = []
            for n in sorted(names):
                rel = strip_prefix(n)
                if not rel.lower().endswith(".md"):
                    continue
                parts = rel.split("/")
                if any(p.startswith("_") or p.startswith(".") for p in parts):
                    continue
                raw_text = zf.read(n).decode("utf-8", errors="replace")
                fm, body = _parse_yaml_frontmatter(raw_text)
                md_entries.append((n, rel, fm, body))

            if not md_entries:
                raise ValueError("No Markdown (.md) chapters found inside ZIP archive.")

            # Infer book title/authors from index.md or section_number=0 if not explicitly overridden
            inferred_title = title
            inferred_authors = authors
            for _n, rel, fm, _body in md_entries:
                if rel.lower() == "index.md" or str(fm.get("section_number", "")).strip() == "0":
                    if not explicit_title and fm.get("title"):
                        inferred_title = str(fm["title"]).strip()
                    if not explicit_authors and fm.get("authors_list"):
                        inferred_authors = ", ".join(fm["authors_list"][:6])
                    break

            book = self.db.create_book(
                title=inferred_title,
                authors=inferred_authors,
                source_format="zip",
                source_filename=filename,
                page_count=len(md_entries),
                topic_areas=topics,
                workspace_id=workspace_id,
            )
            ws_slug = book.get("workspace_slug")
            self.fs.book_source_path(book["slug"], "zip", ws_slug).write_bytes(content)
            assets_dir = self.fs.book_assets_dir(book["slug"], ws_slug)

            # Extract all image assets into books/<slug>/assets/
            asset_lookup: Dict[str, str] = {}
            asset_count = 0
            for n in names:
                ext = Path(n).suffix.lower()
                if ext not in IMAGE_EXTS:
                    continue
                rel = strip_prefix(n).lstrip("/")
                # Avoid double "assets/assets/"
                rel_under_assets = rel[len("assets/") :] if rel.startswith("assets/") else rel
                target = assets_dir / rel_under_assets
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(n))
                asset_count += 1
                api_url = f"/api/books/{book['id']}/assets/{rel_under_assets}"
                asset_lookup[rel.lower()] = api_url
                asset_lookup[rel_under_assets.lower()] = api_url
                asset_lookup[f"assets/{rel_under_assets}".lower()] = api_url
                asset_lookup[Path(rel_under_assets).name.lower()] = api_url

            def resolve_zip_asset(raw_path: str) -> str:
                cleaned = raw_path.strip().strip("'\"").lstrip("./").lstrip("/")
                if cleaned.startswith("http://") or cleaned.startswith("https://") or cleaned.startswith("/api/"):
                    return cleaned
                for key in (cleaned.lower(), cleaned.replace("assets/", "", 1).lower(), Path(cleaned).name.lower()):
                    if key in asset_lookup:
                        return asset_lookup[key]
                return raw_path

            # Order chapters: numeric section_number ascending first, then remaining files
            def sort_key(item: Tuple[str, str, Dict[str, Any], str]) -> Tuple[int, int, str]:
                _n, rel, fm, _b = item
                sn = str(fm.get("section_number", "")).strip()
                if sn.isdigit():
                    return (0, int(sn), rel.lower())
                return (1, 999, rel.lower())

            md_entries.sort(key=sort_key)

            for idx, (_n, rel, fm, body) in enumerate(md_entries, start=1):
                stem = Path(rel).stem
                sn = str(fm.get("section_number", "")).strip()
                ch_title = str(fm.get("title") or "").strip()
                if not ch_title:
                    m_h1 = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
                    ch_title = m_h1.group(1).strip() if m_h1 else stem.replace("-", " ").title()
                if sn.isdigit():
                    display_title = f"Part {int(sn)}: {ch_title}"
                else:
                    display_title = ch_title

                scope = "assigned"
                if not sn.isdigit() or _is_front_or_back_matter(stem, rel):
                    scope = "skipped"

                cleaned_md = self._clean_jekyll_distill_markdown(
                    body=body,
                    title=display_title,
                    subtitle=str(fm.get("subtitle") or "").strip(),
                    description=str(fm.get("description") or "").strip(),
                    resolve_asset=resolve_zip_asset,
                )

                rec = self.db.create_chapter(
                    book_id=book["id"],
                    order_index=idx,
                    title=display_title[:140],
                    start_page=idx,
                    end_page=idx,
                    has_pdf=False,
                    status="pending",
                    scope=scope,
                    slug=f"ch-{idx:02d}-{slugify(stem, 36)}",
                )
                self.fs.chapter_source_md(book["slug"], rec["slug"], ws_slug).write_text(cleaned_md, encoding="utf-8")

        self._sync_book_meta(book["id"], asset_count=asset_count)
        return self.db.get_book(book["id"])  # type: ignore[return-value]

    @staticmethod
    def _clean_jekyll_distill_markdown(
        body: str,
        title: str,
        subtitle: str,
        description: str,
        resolve_asset: Callable[[str], str],
    ) -> str:
        """Transform Jekyll/Distill Liquid tags and footnotes cleanly while preserving LaTeX and code."""
        text = body

        # 1. Strip {% raw %} and {% endraw %} keeping inner content
        text = re.sub(r"\{%\s*(?:end)?raw\s*%\}", "", text)

        # 2. Convert {% include figure.liquid ... %} or figure.html into Markdown image + caption
        def _replace_figure(m: re.Match[str]) -> str:
            inner = m.group(1)
            path_m = re.search(r'(?:path|src)\s*=\s*"([^"]+)"', inner) or re.search(r"(?:path|src)\s*=\s*'([^']+)'", inner)
            cap_m = re.search(r'caption\s*=\s*"((?:\\.|[^"\\])*)"', inner) or re.search(r"caption\s*=\s*'((?:\\.|[^'\\])*)'", inner)
            img_path = resolve_asset(path_m.group(1)) if path_m else ""
            caption = ""
            if cap_m:
                caption = cap_m.group(1).replace('\\"', '"').replace("\\'", "'")
                caption = BeautifulSoup(caption, "html.parser").get_text(" ", strip=True)
            if not img_path:
                return ""
            out = f"\n\n![{caption[:100] or 'Figure'}]({img_path})\n"
            if caption:
                out += f"\n*{caption}*\n"
            return out + "\n"

        text = re.sub(r"\{%\s*include\s+figure\.[^\s%]+\s+([\s\S]*?)%\}", _replace_figure, text)

        # 3. Convert {% details Summary %} ... {% enddetails %} into native collapsible <details>
        text = re.sub(
            r"\{%\s*details\s+(.*?)\s*%\}",
            lambda m: f"\n<details class=\"scholia-details\">\n<summary>{m.group(1).strip()}</summary>\n\n",
            text,
        )
        text = re.sub(r"\{%\s*enddetails\s*%\}", "\n\n</details>\n", text)

        # 4. Strip any remaining Liquid {% ... %} tags
        text = re.sub(r"\{%[\s\S]*?%\}", "", text)

        # 5. Convert <d-footnote>...</d-footnote> into numbered footnotes appended at the end
        footnotes: List[str] = []

        def _replace_footnote(m: re.Match[str]) -> str:
            fn_text = re.sub(r"\s+", " ", m.group(1).strip())
            footnotes.append(fn_text)
            idx = len(footnotes)
            return f"<sup>[{idx}]</sup>"

        text = re.sub(r"<d-footnote>([\s\S]*?)</d-footnote>", _replace_footnote, text)

        # 6. Convert raw HTML <figure>...</figure> or <img ...> tags
        def _replace_html_img(m: re.Match[str]) -> str:
            tag_html = m.group(0)
            soup = BeautifulSoup(tag_html, "html.parser")
            im = soup.find("img")
            if not im or not im.get("src"):
                return ""
            src = resolve_asset(str(im.get("src")))
            alt = str(im.get("alt") or "Figure").strip()
            return f"\n\n![{alt}]({src})\n\n"

        text = re.sub(r"<img\b[^>]*>", _replace_html_img, text, flags=re.IGNORECASE)

        # 7. Rewrite standard Markdown images ![alt](path)
        def _replace_md_img(m: re.Match[str]) -> str:
            alt, raw_p = m.group(1), m.group(2)
            return f"![{alt}]({resolve_asset(raw_p)})"

        text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", _replace_md_img, text)

        # 8. Strip empty <d-*> wrapper tags while keeping inner text
        text = re.sub(r"</?d-[a-z-]+[^>]*>", "", text, flags=re.IGNORECASE)

        header_lines = [f"# {title}"]
        if subtitle:
            header_lines.append(f"*{subtitle}*")
        if description:
            clean_desc = BeautifulSoup(description, "html.parser").get_text(" ", strip=True)
            if clean_desc:
                header_lines.append(f"> {clean_desc}")
        header = "\n\n".join(header_lines)

        if text.lstrip().startswith("# "):
            combined = text.strip()
        else:
            combined = f"{header}\n\n{text.strip()}"

        if footnotes:
            fn_lines = ["", "---", "", "## Footnotes", ""]
            for i, fn in enumerate(footnotes, start=1):
                fn_lines.append(f"{i}. {fn}")
            combined = combined + "\n" + "\n".join(fn_lines)

        return re.sub(r"\n{3,}", "\n\n", combined).strip() + "\n"

    # ---------- PDF ----------

    def _ingest_pdf(
        self,
        filename: str,
        content: bytes,
        title: str,
        authors: str,
        topics: List[str],
        workspace_id: Optional[str] = None,
        toc_level: Optional[int] = None,
        single_unit: bool = False,
        detect_printed_toc: bool = False,
        explicit_title: bool = False,
        explicit_authors: bool = False,
    ) -> Dict[str, Any]:
        doc = fitz.open(stream=content, filetype="pdf")
        try:
            meta = doc.metadata or {}
            book_title = title
            if not explicit_title and meta.get("title") and len(meta["title"].strip()) >= 3:
                meta_title = re.sub(r"\[[^\]]*em\]", "", meta["title"]).strip()
                # Ignore Adobe InDesign filenames like 250717_HUGFA_digital_version_RZ.indd
                if meta_title and not meta_title.lower().endswith((".indd", ".tex", ".dvi", ".pdf")):
                    book_title = meta_title
            if not explicit_authors and meta.get("author") and authors == "Unknown Author":
                authors = meta["author"].strip()
            page_count = max(1, len(doc))
            detected = self._detect_pdf_chapters(
                doc,
                book_title=book_title,
                toc_level=toc_level,
                single_unit=single_unit,
                detect_printed_toc=detect_printed_toc,
            )
        finally:
            doc.close()

        book = self.db.create_book(
            title=book_title,
            authors=authors,
            source_format="pdf",
            source_filename=filename,
            page_count=page_count,
            topic_areas=topics,
            workspace_id=workspace_id,
        )
        ws_slug = book.get("workspace_slug")
        src_path = self.fs.book_source_path(book["slug"], "pdf", ws_slug)
        src_path.write_bytes(content)

        created_chapters = []
        for idx, ch in enumerate(detected, start=1):
            rec = self.db.create_chapter(
                book_id=book["id"],
                order_index=idx,
                title=ch["title"],
                start_page=ch["start_page"],
                end_page=ch["end_page"],
                has_pdf=True,
                status="pending",
                scope=ch.get("scope", "assigned"),
            )
            created_chapters.append(rec)

        self.slice_pdf_chapters(book["slug"], src_path, created_chapters, workspace_slug=ws_slug)
        self._sync_book_meta(book["id"])
        return self.db.get_book(book["id"])  # type: ignore[return-value]

    def get_pdf_toc_tree(self, book_id: str) -> Dict[str, Any]:
        book = self.db.get_book(book_id)
        if not book:
            raise KeyError(f"Book {book_id} not found")
        if book["source_format"] != "pdf":
            return {"book_id": book["id"], "page_count": book["page_count"], "levels": [], "entries": []}
        src_pdf = self.fs.book_source_path(book["slug"], "pdf", book.get("workspace_slug"))
        if not src_pdf.exists():
            return {"book_id": book["id"], "page_count": book["page_count"], "levels": [], "entries": []}
        doc = fitz.open(str(src_pdf))
        try:
            total_pages = len(doc)
            raw_toc = doc.get_toc(simple=True) or []
        finally:
            doc.close()

        entries: List[Dict[str, Any]] = []
        valid = [(int(l), str(t).strip(), int(p)) for l, t, p in raw_toc if 1 <= int(p) <= total_pages]
        for idx, (lvl, title, sp) in enumerate(valid):
            ep = total_pages
            for next_lvl, _nt, next_sp in valid[idx + 1 :]:
                if next_lvl <= lvl:
                    ep = max(sp, next_sp - 1)
                    break
            entries.append(
                {
                    "index": idx,
                    "level": lvl,
                    "title": title or f"Section {idx + 1}",
                    "start_page": sp,
                    "end_page": min(total_pages, ep),
                }
            )
        levels = sorted({e["level"] for e in entries})
        return {
            "book_id": book["id"],
            "page_count": total_pages,
            "levels": levels,
            "entries": entries,
        }

    def detect_printed_toc_for_book(self, book_id: str, apply: bool = False) -> Dict[str, Any]:
        book = self.db.get_book(book_id)
        if not book:
            raise KeyError(f"Book {book_id} not found")
        if book["source_format"] != "pdf":
            raise ValueError("Printed-TOC detection is only supported for PDF volumes.")
        src_pdf = self.fs.book_source_path(book["slug"], "pdf", book.get("workspace_slug"))
        if not src_pdf.exists():
            raise FileNotFoundError("Source PDF not found in vault.")

        doc = fitz.open(str(src_pdf))
        try:
            detected, offset, toc_pages = self._detect_printed_toc(doc)
        finally:
            doc.close()

        if not detected:
            raise ValueError("No printed Table of Contents could be parsed from the early pages of this PDF.")

        updated_book = None
        if apply:
            updated_book = self.update_boundaries(book["id"], detected)
        return {
            "book_id": book["id"],
            "offset": offset,
            "toc_pages": toc_pages,
            "chapters": detected,
            "applied": apply,
            "book": updated_book,
        }

    def _detect_pdf_chapters(
        self,
        doc: fitz.Document,
        book_title: str = "Document",
        toc_level: Optional[int] = None,
        single_unit: bool = False,
        detect_printed_toc: bool = False,
    ) -> List[Dict[str, Any]]:
        total_pages = len(doc)
        if single_unit:
            return [{"title": book_title, "start_page": 1, "end_page": total_pages, "scope": "assigned"}]

        if detect_printed_toc:
            printed, _offset, _pages = self._detect_printed_toc(doc)
            if printed:
                return printed

        toc = doc.get_toc(simple=True) or []
        valid_toc = [(int(l), str(t).strip(), int(p)) for l, t, p in toc if 1 <= int(p) <= total_pages]

        if valid_toc:
            if toc_level is not None:
                selected = self._extract_toc_at_level(valid_toc, total_pages, toc_level)
                if selected:
                    return selected

            # Smart default detection:
            # Check if L1 has Part containers wrapping numbered L2 chapters (like PMPP 5th ed.)
            min_level = min(e[0] for e in valid_toc)
            l1 = [e for e in valid_toc if e[0] == min_level]
            l2 = [e for e in valid_toc if e[0] == min_level + 1]
            numbered_l2_chapters = [
                e for e in l2 if re.match(r"^(?:chapter\s+)?\d+\s+[A-Za-z]", e[1], re.IGNORECASE)
            ]

            if len(numbered_l2_chapters) >= 5:
                smart = self._extract_smart_part_chapter_toc(valid_toc, total_pages, min_level)
                if smart:
                    return smart

            primary = l1
            if len(primary) == 1 and len(l2) >= 2:
                primary = l2

            if primary:
                return self._toc_entries_to_chapters(primary, total_pages)

        # No embedded TOC -> try printed TOC automatically!
        printed, _offset, _pages = self._detect_printed_toc(doc)
        if printed:
            return printed

        # Heuristic scan for "Chapter N" headings on early lines of pages
        chapter_starts: List[Tuple[int, str]] = []
        pattern = re.compile(r"^(?:chapter|part|section)\s+(\d+|[IVXLCDM]+)\b[:.\-\s]*(.*)$", re.IGNORECASE)
        for pno in range(total_pages):
            text = doc[pno].get_text("text") or ""
            lines = [ln.strip() for ln in text.splitlines()[:8] if ln.strip()]
            for line in lines:
                match = pattern.match(line)
                if match and len(line) <= 100:
                    chapter_starts.append((pno + 1, line))
                    break

        if len(chapter_starts) >= 2:
            out: List[Dict[str, Any]] = []
            for idx, (sp, ch_title) in enumerate(chapter_starts):
                ep = chapter_starts[idx + 1][0] - 1 if idx + 1 < len(chapter_starts) else total_pages
                out.append(
                    {
                        "title": ch_title,
                        "start_page": sp,
                        "end_page": max(sp, ep),
                        "scope": "skipped" if _is_front_or_back_matter(ch_title) else "assigned",
                    }
                )
            return out

        # Default 25-page chunks
        chunk = 25
        out = []
        for idx, sp in enumerate(range(1, total_pages + 1, chunk), start=1):
            ep = min(total_pages, sp + chunk - 1)
            out.append({"title": f"Section {idx} (pp. {sp}-{ep})", "start_page": sp, "end_page": ep, "scope": "assigned"})
        return out

    @staticmethod
    def _toc_entries_to_chapters(
        entries: List[Tuple[int, str, int]],
        total_pages: int,
    ) -> List[Dict[str, Any]]:
        chapters: List[Dict[str, Any]] = []
        for idx, (_lvl, ch_title, start_page) in enumerate(entries):
            next_start = entries[idx + 1][2] if idx + 1 < len(entries) else total_pages + 1
            end_page = max(start_page, next_start - 1)
            clean_title = ch_title.strip() or f"Chapter {idx + 1}"
            chapters.append(
                {
                    "title": clean_title,
                    "start_page": int(start_page),
                    "end_page": min(total_pages, int(end_page)),
                    "scope": "skipped" if _is_front_or_back_matter(clean_title) else "assigned",
                }
            )
        return chapters

    def _extract_smart_part_chapter_toc(
        self,
        valid_toc: List[Tuple[int, str, int]],
        total_pages: int,
        min_level: int,
    ) -> List[Dict[str, Any]]:
        """Handle textbooks where L1 has Parts wrapping L2 numbered chapters (e.g., PMPP 5th ed.)."""
        picked: List[Tuple[int, str, int]] = []
        i = 0
        while i < len(valid_toc):
            lvl, title, sp = valid_toc[i]
            if lvl != min_level:
                i += 1
                continue
            # Gather direct L2 children before next L1
            j = i + 1
            children: List[Tuple[int, str, int]] = []
            while j < len(valid_toc) and valid_toc[j][0] > min_level:
                if valid_toc[j][0] == min_level + 1:
                    children.append(valid_toc[j])
                j += 1

            # Check if children are real numbered chapters (e.g. "2 Heterogeneous...", "A Numerical...")
            # rather than decimal subsections ("1.1 ...", "1.2 ...")
            child_chapters = [
                c
                for c in children
                if re.match(r"^(?:chapter\s+)?(?:\d+|[A-Z])\s+[A-Za-z]", c[1], re.IGNORECASE)
                and not re.match(r"^\d+\.\d+", c[1])
            ]
            if child_chapters:
                picked.extend(child_chapters)
            else:
                picked.append((lvl, title, sp))
            i = j

        # Sort by start_page preserving TOC order
        return self._toc_entries_to_chapters(picked, total_pages)

    def _extract_toc_at_level(
        self,
        valid_toc: List[Tuple[int, str, int]],
        total_pages: int,
        toc_level: int,
    ) -> List[Dict[str, Any]]:
        min_level = min(e[0] for e in valid_toc)
        if toc_level == 2:
            # Check if PMPP-style mixed Part/Chapter structure applies
            l2 = [e for e in valid_toc if e[0] == min_level + 1]
            numbered_l2 = [e for e in l2 if re.match(r"^(?:chapter\s+)?\d+\s+[A-Za-z]", e[1], re.IGNORECASE)]
            if len(numbered_l2) >= 5:
                return self._extract_smart_part_chapter_toc(valid_toc, total_pages, min_level)
        # Include entries at <= toc_level (replacing parents that have children at toc_level with their children)
        picked: List[Tuple[int, str, int]] = []
        for idx, (lvl, title, sp) in enumerate(valid_toc):
            if lvl > toc_level:
                continue
            if lvl < toc_level:
                # Check if this entry has any deeper children up to toc_level
                has_children = (
                    idx + 1 < len(valid_toc) and valid_toc[idx + 1][0] > lvl and valid_toc[idx + 1][0] <= toc_level
                )
                if has_children:
                    continue
            picked.append((lvl, title, sp))
        if not picked:
            picked = [e for e in valid_toc if e[0] == toc_level]
        return self._toc_entries_to_chapters(picked, total_pages)

    def _detect_printed_toc(self, doc: fitz.Document) -> Tuple[List[Dict[str, Any]], int, List[int]]:
        """Scan early pages for a printed Table of Contents, parse chapter entries, and calibrate PDF page offset."""
        total_pages = len(doc)
        scan_limit = min(25, total_pages)
        toc_pages: List[int] = []

        for pno in range(scan_limit):
            txt = _normalize_text_ws(doc[pno].get_text("text") or "")
            if re.search(r"(?:table\s+of\s+contents?|^\s*contents\s*$)", txt, re.IGNORECASE | re.MULTILINE):
                toc_pages.append(pno + 1)
                # Check if next 1-2 pages continue TOC
                for extra in (pno + 1, pno + 2):
                    if extra < scan_limit:
                        etxt = _normalize_text_ws(doc[extra].get_text("text") or "")
                        if len(re.findall(r"\b\d{1,3}\b", etxt)) >= 6 and len(etxt.splitlines()) >= 6:
                            toc_pages.append(extra + 1)
                break

        if not toc_pages:
            return [], 0, []

        toc_lines: List[str] = []
        for tp in toc_pages:
            raw = _normalize_text_ws(doc[tp - 1].get_text("text") or "")
            for ln in raw.splitlines():
                cleaned = re.sub(r"[ \t]+", " ", ln).strip()
                if cleaned:
                    toc_lines.append(cleaned)

        # Parse top-level integer chapters (1, 2, 3, ...) from printed TOC lines
        candidates: List[Tuple[int, str, int]] = []  # (chapter_num, title, printed_page)
        i = 0
        while i < len(toc_lines):
            line = toc_lines[i]
            # Pattern 1: Single line "1 Overview ... 9" or "Chapter 1: Overview 9"
            m1 = re.match(
                r"^(?:chapter\s+)?(\d{1,2})\s+([A-Za-z][^\n]{2,90}?)(?:\s*[.\u2026·_-]{2,}\s*|\s+)(\d{1,4})$",
                line,
                re.IGNORECASE,
            )
            if m1 and not re.match(r"^\d+\.\d+", line):
                cnum, ctitle, pnum = int(m1.group(1)), m1.group(2).strip(" .-"), int(m1.group(3))
                if 1 <= pnum <= total_pages and len(ctitle) >= 3:
                    candidates.append((cnum, ctitle, pnum))
                    i += 1
                    continue

            # Pattern 2: Two-line "10 Diving into the GPUs..." + "163"
            m2 = re.match(r"^(?:chapter\s+)?(\d{1,2})\s+([A-Za-z].{2,95})$", line, re.IGNORECASE)
            if m2 and not re.match(r"^\d+\.\d+", line) and i + 1 < len(toc_lines):
                nxt = toc_lines[i + 1]
                if re.fullmatch(r"\d{1,4}", nxt):
                    cnum, ctitle, pnum = int(m2.group(1)), m2.group(2).strip(" .-"), int(nxt)
                    if 1 <= pnum <= total_pages:
                        candidates.append((cnum, ctitle, pnum))
                        i += 2
                        continue

            # Pattern 3: Three-line "1" + "Overview" + "9"
            if re.fullmatch(r"\d{1,2}", line) and i + 2 < len(toc_lines):
                mid = toc_lines[i + 1]
                p_str = toc_lines[i + 2]
                if re.search(r"[A-Za-z]{3,}", mid) and not re.match(r"^\d+\.\d+", mid) and re.fullmatch(r"\d{1,4}", p_str):
                    cnum, ctitle, pnum = int(line), mid.strip(" .-"), int(p_str)
                    if 1 <= pnum <= total_pages:
                        candidates.append((cnum, ctitle, pnum))
                        i += 3
                        continue
            i += 1

        # Filter to a clean strictly increasing chapter sequence (1, 2, 3, ...) with non-decreasing page numbers
        filtered: List[Tuple[int, str, int]] = []
        last_num = 0
        last_page = 0
        for cnum, ctitle, pnum in candidates:
            if cnum == last_num + 1 and pnum >= last_page:
                filtered.append((cnum, ctitle, pnum))
                last_num = cnum
                last_page = pnum

        if len(filtered) < 2:
            return [], 0, toc_pages

        # Calibrate printed_page -> PDF page offset by matching first 3 chapters in the body
        offsets: List[int] = []
        toc_page_set = set(toc_pages)
        for cnum, ctitle, printed_p in filtered[:4]:
            words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", ctitle)]
            if not words:
                continue
            search_lo = max(1, printed_p - 5)
            search_hi = min(total_pages, printed_p + 25)
            for pdf_p in range(search_lo, search_hi + 1):
                if pdf_p in toc_page_set:
                    continue
                top_text = _normalize_text_ws(doc[pdf_p - 1].get_text("text") or "")
                top_head = " ".join(top_text.splitlines()[:12]).lower()
                if all(w in top_head for w in words[:3]):
                    offsets.append(pdf_p - printed_p)
                    break

        offset = sorted(offsets)[len(offsets) // 2] if offsets else 0

        chapters: List[Dict[str, Any]] = []
        adjusted = [
            (cnum, ctitle, max(1, min(total_pages, printed_p + offset)))
            for cnum, ctitle, printed_p in filtered
        ]
        if adjusted[0][2] > 1:
            chapters.append(
                {
                    "title": "Front Matter",
                    "start_page": 1,
                    "end_page": adjusted[0][2] - 1,
                    "scope": "skipped",
                }
            )
        for idx, (cnum, ctitle, sp) in enumerate(adjusted):
            ep = adjusted[idx + 1][2] - 1 if idx + 1 < len(adjusted) else total_pages
            full_title = f"{cnum}. {ctitle}"
            is_back = _is_front_or_back_matter(ctitle)
            chapters.append(
                {
                    "title": full_title,
                    "start_page": sp,
                    "end_page": max(sp, ep),
                    "scope": "skipped" if is_back else "assigned",
                }
            )
        return chapters, offset, toc_pages

    def slice_pdf_chapters(
        self,
        book_slug: str,
        source_pdf: Path,
        chapters: List[Dict[str, Any]],
        workspace_slug: Optional[str] = None,
    ) -> None:
        if not source_pdf.exists():
            return
        src = fitz.open(str(source_pdf))
        try:
            max_page = len(src)
            for ch in chapters:
                sp = max(1, min(max_page, int(ch["start_page"])))
                ep = max(sp, min(max_page, int(ch["end_page"])))
                out_doc = fitz.open()
                out_doc.insert_pdf(src, from_page=sp - 1, to_page=ep - 1)
                target_pdf = self.fs.chapter_source_pdf(book_slug, ch["slug"], workspace_slug)
                out_doc.save(str(target_pdf))
                out_doc.close()
        finally:
            src.close()

    def render_chapter_page_png(
        self,
        book_slug: str,
        chapter_slug: str,
        page_number: int,
        dpi: int = 150,
        workspace_slug: Optional[str] = None,
    ) -> Path:
        pdf_path = self.fs.chapter_source_pdf(book_slug, chapter_slug, workspace_slug)
        if not pdf_path.exists():
            raise FileNotFoundError(f"Chapter PDF not found at {pdf_path}")
        pages_dir = self.fs.chapter_dir(book_slug, chapter_slug, workspace_slug) / "pages"
        out_png = pages_dir / f"page-{page_number:03d}.png"
        if out_png.exists():
            return out_png
        doc = fitz.open(str(pdf_path))
        try:
            if page_number < 1 or page_number > len(doc):
                raise IndexError(f"Page {page_number} out of range (1..{len(doc)})")
            pix = doc[page_number - 1].get_pixmap(dpi=dpi)
            pix.save(str(out_png))
        finally:
            doc.close()
        return out_png

    def extract_chapter_text_and_slices(
        self,
        book_slug: str,
        chapter: Dict[str, Any],
        max_pages_per_slice: int = 20,
        workspace_slug: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        pdf_path = self.fs.chapter_source_pdf(book_slug, chapter["slug"], workspace_slug)
        md_path = self.fs.chapter_source_md(book_slug, chapter["slug"], workspace_slug)
        if pdf_path.exists():
            doc = fitz.open(str(pdf_path))
            try:
                total = len(doc)
                slice_size = max(1, min(20, max_pages_per_slice))
                slices: List[Dict[str, Any]] = []
                for start_idx in range(0, total, slice_size):
                    end_idx = min(total, start_idx + slice_size)
                    page_texts = []
                    for i in range(start_idx, end_idx):
                        abs_page = chapter["start_page"] + i
                        page_texts.append(f"[p. {abs_page}]\n{doc[i].get_text('text').strip()}")
                    slice_pdf = pdf_path
                    if total > slice_size:
                        sub_dir = self.fs.chapter_dir(book_slug, chapter["slug"], workspace_slug) / "slices"
                        sub_dir.mkdir(parents=True, exist_ok=True)
                        slice_pdf = sub_dir / f"slice-{start_idx + 1:03d}-{end_idx:03d}.pdf"
                        sub_doc = fitz.open()
                        sub_doc.insert_pdf(doc, from_page=start_idx, to_page=end_idx - 1)
                        sub_doc.save(str(slice_pdf))
                        sub_doc.close()
                    slices.append(
                        {
                            "slice_index": len(slices) + 1,
                            "local_start": start_idx + 1,
                            "local_end": end_idx,
                            "book_start_page": chapter["start_page"] + start_idx,
                            "book_end_page": chapter["start_page"] + end_idx - 1,
                            "pdf_path": str(slice_pdf),
                            "text": "\n\n".join(page_texts),
                        }
                    )
                return slices
            finally:
                doc.close()
        text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        return [
            {
                "slice_index": 1,
                "local_start": 1,
                "local_end": 1,
                "book_start_page": chapter["start_page"],
                "book_end_page": chapter["end_page"],
                "pdf_path": None,
                "text": text,
            }
        ]

    # ---------- Fidelity EPUB Ingestion ----------

    @staticmethod
    def _flatten_epub_toc(toc_items: Any) -> Dict[str, str]:
        """Map normalized href (without #fragment) -> TOC title."""
        out: Dict[str, str] = {}

        def _walk(items: Any) -> None:
            if not items:
                return
            for entry in items:
                if isinstance(entry, tuple) and len(entry) >= 2:
                    sec, children = entry[0], entry[1]
                    href = getattr(sec, "href", "") or ""
                    title = getattr(sec, "title", "") or ""
                    if href and title:
                        clean_href = href.split("#")[0].lstrip("/")
                        out.setdefault(clean_href, title.strip())
                        out.setdefault(posixpath.basename(clean_href), title.strip())
                    _walk(children)
                else:
                    href = getattr(entry, "href", "") or ""
                    title = getattr(entry, "title", "") or ""
                    if href and title:
                        clean_href = href.split("#")[0].lstrip("/")
                        out.setdefault(clean_href, title.strip())
                        out.setdefault(posixpath.basename(clean_href), title.strip())

        _walk(toc_items)
        return out

    def _ingest_epub(
        self,
        filename: str,
        content: bytes,
        title: str,
        authors: str,
        topics: List[str],
        workspace_id: Optional[str] = None,
        explicit_title: bool = False,
        explicit_authors: bool = False,
    ) -> Dict[str, Any]:
        # Write to temporary bytes via book dir after reading metadata
        temp_book = self.db.create_book(
            title=title,
            authors=authors,
            source_format="epub",
            source_filename=filename,
            page_count=1,
            topic_areas=topics,
            workspace_id=workspace_id,
        )
        ws_slug = temp_book.get("workspace_slug")
        src_path = self.fs.book_source_path(temp_book["slug"], "epub", ws_slug)
        src_path.write_bytes(content)

        epub_book = epub.read_epub(str(src_path))
        # Update title/author from EPUB metadata if not explicitly overridden
        if not explicit_title:
            dc_titles = epub_book.get_metadata("DC", "title")
            if dc_titles and dc_titles[0][0]:
                meta_t = str(dc_titles[0][0]).strip()
                if meta_t:
                    with self.db.connect() as conn:
                        conn.execute("UPDATE books SET title = ? WHERE id = ?", (meta_t, temp_book["id"]))
        if not explicit_authors and authors == "Unknown Author":
            dc_creators = epub_book.get_metadata("DC", "creator")
            if dc_creators:
                meta_a = ", ".join(str(c[0]).strip() for c in dc_creators if c and c[0])
                if meta_a:
                    with self.db.connect() as conn:
                        conn.execute("UPDATE books SET authors = ? WHERE id = ?", (meta_a, temp_book["id"]))

        # 1. Extract ALL image assets into books/<slug>/assets/
        assets_dir = self.fs.book_assets_dir(temp_book["slug"], ws_slug)
        img_lookup: Dict[str, str] = {}
        asset_count = 0
        for item in epub_book.get_items_of_type(ITEM_IMAGE):
            rel = item.get_name().lstrip("/")
            if not rel:
                continue
            target = assets_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.get_content())
            asset_count += 1
            api_url = f"/api/books/{temp_book['id']}/assets/{rel}"
            img_lookup[rel.lower()] = api_url
            img_lookup[posixpath.basename(rel).lower()] = api_url

        # 2. Build TOC title map
        toc_map = self._flatten_epub_toc(epub_book.toc)

        # 3. Iterate spine items in reading order (fallback to ITEM_DOCUMENT)
        ordered_docs: List[Any] = []
        seen_names: set[str] = set()
        for spine_id, _linear in (epub_book.spine or []):
            it = epub_book.get_item_with_id(spine_id)
            if it and it.get_type() == ITEM_DOCUMENT:
                if it.get_name() not in seen_names:
                    ordered_docs.append(it)
                    seen_names.add(it.get_name())
        for it in epub_book.get_items_of_type(ITEM_DOCUMENT):
            if it.get_name() not in seen_names:
                ordered_docs.append(it)
                seen_names.add(it.get_name())

        chapters_extracted: List[Tuple[str, str, str, str]] = []  # (title, md, scope, item_name)
        for idx, item in enumerate(ordered_docs, start=1):
            item_name = item.get_name()
            if isinstance(item, epub.EpubNav) or item_name.lower().endswith("nav.xhtml"):
                continue
            # Skip standalone high-res image wrapper pages (*_images.xhtml)
            if re.search(r"_images\.x?html?$", item_name, re.IGNORECASE):
                continue

            doc_dir = posixpath.dirname(item_name)

            def resolve_epub_img(src: str, _doc_dir: str = doc_dir) -> Optional[str]:
                if not src or src.startswith("data:"):
                    return None
                clean = src.split("#")[0].split("?")[0]
                joined = posixpath.normpath(posixpath.join(_doc_dir, clean)).lstrip("/")
                for cand in (joined.lower(), clean.lstrip("./").lstrip("/").lower(), posixpath.basename(clean).lower()):
                    if cand in img_lookup:
                        return img_lookup[cand]
                return None

            soup = BeautifulSoup(item.get_content(), "html.parser")
            body_root = soup.body or soup

            toc_title = toc_map.get(item_name.lstrip("/")) or toc_map.get(posixpath.basename(item_name))
            heading = body_root.find(["h1", "h2", "h3"])
            heading_txt = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)) if heading else ""
            ch_title = (toc_title or heading_txt or Path(item_name).stem.replace("-", " ").title()).strip()

            md_body = _html_node_to_markdown(body_root, resolve_epub_img)
            if len(md_body.strip()) < 20 and "![" not in md_body:
                continue

            if not md_body.lstrip().startswith("# "):
                md_body = f"# {ch_title}\n\n{md_body}"

            scope = "skipped" if _is_front_or_back_matter(ch_title, item_name) else "assigned"
            chapters_extracted.append((ch_title[:140], md_body, scope, item_name))

        if not chapters_extracted:
            chapters_extracted = [("Chapter 1", f"# {title}\n\nEmpty EPUB text content.\n", "assigned", "ch01")]

        for idx, (ch_title, ch_md, ch_scope, item_name) in enumerate(chapters_extracted, start=1):
            rec = self.db.create_chapter(
                book_id=temp_book["id"],
                order_index=idx,
                title=ch_title,
                start_page=idx,
                end_page=idx,
                has_pdf=False,
                status="pending",
                scope=ch_scope,
            )
            self.fs.chapter_source_md(temp_book["slug"], rec["slug"], ws_slug).write_text(ch_md, encoding="utf-8")

        with self.db.connect() as conn:
            conn.execute("UPDATE books SET page_count = ? WHERE id = ?", (len(chapters_extracted), temp_book["id"]))

        self._sync_book_meta(temp_book["id"], asset_count=asset_count)
        return self.db.get_book(temp_book["id"])  # type: ignore[return-value]

    # ---------- Markdown / TXT ----------

    def _ingest_markdown_or_txt(
        self,
        filename: str,
        content: bytes,
        norm_fmt: str,
        title: str,
        authors: str,
        topics: List[str],
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        text = content.decode("utf-8", errors="replace")
        sections: List[Tuple[str, str]] = []
        current_title = title
        current_lines: List[str] = []

        for line in text.splitlines():
            if line.startswith("# "):
                if current_lines and "\n".join(current_lines).strip():
                    sections.append((current_title, "\n".join(current_lines).strip() + "\n"))
                current_title = line[2:].strip() or f"Section {len(sections) + 1}"
                current_lines = [line]
            else:
                current_lines.append(line)

        if current_lines and "\n".join(current_lines).strip():
            sections.append((current_title, "\n".join(current_lines).strip() + "\n"))

        if not sections:
            sections = [(title, text or f"# {title}\n")]

        book = self.db.create_book(
            title=title,
            authors=authors,
            source_format=norm_fmt,
            source_filename=filename,
            page_count=len(sections),
            topic_areas=topics,
            workspace_id=workspace_id,
        )
        ws_slug = book.get("workspace_slug")
        src_path = self.fs.book_source_path(book["slug"], norm_fmt, ws_slug)
        src_path.write_bytes(content)

        for idx, (ch_title, ch_body) in enumerate(sections, start=1):
            rec = self.db.create_chapter(
                book_id=book["id"],
                order_index=idx,
                title=ch_title[:120],
                start_page=idx,
                end_page=idx,
                has_pdf=False,
                status="pending",
                scope="assigned",
            )
            self.fs.chapter_source_md(book["slug"], rec["slug"], ws_slug).write_text(ch_body, encoding="utf-8")

        self._sync_book_meta(book["id"])
        return self.db.get_book(book["id"])  # type: ignore[return-value]

    # ---------- Boundary Updates ----------

    def update_boundaries(
        self,
        book_id: str,
        chapters_input: List[Dict[str, Any]],
        topic_areas: List[str] | None = None,
    ) -> Dict[str, Any]:
        book = self.db.get_book(book_id)
        if not book:
            raise KeyError(f"Book {book_id} not found")

        if topic_areas is not None:
            self.db.update_book_topics(book["id"], topic_areas)

        is_pdf = book["source_format"] == "pdf"
        specs = []
        for item in chapters_input:
            specs.append(
                {
                    "id": item.get("id"),
                    "title": item["title"],
                    "start_page": int(item["start_page"]),
                    "end_page": int(item["end_page"]),
                    "has_pdf": is_pdf,
                    "scope": item.get("scope"),
                }
            )
        updated = self.db.replace_book_chapters(book["id"], specs)
        ws_slug = book.get("workspace_slug")
        if is_pdf:
            src_pdf = self.fs.book_source_path(book["slug"], "pdf", ws_slug)
            if src_pdf.exists():
                self.slice_pdf_chapters(book["slug"], src_pdf, updated, workspace_slug=ws_slug)
        self._sync_book_meta(book["id"])
        return self.db.get_book(book["id"])  # type: ignore[return-value]

    def _sync_book_meta(self, book_id: str, asset_count: Optional[int] = None) -> None:
        book = self.db.get_book(book_id)
        if not book:
            return
        ws_slug = book.get("workspace_slug")
        existing = self.fs.read_book_meta(book["slug"], ws_slug) or {}
        meta = {
            "id": book["id"],
            "workspace_id": book.get("workspace_id"),
            "workspace_slug": ws_slug,
            "slug": book["slug"],
            "title": book["title"],
            "authors": book["authors"],
            "source_format": book["source_format"],
            "source_url": book.get("source_url", ""),
            "page_count": book["page_count"],
            "topic_areas": book["topic_areas"],
            "asset_count": asset_count if asset_count is not None else existing.get("asset_count", 0),
            "chapters": [
                {
                    "id": c["id"],
                    "slug": c["slug"],
                    "order_index": c["order_index"],
                    "title": c["title"],
                    "start_page": c["start_page"],
                    "end_page": c["end_page"],
                    "status": c["status"],
                    "scope": c["scope"],
                }
                for c in book["chapters"]
            ],
        }
        self.fs.write_book_meta(book["slug"], meta, ws_slug)
