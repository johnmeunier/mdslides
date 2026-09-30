#!/usr/bin/env python3
"""
generate.py — Génère presentation.html depuis content.md (style Bold Signal corpo).

Usage:
  python3 generate.py                         # génération unique depuis content.md
  python3 generate.py --watch                 # regénère automatiquement dès que content.md change
  python3 generate.py --input path/to/file.md # génère depuis un autre markdown
"""

import base64, json, mimetypes, os, sys, re, time, hashlib, unicodedata
from typing import Optional

# ── Minification ──────────────────────────────────────────────────────────────
def minify_html(html: str) -> str:
    """Minifie le contenu HTML tout en préservant la fonctionnalité."""
    # Supprimer les commentaires HTML
    html = re.sub(r'<!--[\s\S]*?-->', '', html)

    # Les retours à la ligne font partie de la syntaxe Mermaid et l'indentation
    # des blocs de code doit etre preservee.
    mermaid_blocks: list[str] = []
    def stash_mermaid(match):
        mermaid_blocks.append(match.group(0))
        return f"__MERMAID_BLOCK_{len(mermaid_blocks) - 1}__"
    html = re.sub(r'<pre class="(?:mermaid|code-scroll)"[^>]*>[\s\S]*?</pre>', stash_mermaid, html)
    
    # Minifier le CSS inline dans les balises <style>
    def minify_style(match):
        css = match.group(1)
        # Supprimer commentaires CSS
        css = re.sub(r'/\*[\s\S]*?\*/', '', css)
        # Supprimer espaces autour des caractères spéciaux
        css = re.sub(r'\s*([{}:;,>+~])\s*', r'\1', css)
        css = re.sub(r'\s+', ' ', css)
        # Supprimer les espaces avant les accolades
        css = re.sub(r'\s+\{', '{', css)
        # Supprimer les point-virgules inutiles avant les accolades fermantes
        css = re.sub(r';\s*}', '}', css)
        return f'<style>{css.strip()}</style>'
    html = re.sub(r'<style>([\s\S]*?)</style>', minify_style, html)
    
    # Minifier le JavaScript inline dans les balises <script>
    def minify_script(match):
        js = match.group(1)
        # Supprimer commentaires single-line
        js = re.sub(r'//.*?(?=\n|$)', '', js)
        # Supprimer commentaires multi-line
        js = re.sub(r'/\*[\s\S]*?\*/', '', js)
        # Retirer espaces autour des opérateurs
        js = re.sub(r'\s*([{}()[\];:,=+\-*/<>!&|?])\s*', r'\1', js)
        # Espaces multiples -> 1 espace (sauf dans les chaînes)
        js = re.sub(r'([^"\'`])\s+', r'\1 ', js)
        js = re.sub(r'\s+([^"\'`])', r' \1', js)
        js = re.sub(r' +', ' ', js)
        return f'<script>{js.strip()}</script>'
    html = re.sub(r'<script>([\s\S]*?)</script>', minify_script, html)
    
    # Minifier le HTML général
    # Enlever espaces avant/après balises
    html = re.sub(r'>\s+<', '><', html)
    # Enlever retours à la ligne et espaces multiples en dehors des balises texte
    html = re.sub(r'\n\s*', '', html)
    # Espaces multiples -> 1 espace (sauf dans les balises)
    html = re.sub(r'(?<=>)\s+(?=<)', '', html)
    html = re.sub(r' {2,}', ' ', html)
    
    # Minifier les attributs data-* avec base64 (réduire les retours à la ligne)
    html = re.sub(r'data:([^"]*)"', lambda m: 'data:' + m.group(1).replace('\n', '') + '"', html)

    for index, block in enumerate(mermaid_blocks):
      html = html.replace(f"__MERMAID_BLOCK_{index}__", block)
    
    return html.strip()


# ── Chemins ───────────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
FONT_PATH    = os.path.join(SCRIPT_DIR, "./assets/publico-headline-bold-b64.txt")
DEFAULT_CONTENT_FILE = os.path.join(SCRIPT_DIR, "content.md")
CONF_DIR = os.path.join(SCRIPT_DIR, "CONF")


def slugify_kebab(text: str) -> str:
    s = str(text or "").strip().lower()
    if not s:
      return ""
    # Translittere les accents et ligatures (ex: "rétro" -> "retro").
    s = s.replace("œ", "oe").replace("æ", "ae")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def conference_slug_from_meta(meta: dict) -> str:
    title = str(meta.get("presentation-title", "") or "").strip()
    slug = slugify_kebab(title)
    if not slug:
      return "presentation"
    return slug


def output_file_from_source(source_file: str) -> str:
  source_abs = os.path.abspath(source_file)
  source_dir = os.path.dirname(source_abs)
  stem = os.path.splitext(os.path.basename(source_abs))[0]
  return os.path.join(source_dir, f"{stem}.html")


def markdown_file_from_source(source_file: str) -> str:
  source_abs = os.path.abspath(source_file)
  source_dir = os.path.dirname(source_abs)
  stem = os.path.splitext(os.path.basename(source_abs))[0]
  return os.path.join(source_dir, f"{stem}.md")


def conference_dir_from_source(source_file: str) -> str:
  return os.path.dirname(os.path.abspath(source_file))


# ── Police Publico Headline ───────────────────────────────────────────────────
def load_font() -> str:
    with open(FONT_PATH, "r") as f:
        return f.read().replace("\n", "").strip()


def parse_front_matter(text: str) -> tuple[dict, str]:
  """Parse un front matter YAML simplifie en tete de fichier.

  Format supporte:
  ---
  presentation-title: ...
  speaker-name: ...
  footer:
    left: ...
    center: ...
    right: ...
  ---
  """
  stripped = text.lstrip()
  if not stripped.startswith("---\n"):
    return {}, text

  start_offset = len(text) - len(stripped)
  end_idx = stripped.find("\n---\n", 4)
  if end_idx == -1:
    return {}, text

  raw_fm = stripped[4:end_idx]
  body = stripped[end_idx + 5 :]
  meta: dict = {}
  section: str | None = None

  for raw_line in raw_fm.splitlines():
    line = raw_line.rstrip()
    if not line or line.lstrip().startswith("#"):
      continue

    nested = re.match(r"^\s+([\w-]+):\s*(.*)$", line)
    if nested and section:
      sub_key, sub_val = nested.group(1), nested.group(2).strip()
      section_obj = meta.get(section)
      if isinstance(section_obj, dict):
        section_obj[sub_key] = sub_val
      continue

    m = re.match(r"^([\w-]+):\s*(.*)$", line)
    if not m:
      continue

    key, value = m.group(1), m.group(2).strip()
    if value:
      meta[key] = value
      section = None
    else:
      meta[key] = {}
      section = key

  return meta, text[:start_offset] + body


SUPPORTED_THEMES = {"corpo", "corail"}


def normalize_theme(value: object) -> str:
  """Retourne un theme connu, avec le theme corpo comme valeur de repli."""
  theme = slugify_kebab(str(value or ""))
  if theme in ("", "default", "corporate", "corpo"):
    return "corpo"
  return theme if theme in SUPPORTED_THEMES else "corpo"


# ── Parser content.md ────────────────────────────────────────────────────────
def parse_content(text: str) -> list[dict]:
  # Supporte la syntaxe markdown-first: "---content" au lieu de "---" puis "type: content".
  text = re.sub(r"(?m)^\s*---\s*([a-zA-Z0-9-]+)\s*$", r"---\ntype: \1", text)

  # Supprime les commentaires HTML
  text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

  known_keys = {
    "type", "label", "title", "subtitle", "heading", "speaker", "contact", "cta", "tagline",
    "text", "bullets", "items", "ordered", "bullets-type",
    "quote", "author", "role",
    "stat", "stat-label", "caption",
    "src", "alt", "full-screen", "scrolling",
    "display-category-title", "inverse", "hidden",
    "card-1-title", "card-1-body", "card-2-title", "card-2-body", "card-3-title", "card-3-body",
    "card-4-title", "card-4-body", "card-5-title", "card-5-body", "card-6-title", "card-6-body",
    "stat-1-value", "stat-1-label", "stat-2-value", "stat-2-label", "stat-3-value", "stat-3-label",
  }

  slides = []
  for part in re.split(r"\n---\n", text):
    part = part.strip()
    if not part:
      continue

    slide: dict = {}
    current_list_key: str | None = None
    current_list: list[str] = []
    markdown_lines: list[str] = []
    speaker_notes: list[str] = []

    raw_source_lines = part.split("\n")
    src_idx = 0
    while src_idx < len(raw_source_lines):
      raw_line = raw_source_lines[src_idx]
      src_idx += 1
      line = raw_line.strip()
      if not line:
        if current_list_key is None:
          markdown_lines.append("")
        continue

      # Bloc de code fence (```lang ... ```): capture brute, indentation preservee.
      if line.startswith("```"):
        if current_list_key is not None:
          slide[current_list_key] = current_list
          current_list_key = None
          current_list = []
        fence_lines = [line]
        while src_idx < len(raw_source_lines) and raw_source_lines[src_idx].strip() != "```":
          fence_lines.append(raw_source_lines[src_idx])
          src_idx += 1
        if src_idx < len(raw_source_lines):
          src_idx += 1  # saute la fence fermante
        fence_lines.append("```")
        markdown_lines.append("\n".join(fence_lines))
        continue

      if line.startswith(">>"):
        note = line[2:].strip()
        if note:
          speaker_notes.append(note)
        continue

      if m := re.match(r"^-\s+(.+)$", line):
        if current_list_key is not None:
          current_list.append(m.group(1).strip())
        else:
          markdown_lines.append(line)
        continue

      if m := re.match(r"^([\w-]+):\s*(.*)$", line):
        key, value = m.group(1), m.group(2).strip()

        if key not in known_keys:
          if current_list_key is not None:
            slide[current_list_key] = current_list
            current_list_key = None
            current_list = []
          markdown_lines.append(line)
          continue

        if current_list_key is not None:
          slide[current_list_key] = current_list
          current_list = []

        if not value:
          current_list_key = key
          current_list = []
        else:
          current_list_key = None
          slide[key] = value
        continue

      if current_list_key is not None:
        slide[current_list_key] = current_list
        current_list_key = None
        current_list = []

      markdown_lines.append(line)

    if current_list_key is not None:
      slide[current_list_key] = current_list

    if speaker_notes:
      slide["notes"] = speaker_notes

    # Un bloc est une slide uniquement s'il contient un type.
    if "type" not in slide:
      continue

    slide["type"] = str(slide["type"]).strip().lower()
    t = slide["type"]

    h1_list: list[str] = []
    h2_list: list[str] = []
    h3_list: list[str] = []
    h4_list: list[str] = []
    plain_lines: list[str] = []
    list_items: list[str] = []
    list_kind: str | None = None

    for line in markdown_lines:
      if not line:
        continue

      if m := re.match(r"^####\s+(.+)$", line):
        h4_list.append(m.group(1).strip())
        continue

      if m := re.match(r"^###\s+(.+)$", line):
        h3_list.append(m.group(1).strip())
        continue

      if m := re.match(r"^##\s+(.+)$", line):
        h2_list.append(m.group(1).strip())
        continue

      if m := re.match(r"^#\s+(.+)$", line):
        h1_list.append(m.group(1).strip())
        continue

      if m := re.match(r"^\d+\.\s+(.+)$", line):
        if list_kind is None:
          list_kind = "ordered"
        list_items.append(m.group(1).strip())
        continue

      if m := re.match(r"^-\s+(.+)$", line):
        if list_kind is None:
          list_kind = "unordered"
        list_items.append(m.group(1).strip())
        continue

      plain_lines.append(line)

    if t == "title":
      if not slide.get("title") and h1_list:
        slide["title"] = h1_list[0]

      if not slide.get("subtitle") and h2_list:
        slide["subtitle"] = h2_list[0]
      if not slide.get("heading") and slide.get("subtitle"):
        slide["heading"] = slide.get("subtitle")

      h3_copy = list(h3_list)
      if not slide.get("label") and h3_copy:
        slide["label"] = h3_copy[0]

      if not slide.get("speaker") and h4_list:
        slide["speaker"] = h4_list[0]
      elif not slide.get("speaker") and len(h3_copy) >= 2:
        # Compat legacy: ancien format ou speaker en second ###.
        slide["speaker"] = h3_copy[1]

    elif t == "agenda":
      if not slide.get("heading") and h1_list:
        slide["heading"] = h1_list[0]
      elif not slide.get("heading") and h2_list:
        slide["heading"] = h2_list[0]
      if not slide.get("subtitle") and h2_list:
        slide["subtitle"] = h2_list[0]
      if not slide.get("label") and h3_list:
        slide["label"] = h3_list[0]
      if not slide.get("items") and list_items:
        slide["items"] = list_items

    elif t == "content":
      if not slide.get("heading") and h1_list:
        slide["heading"] = h1_list[0]
      elif not slide.get("heading") and h2_list:
        slide["heading"] = h2_list[0]
      if not slide.get("subtitle") and h2_list:
        slide["subtitle"] = h2_list[0]
      if not slide.get("label") and h3_list:
        slide["label"] = h3_list[0]

      if not slide.get("bullets") and list_items:
        slide["bullets"] = list_items
        if list_kind == "ordered":
          slide["ordered"] = "true"

      if not slide.get("text") and plain_lines:
        slide["text"] = list(plain_lines)

    elif t == "bio":
      if not slide.get("heading") and h1_list:
        slide["heading"] = h1_list[0]
      elif not slide.get("heading") and h2_list:
        slide["heading"] = h2_list[0]
      if not slide.get("subtitle") and h2_list:
        slide["subtitle"] = h2_list[0]
      if not slide.get("label") and h3_list:
        slide["label"] = h3_list[0]

      if not slide.get("bullets") and list_items:
        slide["bullets"] = list_items
        if list_kind == "ordered":
          slide["ordered"] = "true"

      if not slide.get("text") and plain_lines:
        slide["text"] = list(plain_lines)

    elif t == "quote":
      if not slide.get("heading") and h1_list:
        slide["heading"] = h1_list[0]
      elif not slide.get("heading") and h2_list:
        slide["heading"] = h2_list[0]
      if not slide.get("subtitle") and h2_list:
        slide["subtitle"] = h2_list[0]
      if not slide.get("label") and h3_list:
        slide["label"] = h3_list[0]
      if not slide.get("quote") and plain_lines:
        slide["quote"] = "\n".join(plain_lines)

    elif t == "stat":
      if not slide.get("stat") and h1_list:
        slide["stat"] = h1_list[0]
      if not slide.get("stat-label") and h2_list:
        slide["stat-label"] = h2_list[0]
      if not slide.get("label") and h3_list:
        slide["label"] = h3_list[0]
      if not slide.get("caption") and h4_list:
        slide["caption"] = h4_list[0]

    elif t == "closing":
      if not slide.get("heading"):
        if h1_list:
          slide["heading"] = h1_list[0]
        elif h2_list:
          slide["heading"] = h2_list[0]

      if not slide.get("subtitle") and h2_list:
        slide["subtitle"] = h2_list[0]

      if not slide.get("speaker"):
        if len(h2_list) >= 2:
          slide["speaker"] = h2_list[1]
      if not slide.get("contact") and h3_list:
        slide["contact"] = h3_list[0]

    elif t in ("image", "iframe"):
      if not slide.get("heading") and h1_list:
        slide["heading"] = h1_list[0]
      elif not slide.get("heading") and h2_list:
        slide["heading"] = h2_list[0]
      if not slide.get("subtitle") and h2_list:
        slide["subtitle"] = h2_list[0]
      if not slide.get("label") and h3_list:
        slide["label"] = h3_list[0]
      if not slide.get("caption") and h4_list:
        slide["caption"] = h4_list[0]

    elif t == "subtitle":
      if not slide.get("heading") and h1_list:
        slide["heading"] = h1_list[0]
      elif not slide.get("heading") and h2_list:
        slide["heading"] = h2_list[0]
      if not slide.get("subtitle") and h2_list:
        slide["subtitle"] = h2_list[0]
      if not slide.get("label") and h3_list:
        slide["label"] = h3_list[0]

    else:
      if not slide.get("heading") and h1_list:
        slide["heading"] = h1_list[0]
      elif not slide.get("heading") and h2_list:
        slide["heading"] = h2_list[0]
      if not slide.get("subtitle") and h2_list:
        slide["subtitle"] = h2_list[0]
      if not slide.get("label") and h3_list:
        slide["label"] = h3_list[0]

    hidden_flag = str(slide.get("hidden", "false")).strip().lower()
    if hidden_flag in ("1", "true", "yes", "y", "oui"):
      continue

    slides.append(slide)

  # Post-processing : injecte le titre de catégorie courant sur les slides qui n'ont pas déjà un label.
  # Par défaut display-category-title vaut true ; mettre false pour désactiver sur un slide.
  # La catégorie courante est mise à jour à chaque slide de type "subtitle" (son champ heading).
  current_category: str = ""
  for slide in slides:
    if slide.get("type") == "subtitle":
      current_category = slide.get("heading", "")

    # Ces types gèrent leur propre label ou n'ont pas vocation à afficher la catégorie.
    if slide.get("type") in ("title", "subtitle", "closing", "agenda"):
      continue

    display_flag = str(slide.get("display-category-title", "true")).strip().lower()
    if display_flag not in ("0", "false", "no", "n", "non"):
      if not slide.get("label") and current_category:
        slide["label"] = current_category

  return slides


def build_footer_config(meta: dict) -> dict:
    footer_obj = meta.get("footer") if isinstance(meta.get("footer"), dict) else {}

    left = str(meta.get("footer-left", "") or footer_obj.get("left", "")).strip()
    center = str(meta.get("footer-center", "") or footer_obj.get("center", "")).strip()
    right = str(meta.get("footer-right", "") or footer_obj.get("right", "")).strip()

    # Fallback utile si rien n'est configure explicitement.
    if not left:
      title = str(meta.get("presentation-title", "")).strip()
      speaker = str(meta.get("speaker-name", "")).strip()
      left = " | ".join(x for x in [title, speaker] if x)

    return {
      "left": left,
      "center": center,
      "right": right,
    }


def build_page_title(meta: dict) -> str:
    presentation_title = str(meta.get("presentation-title", "") or "").strip() or "Présentation"
    author = str(meta.get("speaker-name", "") or "").strip() or "Auteur"
    return f"{presentation_title} - {author}"


def render_footer(footer_cfg: dict) -> str:
    left = str(footer_cfg.get("left", "")).strip()
    center = str(footer_cfg.get("center", "")).strip()
    right = str(footer_cfg.get("right", "")).strip()

    if not any([left, center, right]):
      return ""

    return (
      '<div class="slide-footer">'
      + f'<span class="footer-left">{esc(left)}</span>'
      + f'<span class="footer-center">{esc(center)}</span>'
      + f'<span class="footer-right">{esc(right)}</span>'
      + "</div>"
    )


def inline_asset_src(src: str, source_file: str, conference_dir: str) -> str:
    raw_src = str(src or "").strip()
    if not raw_src:
      return ""

    if re.match(r"^data:", raw_src, flags=re.IGNORECASE):
      return raw_src

    if re.match(r"^https?://", raw_src, flags=re.IGNORECASE):
      return raw_src

    # Supporte les chemins locaux de type file:///... en les embarquant.
    if raw_src.lower().startswith("file://"):
      candidate = raw_src[7:]
      if os.path.isfile(candidate):
        raw_src = candidate
      else:
        return src

    source_dir = os.path.dirname(os.path.abspath(source_file))
    candidates: list[str] = []

    if os.path.isabs(raw_src):
      if raw_src.startswith("/assets/"):
        # Nouvelle structure cible: assets par conférence.
        candidates.append(os.path.normpath(os.path.join(conference_dir, raw_src.lstrip("/"))))
        # Compatibilité avec l'ancienne structure racine.
        candidates.append(os.path.normpath(os.path.join(SCRIPT_DIR, raw_src.lstrip("/"))))
      else:
        candidates.append(raw_src)
    else:
      # 1) relatif au markdown source
      candidates.append(os.path.normpath(os.path.join(source_dir, raw_src)))
      # 2) relatif au dossier de conférence
      candidates.append(os.path.normpath(os.path.join(conference_dir, raw_src)))
      # 3) relatif à la racine projet (fallback)
      candidates.append(os.path.normpath(os.path.join(SCRIPT_DIR, raw_src)))

    candidate = ""
    for path in candidates:
      if os.path.isfile(path):
        candidate = path
        break

    if not candidate:
      return raw_src

    mime_type, _ = mimetypes.guess_type(candidate)
    if not mime_type:
      mime_type = "application/octet-stream"

    with open(candidate, "rb") as f:
      payload = base64.b64encode(f.read()).decode("ascii")

    return f"data:{mime_type};base64,{payload}"

# ── Helpers HTML ─────────────────────────────────────────────────────────────
def esc(s: object) -> str:
  if s is None:
    text = ""
  elif isinstance(s, list):
    text = "\n".join(str(x) for x in s if x is not None)
  else:
    text = str(s)
  return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def md(s: object, source_file: Optional[str] = None, conference_dir: Optional[str] = None) -> str:
  """Convertit une subset Markdown (liens, images, emphases) en HTML."""
  s = esc(s)

  # Images markdown ![alt](src)
  def _replace_image(match: re.Match) -> str:
    alt = match.group(1).strip()
    src = match.group(2).strip()

    # Bloque les schemas dangereux.
    if re.match(r"(?i)\s*(javascript:|data:)", src):
      return alt

    resolved_src = src
    if source_file and conference_dir:
      resolved_src = inline_asset_src(src, source_file, conference_dir)

    return f'<img class="md-image" src="{resolved_src}" alt="{alt}" loading="lazy" />'

  s = re.sub(r"!\[([^\]]*)\]\(([^\)\s]+)\)", _replace_image, s)

  # Liens markdown [texte](url) avec ouverture dans un nouvel onglet.
  def _replace_link(match: re.Match) -> str:
    label = match.group(1).strip() or match.group(2).strip()
    href = match.group(2).strip()

    # Bloque les schemas dangereux.
    if re.match(r"(?i)\s*(javascript:|data:)", href):
      return label

    return (
      f'<a class="ext-link" href="{href}" target="_blank" rel="noopener noreferrer">'
      f'{label}'
      '<span class="ext-link-icon" aria-hidden="true">↗</span>'
      '<span class="sr-only"> (nouvel onglet)</span>'
      '</a>'
    )

  s = re.sub(r"(?<!!)\[([^\]]+)\]\(([^\)\s]+)\)", _replace_link, s)
  s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
  s = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         s)
  # Emphase "tag": _texte_ (sans changer la semantique de *italique*).
  s = re.sub(r"(?<!\w)_(?!\s)([^_\n]+?)(?<!\s)_(?!\w)", r'<span class="inline-emph">\1</span>', s)
  return s


def _split_md_table_row(line: str) -> Optional[list[str]]:
  raw = str(line or "").strip()
  if not raw.startswith("|"):
    return None

  # Supporte les lignes avec ou sans pipe final.
  if raw.endswith("|"):
    raw = raw[:-1]
  raw = raw[1:]
  cells = [c.strip() for c in raw.split("|")]
  return cells if cells else None


def _is_md_table_separator(line: str, col_count: int) -> bool:
  cells = _split_md_table_row(line)
  if not cells or len(cells) != col_count:
    return False

  # Accepte --- / :--- / ---: / :---:
  for cell in cells:
    if not re.match(r"^:?-{3,}:?$", cell):
      return False
  return True


# Alias de langages vers les identifiants highlight.js (bundle "common").
# Tout langage inconnu tombe en repli sur du texte brut (pas de coloration).
CODE_LANG_ALIASES = {
  "": "plaintext",
  "text": "plaintext", "txt": "plaintext", "raw": "plaintext", "plain": "plaintext",
  "js": "javascript", "jsx": "javascript", "mjs": "javascript", "cjs": "javascript", "node": "javascript",
  "ts": "typescript", "tsx": "typescript",
  "py": "python", "python3": "python",
  "sh": "bash", "shell": "bash", "zsh": "bash", "console": "shell", "terminal": "shell",
  "yml": "yaml",
  "c++": "cpp", "c#": "csharp", "cs": "csharp",
  "golang": "go",
  "kt": "kotlin", "kts": "kotlin",
  "html": "xml", "xhtml": "xml", "vue": "xml", "svg": "xml",
  "md": "markdown",
  "objc": "objectivec",
  "docker": "dockerfile",
}


def render_code_block(code: str, lang: str, reveal_idx: int) -> str:
  """Rend un bloc de code avec header (langage + bouton copier) et scroll interne."""
  raw_lang = str(lang or "").strip().lower()
  hljs_lang = CODE_LANG_ALIASES.get(raw_lang, raw_lang or "plaintext")
  label = (raw_lang or "text").upper()
  return (
    f'<div class="code-block reveal" data-no-nav="true" style="transition-delay:{reveal_idx*0.08:.2f}s">'
    f'<div class="code-header">'
    f'<span class="code-lang">{esc(label)}</span>'
    f'<button type="button" class="code-copy-btn" aria-label="Copier le code">&#10697; Copier</button>'
    f'</div>'
    f'<pre class="code-scroll" tabindex="0"><code class="language-{esc(hljs_lang)}">{esc(code)}</code></pre>'
    f'<span class="code-scroll-hint" aria-hidden="true">&#9660; scroll</span>'
    '</div>'
  )


def _render_content_text_blocks(lines: list[str], source_file: str, conference_dir: str) -> str:
  blocks: list[str] = []
  i = 0
  reveal_idx = 0

  while i < len(lines):
    line = str(lines[i]).strip()

    # Bloc fence ```lang ... ``` (capture en un seul element multi-lignes par parse_content).
    if line.startswith("```"):
      fence_lines = line.split("\n")
      fence_lang = fence_lines[0][3:].strip().lower()
      body_lines = fence_lines[1:]
      if body_lines and body_lines[-1].strip() == "```":
        body_lines = body_lines[:-1]
      body = "\n".join(body_lines).strip("\n")

      if fence_lang == "mermaid":
        if body:
          blocks.append(
            f'<div class="mermaid-wrap reveal" style="transition-delay:{reveal_idx*0.08:.2f}s">'
            f'<pre class="mermaid">{esc(body)}</pre>'
            '</div>'
          )
          reveal_idx += 1
      else:
        blocks.append(render_code_block(body, fence_lang, reveal_idx))
        reveal_idx += 1
      i += 1
      continue

    is_mermaid_start = re.match(
      r"^(?:flowchart|graph|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|journey|gantt|pie|mindmap|timeline|gitGraph|quadrantChart|requirementDiagram|C4Context)\b",
      line,
      flags=re.IGNORECASE,
    )

    if is_mermaid_start:
      diagram_lines: list[str] = []
      while i < len(lines):
        diagram_line = str(lines[i]).strip()
        diagram_lines.append(diagram_line)
        i += 1

      if diagram_lines:
        diagram_source = "\n".join(diagram_lines)
        blocks.append(
          f'<div class="mermaid-wrap reveal" style="transition-delay:{reveal_idx*0.08:.2f}s">'
          f'<pre class="mermaid">{esc(diagram_source)}</pre>'
          '</div>'
        )
        reveal_idx += 1
      continue

    header_cells = _split_md_table_row(line)

    # Table markdown: header + separator + n rows
    if (
      header_cells
      and i + 1 < len(lines)
      and _is_md_table_separator(lines[i + 1], len(header_cells))
    ):
      rows: list[list[str]] = []
      j = i + 2
      while j < len(lines):
        row_cells = _split_md_table_row(lines[j])
        if not row_cells or len(row_cells) != len(header_cells):
          break
        rows.append(row_cells)
        j += 1

      thead = "".join(f"<th>{md(cell, source_file, conference_dir)}</th>" for cell in header_cells)
      tbody = "".join(
        "<tr>" + "".join(f"<td>{md(cell, source_file, conference_dir)}</td>" for cell in row) + "</tr>"
        for row in rows
      )
      blocks.append(
        f'<div class="content-text content-table reveal" style="transition-delay:{reveal_idx*0.08:.2f}s">'
        f'<div class="md-table-wrap"><table class="md-table"><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table></div>'
        f'</div>'
      )
      reveal_idx += 1
      i = j
      continue

    blocks.append(
      f'<p class="content-text reveal" style="transition-delay:{reveal_idx*0.08:.2f}s">'
      f'{md(line, source_file, conference_dir)}'
      '</p>'
    )
    reveal_idx += 1
    i += 1

  return "".join(blocks)


# ── Rendus par type de slide ──────────────────────────────────────────────────
def render_slide(slide: dict, idx: int, total: int, source_file: str, conference_dir: str) -> str:
    t = slide.get("type", "content")
    num = f'<div class="slide-num">{idx} / {total}</div>'
    inverse_flag = str(slide.get("inverse", "")).strip().lower()
    inv = " slide-inverse" if inverse_flag in ("1", "true", "yes", "y", "oui") else ""

    # ── title ────────────────────────────────────────────────────────────────
    if t == "title":
        label    = slide.get("label", "")
        title    = slide.get("title", "Titre")
        subtitle = slide.get("subtitle", "") or slide.get("heading", "")
        speaker  = slide.get("speaker", "")
        return f"""
<section class="slide slide-title{inv}" id="s{idx}">
  <div class="slide-content">
    {f'<span class="tag reveal">{esc(label)}</span>' if label else ''}
    <h1 class="reveal">{md(title)}</h1>
    {f'<p class="subtitle reveal">{md(subtitle)}</p>' if subtitle else ''}
    {f'<p class="speaker reveal">{esc(speaker)}</p>' if speaker else ''}
  </div>
  {num}
</section>"""

    # ── subtitle (slide de transition) ─────────────────────────────────────
    if t == "subtitle":
        label = slide.get("label", "")
        heading = slide.get("heading", "")
        subtitle = slide.get("subtitle", "")
        return f"""
<section class="slide slide-subtitle-break{inv}" id="s{idx}">
  <div class="slide-content">
    {f'<span class="tag reveal">{esc(label)}</span>' if label else ''}
    {f'<h1 class="reveal">{md(heading)}</h1>' if heading else ''}
    {f'<p class="slide-subtitle reveal">{md(subtitle)}</p>' if subtitle else ''}
  </div>
  {num}
</section>"""

    # ── agenda ───────────────────────────────────────────────────────────────
    if t == "agenda":
        label = slide.get("label", "")
        heading = slide.get("heading", "Au programme")
        subtitle = slide.get("subtitle", "")
        items   = slide.get("items", [])
        items_html = "".join(
            f'<li class="reveal" style="transition-delay:{i*0.12:.2f}s">'
            f'<span class="agenda-num">{i+1:02d}</span>'
            f'<span>{md(item)}</span></li>'
            for i, item in enumerate(items)
        )
        return f"""
<section class="slide slide-agenda{inv}" id="s{idx}">
  <div class="slide-content">
    {f'<span class="tag reveal">{esc(label)}</span>' if label else ''}
    {f'<h1 class="reveal">{md(heading)}</h1>' if heading else ''}
    {f'<p class="slide-subtitle reveal">{md(subtitle)}</p>' if subtitle else ''}
    <ol class="agenda-list">{items_html}</ol>
  </div>
  {num}
</section>"""

    # ── content ──────────────────────────────────────────────────────────────
    if t == "content":
        label   = slide.get("label", "")
        heading = slide.get("heading", "")
        subtitle = slide.get("subtitle", "")
        text_val = slide.get("text", "")
        bullets = slide.get("bullets", [])
        ordered = False
        bullets_type = str(slide.get("bullets-type", "")).strip().lower()
        ordered_flag = str(slide.get("ordered", "")).strip().lower()
        if bullets_type in ("ordered", "numbered", "ol", "numbers"):
            ordered = True
        if ordered_flag in ("1", "true", "yes", "y", "oui"):
            ordered = True

        text_html = ""
        if isinstance(text_val, list):
          text_html = _render_content_text_blocks(text_val, source_file, conference_dir)
        elif text_val:
          text_html = f'<p class="content-text reveal">{md(str(text_val), source_file, conference_dir)}</p>'

        list_class = "bullets bullets-ordered" if ordered else "bullets"
        bullets_html = "".join(
          f'<li class="reveal" style="transition-delay:{i*0.1:.1f}s">{md(b, source_file, conference_dir)}</li>'
            for i, b in enumerate(bullets)
        )
        list_html = f'<ol class="{list_class}">{bullets_html}</ol>' if ordered else f'<ul class="{list_class}">{bullets_html}</ul>'
        return f"""
<section class="slide slide-text{inv}" id="s{idx}">
  <div class="slide-content">
    {f'<span class="tag reveal">{esc(label)}</span>' if label else ''}
    {f'<h1 class="reveal">{md(heading)}</h1>' if heading else ''}
    {f'<p class="slide-subtitle reveal">{md(subtitle)}</p>' if subtitle else ''}
    {text_html}
    {list_html}
  </div>
  {num}
</section>"""

    # ── bio ──────────────────────────────────────────────────────────────────
    if t == "bio":
        label = slide.get("label", "")
        heading = slide.get("heading", "")
        subtitle = slide.get("subtitle", "")
        text_val = slide.get("text", "")
        bullets = slide.get("bullets", [])
        ordered = False
        bullets_type = str(slide.get("bullets-type", "")).strip().lower()
        ordered_flag = str(slide.get("ordered", "")).strip().lower()
        if bullets_type in ("ordered", "numbered", "ol", "numbers"):
            ordered = True
        if ordered_flag in ("1", "true", "yes", "y", "oui"):
            ordered = True

        text_html = ""
        if isinstance(text_val, list):
          text_html = _render_content_text_blocks(text_val, source_file, conference_dir)
        elif text_val:
          text_html = f'<p class="content-text reveal">{md(str(text_val), source_file, conference_dir)}</p>'

        bullets_html = ""
        if bullets:
          list_class = "bullets bullets-ordered" if ordered else "bullets"
          items_html = "".join(
            f'<li class="reveal" style="transition-delay:{i*0.1:.1f}s">{md(b, source_file, conference_dir)}</li>'
            for i, b in enumerate(bullets)
          )
          bullets_html = (
            f'<ol class="{list_class}">{items_html}</ol>'
            if ordered else
            f'<ul class="{list_class}">{items_html}</ul>'
          )

        src = inline_asset_src(slide.get("src", ""), source_file, conference_dir)
        alt = slide.get("alt", "")
        image_html = (
          f'<img class="bio-media reveal" src="{esc(src)}" alt="{esc(alt)}" loading="lazy">'
          if src
          else '<div class="bio-media bio-media-missing reveal">Photo manquante: renseigne la cle src:</div>'
        )

        return f"""
<section class="slide slide-bio{inv}" id="s{idx}">
  <div class="slide-content">
    <div class="bio-grid">
      <div class="bio-visual">{image_html}</div>
      <div class="bio-copy">
        {f'<span class="tag reveal">{esc(label)}</span>' if label else ''}
        {f'<h1 class="reveal">{md(heading)}</h1>' if heading else ''}
        {f'<p class="slide-subtitle reveal">{md(subtitle)}</p>' if subtitle else ''}
        {text_html}
        {bullets_html}
      </div>
    </div>
  </div>
  {num}
</section>"""

    # ── stat ─────────────────────────────────────────────────────────────────
    if t == "stat":
        label      = slide.get("label", "")
        stat       = slide.get("stat", "")
        stat_label = slide.get("stat-label", "")
        caption    = slide.get("caption", "")
        return f"""
<section class="slide slide-stat{inv}" id="s{idx}">
  <div class="slide-content" style="text-align:center;">
    {f'<span class="tag reveal">{esc(label)}</span>' if label else ''}
    <div class="big-number reveal">{esc(stat)}</div>
    {f'<h2 class="reveal stat-label-heading" style="margin-top:0.5rem;">{esc(stat_label)}</h2>' if stat_label else ''}
    {f'<p class="stat-caption reveal">{md(caption)}</p>' if caption else ''}
  </div>
  {num}
</section>"""

    # ── stats-row ────────────────────────────────────────────────────────────
    if t == "stats-row":
        label = slide.get("label", "")
        heading = slide.get("heading", "")
        subtitle = slide.get("subtitle", "")
        teal    = "var(--corpo-teal)"
        red     = "var(--corpo-red)"
        colors  = [teal, red, teal]
        stats_html = ""
        for i in range(1, 4):
            v = slide.get(f"stat-{i}-value", "")
            l = slide.get(f"stat-{i}-label", "")
            if v:
                stats_html += (
                    f'<div class="stat reveal" style="transition-delay:{(i-1)*0.15:.2f}s">'
                    f'<div class="stat-num" style="color:{colors[i-1]}">{esc(v)}</div>'
                    f'<div class="stat-label">{esc(l)}</div></div>'
                )
        return f"""
<section class="slide slide-stats-row{inv}" id="s{idx}">
  <div class="slide-content">
    {f'<span class="tag reveal">{esc(label)}</span>' if label else ''}
    {f'<h1 class="reveal">{md(heading)}</h1>' if heading else ''}
    {f'<p class="slide-subtitle reveal">{md(subtitle)}</p>' if subtitle else ''}
    <div class="stat-row">{stats_html}</div>
  </div>
  {num}
</section>"""

    # ── cards ────────────────────────────────────────────────────────────────
    if t == "cards":
        label   = slide.get("label", "")
        heading = slide.get("heading", "")
        subtitle = slide.get("subtitle", "")
        cards_html = ""
        for i in range(1, 7):
            ct = slide.get(f"card-{i}-title", "")
            cb = slide.get(f"card-{i}-body",  "")
            if ct:
                cards_html += (
                    f'<div class="card reveal" style="transition-delay:{(i-1)*0.1:.1f}s">'
                    f'<h3>{md(ct)}</h3><p>{md(cb)}</p></div>'
                )
        return f"""
<section class="slide slide-cards{inv}" id="s{idx}">
  <div class="slide-content">
    {f'<span class="tag reveal">{esc(label)}</span>' if label else ''}
    {f'<h1 class="reveal">{md(heading)}</h1>' if heading else ''}
    {f'<p class="slide-subtitle reveal">{md(subtitle)}</p>' if subtitle else ''}
    <div class="cards-grid">{cards_html}</div>
  </div>
  {num}
</section>"""

    # ── quote ────────────────────────────────────────────────────────────────
    if t == "quote":
        label = slide.get("label", "")
        heading = slide.get("heading", "")
        subtitle = slide.get("subtitle", "")
        quote = slide.get("quote", "").strip()
        if (quote.startswith('"') and quote.endswith('"')) or (quote.startswith("\u201c") and quote.endswith("\u201d")):
            quote = quote[1:-1].strip()
        author = slide.get("author", "")
        role = slide.get("role", "")
        return f"""
<section class="slide slide-quote{inv}" id="s{idx}">
  <div class="slide-content" style="text-align:center;">
    {f'<span class="tag reveal">{esc(label)}</span>' if label else ''}
    {f'<h1 class="reveal">{md(heading)}</h1>' if heading else ''}
    {f'<p class="slide-subtitle reveal">{md(subtitle)}</p>' if subtitle else ''}
    <blockquote class="reveal quote-typewriter" data-typewriter-text="{esc(quote)}">{md(quote)}</blockquote>
    <button type="button" class="quote-copy-btn reveal" aria-label="Copier la citation">Copier la citation</button>
    <div class="quote-attr reveal">
      {f'<strong>{esc(author)}</strong>' if author else ''}
      {f'<span class="role">{esc(role)}</span>' if role else ''}
    </div>
  </div>
  {num}
</section>"""

    # ── image ────────────────────────────────────────────────────────────────
    if t == "image":
        label = slide.get("label", "")
        heading = slide.get("heading", "")
        subtitle = slide.get("subtitle", "")
        src = inline_asset_src(slide.get("src", ""), source_file, conference_dir)
        alt = slide.get("alt", "")
        caption = slide.get("caption", "")
        full_screen_flag = str(slide.get("full-screen", "")).strip().lower()
        is_fullscreen = full_screen_flag in ("1", "true", "yes", "y", "oui")
        
        image_html = (
            f'<img class="slide-image-media reveal" src="{esc(src)}" alt="{esc(alt)}" loading="lazy">'
            if src
            else '<div class="image-missing reveal">Image manquante: renseigne la cle src:</div>'
        )
        
        if is_fullscreen:
            # Mode plein écran : juste l'image, mais le titre est caché pour le TOC
            return f"""
<section class="slide slide-image slide-image-fullscreen{inv}" id="s{idx}">
  {f'<h1 hidden>{md(heading)}</h1>' if heading else ''}
  <div class="slide-content fullscreen-content">
    <div class="fullscreen-image-container">
      <div class="slide-image-frame reveal">{image_html}</div>
    </div>
  </div>
  {num}
</section>"""
        else:
            # Mode normal avec titre et caption
            return f"""
<section class="slide slide-image{inv}" id="s{idx}">
  <div class="slide-content">
    {f'<span class="tag reveal">{esc(label)}</span>' if label else ''}
    {f'<h1 class="reveal">{md(heading)}</h1>' if heading else ''}
    {f'<p class="slide-subtitle reveal">{md(subtitle)}</p>' if subtitle else ''}
    <div class="image-wrap">
      <div class="slide-image-frame reveal">{image_html}</div>
    </div>
    {f'<p class="image-caption reveal">{md(caption)}</p>' if caption else ''}
  </div>
  {num}
</section>"""

    # ── iframe ───────────────────────────────────────────────────────────────
    if t == "iframe":
        label = slide.get("label", "")
        heading = slide.get("heading", "")
        subtitle = slide.get("subtitle", "")
        src = str(slide.get("src", "")).strip()
        caption = slide.get("caption", "")
        full_screen_flag = str(slide.get("full-screen", "")).strip().lower()
        is_fullscreen = full_screen_flag in ("1", "true", "yes", "y", "oui")
        scrolling_flag = str(slide.get("scrolling", "no")).strip().lower()
        scrolling = "yes" if scrolling_flag in ("1", "true", "yes", "y", "oui") else "no"

        if src:
            iframe_html = (
                f'<iframe class="slide-iframe-media reveal" src="{esc(src)}" '
                f'scrolling="{scrolling}" '
                f'sandbox="allow-scripts allow-same-origin allow-forms" '
                f'loading="lazy" '
                f'title="{esc(heading or src)}"></iframe>'
            )
        else:
            iframe_html = '<div class="image-missing reveal">URL manquante: renseigne la clé src:</div>'

        if is_fullscreen:
            return f"""
<section class="slide slide-iframe slide-iframe-fullscreen{inv}" id="s{idx}">
  {f'<h1 hidden>{md(heading)}</h1>' if heading else ''}
  <div class="slide-content fullscreen-content">
    <div class="fullscreen-iframe-container">
      <div class="slide-iframe-frame reveal">{iframe_html}</div>
    </div>
  </div>
  {num}
</section>"""
        else:
            return f"""
<section class="slide slide-iframe{inv}" id="s{idx}">
  <div class="slide-content">
    {f'<span class="tag reveal">{esc(label)}</span>' if label else ''}
    {f'<h1 class="reveal">{md(heading)}</h1>' if heading else ''}
    {f'<p class="slide-subtitle reveal">{md(subtitle)}</p>' if subtitle else ''}
    <div class="image-wrap">
      <div class="slide-iframe-frame reveal">{iframe_html}</div>
    </div>
    {f'<p class="image-caption reveal">{md(caption)}</p>' if caption else ''}
  </div>
  {num}
</section>"""

    # ── closing ──────────────────────────────────────────────────────────────
    if t == "closing":
        label = slide.get("label", "")
        heading = slide.get("heading", "Merci !")
        subtitle = slide.get("subtitle", "") or slide.get("tagline", "")
        cta     = slide.get("cta", "")
        speaker = slide.get("speaker", "")
        contact = slide.get("contact", "")
        src = inline_asset_src(slide.get("src", ""), source_file, conference_dir)
        alt = slide.get("alt", "")
        with_image_class = " slide-closing-with-image" if src else ""
        image_html = (
          f'<div class="closing-visual"><img class="closing-media reveal" src="{esc(src)}" alt="{esc(alt)}" loading="lazy"></div>'
          if src else ""
        )
        return f"""
<section class="slide slide-closing{with_image_class}{inv}" id="s{idx}">
  <div class="slide-content">
    <div class="closing-layout">
      <div class="closing-copy">
        {f'<span class="tag reveal">{esc(label)}</span>' if label else ''}
        <h1 class="reveal">{md(heading)}</h1>
        {f'<p class="slide-subtitle reveal">{md(subtitle)}</p>' if subtitle else ''}
        {f'<div class="cta-link reveal">{esc(cta)}</div>' if cta else ''}
        {f'<p class="speaker reveal" style="margin-top:2rem;">{esc(speaker)}</p>' if speaker else ''}
        {f'<p class="contact reveal">{esc(contact)}</p>' if contact else ''}
      </div>
      {image_html}
    </div>
  </div>
  {num}
</section>"""

    # ── fallback ─────────────────────────────────────────────────────────────
    return f'<section class="slide{inv}" id="s{idx}"><div class="slide-content"><p>Type inconnu : {esc(t)}</p></div>{num}</section>'


# ── Assemblage HTML complet ───────────────────────────────────────────────────
def build_html(slides: list[dict], font_b64: str, footer_cfg: dict, page_title: str, source_file: str, conference_dir: str, theme: str) -> str:
  total = len(slides)
  footer_html = render_footer(footer_cfg)
  slides_html = "\n".join(render_slide(s, i + 1, total, source_file, conference_dir) for i, s in enumerate(slides))
  theme_class = f"theme-{normalize_theme(theme)}"
  speaker_notes_json = json.dumps(
    [slide.get("notes", []) for slide in slides],
    ensure_ascii=False,
    separators=(",", ":"),
  ).replace(" ", "\\u0020").replace("</", "<\\/")

  return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{esc(page_title)}</title>
<link rel="stylesheet" href="https://api.fontshare.com/v2/css?f[]=satoshi@700,500,400&display=swap" />
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Caveat:wght@500;600;700&family=Nunito:wght@400;500;600;700;800&display=swap" />
<style>
@font-face {{
  font-family: "Publico Headline";
  font-style: normal;
  font-weight: 700;
  src: url("data:font/truetype;base64,{font_b64}") format("truetype");
}}

:root {{
  --corpo-blue:       #0000EF;
  --corpo-blue-mid:   #1414A0;
  --corpo-blue-light: #EEEEF8;
  --corpo-red:        #FF1721;
  --corpo-teal:       #5CC8E2;
  --heading-em-gradient: linear-gradient(110deg, #5CC8E2 0%, #FFFFFF 92%);
  --font-display: "Publico Headline", Georgia, serif;
  --font-body:    'Satoshi', system-ui, -apple-system, sans-serif;
  --title-size:   clamp(3rem, 8vw, 6rem);
  --h2-size:      clamp(2rem, 5vw, 3.5rem);
  --h3-size:      clamp(1.4rem, 2.8vw, 2.2rem);
  --body-size:    clamp(1.25rem, 2.5vw, 1.75rem);
  --small-size:   clamp(1.125rem, 2vw, 1.5rem);
  --slide-padding: clamp(2rem, 5vw, 4rem);
  --content-gap:   clamp(0.8rem, 2vh, 2rem);
  --slide-footer-height: clamp(1.35rem, 1.7vw, 1.65rem);
}}

*, *::before, *::after {{ margin: 0; padding: 0; box-sizing: border-box; }}

html, body {{
  height: 100%;
  overflow-x: hidden;
  overflow-y: scroll;
  scroll-snap-type: y mandatory;
  background: var(--corpo-blue);
  color: #fff;
  font-family: var(--font-body);
}}

/* ── Slides ──────────────────────────────────────────────────────────── */
.slide {{
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  scroll-snap-align: start;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--slide-padding);
  position: relative;
}}
.slide::before {{
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  opacity: 0.03;
  background-image:
    repeating-linear-gradient(0deg, rgba(255,255,255,0.05) 0 1px, transparent 1px 3px),
    repeating-linear-gradient(90deg, rgba(0,0,0,0.04) 0 1px, transparent 1px 4px);
}}
.slide-content {{ max-width: min(85vw, 1400px); width: 100%; position: relative; z-index: 1; }}

/* ── Typography ──────────────────────────────────────────────────────── */
h1 {{ font-family: var(--font-display); font-size: var(--title-size); line-height: 1.05; }}
h2 {{ font-family: var(--font-display); font-size: var(--h2-size); line-height: 1.1; margin-bottom: var(--content-gap); color: #fff; }}
h3 {{ font-size: var(--h3-size); font-weight: 700; }}
p  {{ font-size: var(--body-size); line-height: 1.55; opacity: 0.85; }}
.slide:not(.slide-title):not(.slide-closing):not(.slide-subtitle-break) h1 {{
  font-size: var(--h2-size);
  line-height: 1.1;
  margin-bottom: 0.1rem;
}}
.ext-link {{
  color: var(--corpo-teal);
  text-decoration: underline;
  text-decoration-thickness: 0.08em;
  text-underline-offset: 0.14em;
  font-weight: 700;
}}
.ext-link:hover {{ color: #ffffff; }}
.ext-link:focus-visible {{
  outline: 2px solid var(--corpo-teal);
  outline-offset: 2px;
  border-radius: 4px;
}}
.ext-link-icon {{
  display: inline-block;
  margin-left: 0.28em;
  font-size: 0.82em;
  vertical-align: text-top;
}}
.sr-only {{
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}}
.label {{
  font-size: var(--small-size);
  opacity: 0.5;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-bottom: 0.5rem;
}}
.tag {{
  display: inline-block;
  background: var(--corpo-red);
  color: #fff;
  font-size: var(--small-size);
  font-weight: 700;
  padding: 0.2em 0.75em;
  border-radius: 3px;
  margin-bottom: 1rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}
.inline-emph {{
  display: inline-block;
  padding: 0.08em 0.48em;
  margin: 0 0.03em;
  border-radius: 999px;
  background: rgba(92, 200, 226, 0.2);
  border: 1px solid rgba(92, 200, 226, 0.55);
  color: #eafaff;
  font-weight: 800;
  line-height: 1.2;
  box-shadow: inset 0 -1px 0 rgba(255, 255, 255, 0.12);
}}

/* ── Reveal ──────────────────────────────────────────────────────────── */
.reveal {{
  opacity: 0;
  transform: translateY(34px) scale(0.985);
  filter: blur(5px);
  transition:
    opacity 0.46s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.46s cubic-bezier(0.22, 1, 0.36, 1),
    filter 0.46s cubic-bezier(0.22, 1, 0.36, 1);
  will-change: opacity, transform, filter;
}}
.reveal.visible {{ opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }}
@media (scripting: none) {{
  .reveal {{ opacity: 1 !important; transform: none !important; filter: none !important; transition: none !important; }}
}}

/* ── Backgrounds ─────────────────────────────────────────────────────── */
.slide-title     {{ background: #0000EF; }}
.slide-title::after {{
  content: "";
  position: absolute; top: 0; right: 0;
  width: 40vw; height: 100%;
  background: linear-gradient(135deg, transparent 55%, rgba(255,23,33,0.06) 100%);
  pointer-events: none;
}}
.slide-agenda    {{ background: #080818; }}
.slide-text      {{ background: #080818; }}
.slide-stat      {{ background: #080818; }}
.slide-stats-row {{ background: #080818; }}
.slide-cards     {{ background: #080818; }}
.slide-quote     {{ background: #101046; }}
.slide-image     {{ background: #080818; }}
.slide-iframe    {{ background: #080818; }}
.slide-bio       {{ background: #0000EF; }}
.slide-subtitle-break {{ background: #101046; }}
.slide-closing   {{ background: #0000EF; }}

/* ── Subtitle transition ────────────────────────────────────────────── */
.slide-subtitle-break .slide-content {{
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 62vh;
}}
.slide-subtitle-break h1 {{
  font-size: clamp(3.2rem, 9vw, 6.8rem);
  max-width: 16ch;
  line-height: 1.03;
  text-wrap: balance;
}}
.slide-subtitle-break .slide-subtitle {{
  max-width: 52ch;
  margin-left: auto;
  margin-right: auto;
}}

/* ── Title slide ─────────────────────────────────────────────────────── */
.slide-title .subtitle {{
  margin-top: 1.25rem;
  max-width: 55ch;
  font-size: var(--body-size);
  opacity: 0.8;
}}
.slide-subtitle {{
  margin-top: 0.65rem;
  margin-bottom: 0.5rem;
  max-width: 70ch;
  font-size: clamp(1.35rem, 2.6vw, 2rem);
  font-weight: 600;
  opacity: 0.88;
  line-height: 1.35;
}}
.slide-title .speaker {{
  margin-top: 2.5rem;
  font-size: var(--small-size);
  opacity: 0.4;
}}

/* ── Agenda ──────────────────────────────────────────────────────────── */
.agenda-list {{
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: clamp(0.35rem, 1vh, 0.8rem);
}}
.agenda-list li {{
  display: flex;
  align-items: center;
  gap: 1.2rem;
  font-size: var(--body-size);
  opacity: 0.85;
}}
.agenda-num {{
  font-family: var(--font-display);
  font-size: clamp(1.5rem, 3vw, 2.5rem);
  color: var(--corpo-teal);
  min-width: 2.5ch;
  line-height: 1;
}}

/* ── Bullets ─────────────────────────────────────────────────────────── */
.bullets {{
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: clamp(0.35rem, 1vh, 0.8rem);
  margin-top: clamp(0.4rem, 1vh, 0.8rem);
}}
.bullets li {{
  display: block;
  font-size: var(--body-size);
  opacity: 0.85;
  line-height: 1.45;
}}
.bullets:not(.bullets-ordered) li::before {{
  content: "→";
  color: var(--corpo-teal);
  font-weight: 700;
  display: inline-block;
  margin-right: 0.55rem;
}}
.bullets.bullets-ordered {{
  list-style: none;
  counter-reset: item;
  padding-left: 0;
}}
.bullets.bullets-ordered li {{
  display: block;
  counter-increment: item;
}}
.bullets.bullets-ordered li::before {{
  content: counter(item, decimal-leading-zero) ".";
  color: var(--corpo-teal);
  font-weight: 800;
  display: inline-block;
  margin-right: 0.55rem;
}}
.content-text {{
  margin-top: 0.25rem;
  margin-bottom: 0.6rem;
  max-width: 70ch;
}}
.md-table-wrap {{
  width: 100%;
  max-width: min(100%, 1100px);
  overflow-x: auto;
  border: 1px solid rgba(255,255,255,0.2);
  border-radius: 12px;
  background: rgba(255,255,255,0.04);
}}
.md-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: clamp(0.95rem, 1.4vw, 1.1rem);
}}
.md-table th,
.md-table td {{
  padding: 0.55rem 0.75rem;
  text-align: left;
  border-bottom: 1px solid rgba(255,255,255,0.15);
  vertical-align: top;
}}
.md-table th {{
  color: var(--corpo-teal);
  font-weight: 700;
  background: rgba(255,255,255,0.06);
}}
.md-table tbody tr:last-child td {{
  border-bottom: none;
}}
.content-text .md-image {{
  display: block;
  max-width: min(100%, 1100px);
  max-height: 52vh;
  width: auto;
  height: auto;
  object-fit: contain;
  border-radius: 12px;
}}

/* ── Stat ────────────────────────────────────────────────────────────── */
.big-number {{
  font-family: var(--font-display);
  font-size: clamp(5rem, 15vw, 10rem);
  color: var(--corpo-red);
  line-height: 1;
}}
.stat-caption {{
  margin-top: 1rem;
  max-width: 55ch;
  margin-left: auto;
  margin-right: auto;
  text-align: center;
}}

/* ── Stats row ───────────────────────────────────────────────────────── */
.stat-row {{
  display: flex;
  gap: clamp(2rem, 6vw, 5rem);
  align-items: flex-end;
  margin-top: var(--content-gap);
  flex-wrap: wrap;
}}
.stat {{ text-align: center; }}
.stat-num {{
  font-family: var(--font-display);
  font-size: clamp(3rem, 7vw, 5.5rem);
  line-height: 1;
}}
.stat-label {{
  font-size: var(--small-size);
  opacity: 0.5;
  margin-top: 0.3rem;
}}

/* ── Cards ───────────────────────────────────────────────────────────── */
.cards-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(260px, 28vw), 1fr));
  gap: clamp(0.6rem, 1.2vw, 1.2rem);
  margin-top: var(--content-gap);
}}
.card {{
  background: #161616;
  border-left: 4px solid var(--corpo-red);
  padding: clamp(0.75rem, 1.2vw, 1.25rem);
  border-radius: 4px;
}}
.card h3 {{
  font-size: var(--small-size);
  font-weight: 700;
  color: var(--corpo-teal);
  margin-bottom: 0.35rem;
}}
.card p {{
  font-size: var(--small-size);
  opacity: 0.7;
  line-height: 1.4;
}}

/* ── Quote ───────────────────────────────────────────────────────────── */
blockquote {{
  font-family: var(--font-display);
  font-size: clamp(1.5rem, 3.5vw, 2.8rem);
  line-height: 1.3;
  max-width: 70ch;
  margin: 0 auto;
}}
blockquote::before {{ content: "\u201C"; color: var(--corpo-red); font-size: 1.2em; line-height: 0; vertical-align: -0.4em; margin-right: 0.1em; }}
blockquote::after  {{ content: "\u201D"; color: var(--corpo-red); font-size: 1.2em; line-height: 0; vertical-align: -0.4em; margin-left:  0.1em; }}
.quote-typewriter::after {{
  content: "";
  display: inline-block;
  width: 0.075em;
  height: 0.95em;
  margin-left: 0.08em;
  background: currentColor;
  opacity: 0;
  vertical-align: -0.08em;
}}
.quote-typewriter.typing::after {{
  opacity: 0.72;
  animation: tw-caret 0.56s steps(1, end) infinite;
}}
@keyframes tw-caret {{
  0%, 49% {{ opacity: 0.72; }}
  50%, 100% {{ opacity: 0.1; }}
}}
.quote-attr {{
  margin-top: 1.5rem;
  font-size: var(--small-size);
  opacity: 0.6;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
}}
.quote-attr strong {{ opacity: 1; color: var(--corpo-teal); }}
.role {{ font-style: italic; }}
.quote-copy-btn {{
  margin-top: 1rem;
  background: rgba(255,255,255,0.1);
  border: 1px solid rgba(255,255,255,0.28);
  color: #fff;
  font-size: clamp(0.8rem, 1.1vw, 0.95rem);
  padding: 0.42rem 0.8rem;
  border-radius: 999px;
  cursor: pointer;
  transition: background 120ms ease, border-color 120ms ease, transform 120ms ease;
}}
.quote-copy-btn:hover {{
  background: rgba(255,255,255,0.2);
  border-color: rgba(255,255,255,0.45);
}}
.quote-copy-btn:active {{ transform: scale(0.98); }}

/* ── Image ───────────────────────────────────────────────────────────── */
.slide-image .slide-content {{
  display: flex;
  flex-direction: column;
  align-items: stretch;
  max-width: min(84vw, 1320px);
}}
.slide-image .tag,
.slide-image h1,
.slide-image .slide-subtitle {{
  align-self: flex-start;
}}
.image-wrap {{
  width: 100%;
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.slide-image-frame {{
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 14px 40px rgba(0, 0, 0, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(0, 0, 0, 0.2);
}}
.slide-image-media {{
  width: min(76vw, 1240px);
  max-width: 100%;
  max-height: min(62vh, 620px);
  display: block;
  margin-left: auto;
  margin-right: auto;
  height: auto;
  object-fit: contain;
  border-radius: 14px;
}}
.image-caption {{
  margin-top: 0.7rem;
  font-size: var(--small-size);
  opacity: 0.72;
  text-align: center;
  max-width: min(80vw, 1100px);
}}
.image-missing {{
  border: 1px dashed rgba(255,255,255,0.35);
  padding: 1rem 1.2rem;
  border-radius: 8px;
  font-size: var(--small-size);
  opacity: 0.75;
  text-align: center;
  margin-left: auto;
  margin-right: auto;
}}

/* Iframe slide */
.slide-iframe-frame {{
  display: flex;
  align-items: stretch;
  justify-content: center;
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 14px 40px rgba(0,0,0,0.35);
  border: 1px solid rgba(255,255,255,0.18);
  background: rgba(0,0,0,0.2);
  width: min(76vw, 1240px);
  height: min(62vh, 620px);
}}
.slide-iframe-media {{
  width: 100%;
  height: 100%;
  display: block;
  border: none;
  border-radius: 14px;
  background: #fff;
}}
.slide-iframe-fullscreen {{
  box-sizing: border-box;
  padding: 3.5rem 30px var(--iframe-footer-height, var(--slide-footer-height));
  overflow: hidden;
}}
.slide-iframe-fullscreen .slide-content {{
  max-width: 100%;
  width: 100%;
  height: 100%;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
}}
.slide-iframe-fullscreen .fullscreen-content {{
  display: flex;
  width: 100%;
  height: 100%;
}}
.fullscreen-iframe-container {{
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.slide-iframe-fullscreen .slide-iframe-frame {{
  width: 100%;
  height: 100%;
  border-radius: 0;
  box-shadow: none;
  border: none;
  background: transparent;
}}
.slide-iframe-fullscreen .slide-iframe-media {{
  border-radius: 0;
}}

/* ── Code blocks ───────────────────────────────────────────────────── */
.code-block {{
  margin-top: clamp(0.4rem, 1.2vh, 1rem);
  width: 100%;
  max-width: min(100%, 1100px);
  border: 1px solid rgba(255,255,255,0.18);
  border-radius: 10px;
  background: #0a0a1c;
  box-shadow: 0 12px 34px rgba(0,0,0,0.35);
  overflow: hidden;
  position: relative;
}}
.code-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.32rem 0.55rem 0.32rem 0.85rem;
  background: rgba(255,255,255,0.05);
  border-bottom: 1px solid rgba(255,255,255,0.12);
}}
.code-lang {{
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--corpo-teal);
}}
.code-copy-btn {{
  border: 1px solid rgba(255,255,255,0.25);
  background: rgba(255,255,255,0.08);
  color: #fff;
  font-size: 0.72rem;
  font-weight: 700;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  cursor: pointer;
  transition: background 120ms ease, border-color 120ms ease, transform 120ms ease;
}}
.code-copy-btn:hover {{ background: rgba(255,255,255,0.18); border-color: rgba(255,255,255,0.45); }}
.code-copy-btn:active {{ transform: scale(0.96); }}
.code-copy-btn:focus-visible {{ outline: 2px solid var(--corpo-teal); outline-offset: 2px; }}
.code-scroll {{
  max-height: min(44vh, 460px);
  overflow: auto;
  overscroll-behavior: contain;
  padding: 0.85rem 1rem;
  font-size: clamp(0.78rem, 1.3vw, 1rem);
  line-height: 1.5;
}}
.code-scroll:focus-visible {{ outline: 2px solid var(--corpo-teal); outline-offset: -2px; }}
.code-scroll code {{
  display: block;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  white-space: pre;
  color: #c0caf5;
  background: transparent;
}}
.code-scroll::-webkit-scrollbar {{ width: 8px; height: 8px; }}
.code-scroll::-webkit-scrollbar-track {{ background: transparent; }}
.code-scroll::-webkit-scrollbar-thumb {{ background: rgba(92,200,226,0.35); border-radius: 4px; }}
.code-scroll-hint {{
  position: absolute;
  right: 0.55rem;
  bottom: 0.4rem;
  display: none;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #fff;
  background: rgba(255,23,33,0.9);
  padding: 0.18rem 0.55rem;
  border-radius: 999px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  pointer-events: none;
}}
.code-block.is-scrollable .code-scroll-hint {{ display: inline-flex; animation: code-hint-bounce 1.4s ease-in-out infinite; }}
.code-block.at-bottom .code-scroll-hint {{ display: none; }}
@keyframes code-hint-bounce {{
  0%, 100% {{ transform: translateY(0); }}
  50% {{ transform: translateY(3px); }}
}}

/* Coloration syntaxique (highlight.js, theme sombre corpo) */
.hljs {{ color: #c0caf5; background: transparent; }}
.hljs-comment, .hljs-quote {{ color: #565f89; font-style: italic; }}
.hljs-keyword, .hljs-selector-tag, .hljs-doctag {{ color: #5CC8E2; }}
.hljs-string, .hljs-regexp, .hljs-addition {{ color: #9ece6a; }}
.hljs-number, .hljs-literal, .hljs-deletion {{ color: #ff9e64; }}
.hljs-title, .hljs-title.function_, .hljs-section {{ color: #7aa2f7; }}
.hljs-title.class_, .hljs-type, .hljs-built_in {{ color: #bb9af7; }}
.hljs-attr, .hljs-attribute, .hljs-name, .hljs-selector-class, .hljs-selector-id {{ color: #73daca; }}
.hljs-variable, .hljs-template-variable, .hljs-selector-attr, .hljs-selector-pseudo {{ color: #e0af68; }}
.hljs-meta, .hljs-tag {{ color: #f7768e; }}
.hljs-symbol, .hljs-bullet, .hljs-link {{ color: #5CC8E2; }}
.hljs-emphasis {{ font-style: italic; }}
.hljs-strong {{ font-weight: 700; }}

/* ── Mermaid ────────────────────────────────────────────────────────── */
.mermaid-wrap {{
  width: 100%;
  height: min(58vh, 620px);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  margin-top: var(--content-gap);
  padding: clamp(1rem, 2vw, 2rem);
  border: 1px solid rgba(255,255,255,0.18);
  border-radius: 8px;
  background: rgba(255,255,255,0.05);
}}
.mermaid {{
  height: 100%;
  width: 100%;
  text-align: center;
  color: #fff;
  font-family: var(--font-body);
}}
.mermaid svg {{
  display: block;
  width: 100% !important;
  height: 100% !important;
  margin: auto;
  object-fit: contain;
}}

/* Fullscreen image mode */
.slide-image-fullscreen {{
  box-sizing: border-box;
  padding: 0 0 var(--slide-footer-height);
  overflow: hidden;
}}
.slide-image-fullscreen .slide-content {{
  max-width: 100%;
  width: 100%;
  height: 100%;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
}}
.slide-image-fullscreen .fullscreen-content {{
  display: flex;
  width: 100%;
  height: 100%;
}}
.fullscreen-image-container {{
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
}}
.slide-image-fullscreen .slide-image-frame {{
  width: 100%;
  height: 100%;
  border-radius: 0;
  box-shadow: none;
  border: none;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.slide-image-fullscreen .slide-image-media {{
  width: 100%;
  height: 100%;
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 0;
  display: block;
}}

/* ── Bio ─────────────────────────────────────────────────────────────── */
.slide-bio .slide-content {{
  max-width: min(88vw, 1400px);
}}
.bio-grid {{
  display: grid;
  grid-template-columns: minmax(260px, 0.9fr) minmax(0, 1.5fr);
  gap: clamp(1.5rem, 4vw, 4rem);
  align-items: center;
  min-height: min(68vh, 760px);
}}
.bio-visual {{
  display: flex;
  align-items: center;
  justify-content: center;
}}
.bio-media {{
  width: min(100%, 420px);
  aspect-ratio: 4 / 5;
  object-fit: cover;
  border-radius: 50% / 38%;
  border: 1px solid rgba(255,255,255,0.2);
  box-shadow: 0 20px 48px rgba(0,0,0,0.28);
  background: rgba(255,255,255,0.08);
}}
.bio-media-missing {{
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem;
  text-align: center;
  color: rgba(255,255,255,0.78);
  font-size: var(--small-size);
  border-style: dashed;
}}
.bio-copy {{
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}}
.slide-bio h1 {{
  color: var(--corpo-teal);
}}
.slide-bio .content-text,
.slide-bio .bullets {{
  max-width: 60ch;
}}

/* ── Closing ─────────────────────────────────────────────────────────── */
.slide-closing h1 {{ color: var(--corpo-teal); }}
.slide-closing .closing-layout {{
  min-height: 62vh;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.slide-closing .closing-copy {{
  text-align: center;
}}
.slide-closing-with-image .slide-content {{
  max-width: min(88vw, 1400px);
}}
.slide-closing-with-image .closing-layout {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: clamp(1.5rem, 5vw, 5rem);
}}
.closing-visual {{
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.closing-media {{
  display: block;
  width: 100%;
  max-height: min(68vh, 680px);
  object-fit: contain;
}}
.slide-closing .subtitle {{
  margin-top: 1.25rem;
  max-width: 55ch;
  font-size: var(--body-size);
  opacity: 0.75;
  margin-left: auto;
  margin-right: auto;
}}
.cta-link {{
  display: inline-block;
  margin-top: 1.5rem;
  font-size: var(--body-size);
  color: var(--corpo-red);
  font-weight: 700;
}}
.contact {{
  font-size: var(--small-size);
  opacity: 0.4;
  margin-top: 0.4rem;
}}

/* ── Slide counter ───────────────────────────────────────────────────── */
.slide-num {{
  position: absolute;
  top: 1rem;
  left: 1rem;
  font-size: 0.85rem;
  opacity: 0.25;
  z-index: 700;
}}

.slide-footer {{
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  min-height: var(--slide-footer-height);
  box-sizing: border-box;
  z-index: 600;
  background: #000;
  border-top: 1px solid rgba(255, 255, 255, 0.14);
  padding: 0.24rem 2rem calc(0.24rem + env(safe-area-inset-bottom));
  font-size: clamp(0.6rem, 0.75vw, 0.72rem);
  opacity: 0.56;
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 1rem;
  align-items: center;
  pointer-events: none;
  transition: opacity 160ms ease;
}}
.footer-left,
.footer-center,
.footer-right {{
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}}
.footer-center {{ text-align: center; }}
.footer-center {{ justify-self: center; }}
.footer-right {{ text-align: right; justify-self: end; }}

/* ── Menu TOC ───────────────────────────────────────────────────────── */
.top-controls {{
  position: fixed;
  top: 0.8rem;
  right: 1rem;
  display: flex;
  align-items: center;
  gap: 0.55rem;
  z-index: 950;
}}
#fs-hint {{
  font-size: 0.8rem;
  color: rgba(255,255,255,0.28);
  pointer-events: none;
}}
.toc-toggle,
.notes-toggle {{
  border: 1px solid rgba(255, 255, 255, 0.28);
  background: rgba(7, 7, 24, 0.78);
  color: #fff;
  border-radius: 999px;
  width: 2.25rem;
  height: 2.25rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 140ms ease, border-color 140ms ease, transform 140ms ease;
}}
.toc-toggle:hover,
.notes-toggle:hover {{
  background: rgba(17, 17, 42, 0.95);
  border-color: rgba(255, 255, 255, 0.48);
}}
.toc-toggle:active,
.notes-toggle:active {{ transform: scale(0.97); }}
.toc-toggle:focus-visible,
.notes-toggle:focus-visible {{
  outline: 2px solid var(--corpo-teal);
  outline-offset: 2px;
}}
.notes-toggle {{
  width: auto;
  padding: 0 0.7rem;
  font-size: 0.78rem;
  font-weight: 700;
}}
.toc-toggle-icon {{
  width: 1rem;
  height: 0.75rem;
  position: relative;
  display: block;
}}
.toc-toggle-icon::before,
.toc-toggle-icon::after,
.toc-toggle-icon span {{
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  height: 2px;
  border-radius: 2px;
  background: currentColor;
}}
.toc-toggle-icon::before {{ top: 0; }}
.toc-toggle-icon span {{ top: 50%; transform: translateY(-50%); }}
.toc-toggle-icon::after {{ bottom: 0; }}

.toc-backdrop {{
  position: fixed;
  inset: 0;
  background: rgba(2, 2, 14, 0.42);
  backdrop-filter: blur(2px);
  z-index: 900;
}}
.toc-panel,
.notes-panel {{
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(36rem, 86vw);
  background: linear-gradient(180deg, rgba(11, 11, 34, 0.98), rgba(4, 4, 18, 0.98));
  border-left: 1px solid rgba(255, 255, 255, 0.18);
  box-shadow: -18px 0 42px rgba(0, 0, 0, 0.45);
  z-index: 930;
  transform: translateX(100%);
  transition: transform 210ms cubic-bezier(0.22, 1, 0.36, 1);
  display: flex;
  flex-direction: column;
}}
.toc-panel.open,
.notes-panel.open {{ transform: translateX(0); }}
.toc-header {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1rem 0.85rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.14);
}}
.toc-title {{
  font-size: 0.9rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  opacity: 0.8;
}}
.toc-close {{
  border: 1px solid rgba(255, 255, 255, 0.26);
  background: transparent;
  color: #fff;
  border-radius: 999px;
  width: 1.9rem;
  height: 1.9rem;
  font-size: 1.1rem;
  line-height: 1;
  cursor: pointer;
}}
.toc-close:focus-visible {{
  outline: 2px solid var(--corpo-teal);
  outline-offset: 2px;
}}
.toc-list {{
  list-style: none;
  padding: 0.5rem;
  margin: 0;
  overflow: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}}
.toc-group {{
  display: flex;
  flex-direction: column;
  gap: 0.16rem;
}}
.toc-sublist {{
  list-style: none;
  margin: 0;
  margin-left: 1rem;
  padding-left: 0.65rem;
  border-left: 1px solid rgba(255, 255, 255, 0.14);
  display: flex;
  flex-direction: column;
  gap: 0.16rem;
}}
.toc-item-btn {{
  width: 100%;
  border: 0;
  background: transparent;
  color: rgba(255, 255, 255, 0.9);
  text-align: left;
  display: grid;
  grid-template-columns: 3ch 1fr;
  gap: 0.7rem;
  align-items: start;
  padding: 0.46rem 0.55rem;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.93rem;
  line-height: 1.32;
}}
.toc-item-btn.toc-main {{
  font-weight: 700;
}}
.toc-item-btn.toc-sub {{
  font-size: 0.88rem;
  color: rgba(255, 255, 255, 0.86);
}}
.toc-item-btn:hover {{
  background: rgba(92, 200, 226, 0.14);
}}
.toc-item-btn:focus-visible {{
  outline: 2px solid var(--corpo-teal);
  outline-offset: 1px;
}}
.toc-item-btn.active {{
  background: rgba(255, 23, 33, 0.2);
  color: #fff;
}}
.toc-item-num {{
  opacity: 0.64;
  font-variant-numeric: tabular-nums;
}}
.toc-item-title {{
  white-space: normal;
  text-wrap: pretty;
}}
.notes-content {{
  flex: 1;
  overflow: auto;
  padding: 1rem;
  color: rgba(255, 255, 255, 0.9);
  font-size: 1rem;
  line-height: 1.5;
  white-space: pre-wrap;
}}

/* ── Breakpoints hauteur ─────────────────────────────────────────────── */
@media (max-height: 700px) {{
  :root {{ --title-size: clamp(2.5rem,7vw,5rem); --h2-size: clamp(1.75rem,4vw,3rem); }}
}}
@media (max-height: 600px) {{
  :root {{ --slide-padding: clamp(1rem, 3vw, 2rem); --content-gap: clamp(0.4rem, 1vh, 0.8rem); }}
}}
@media (max-height: 500px) {{
  :root {{ --body-size: clamp(1rem, 2vw, 1.4rem); }}
}}

@media (max-width: 900px) {{
  :root {{ --iframe-footer-height: 3.5rem; }}
  .slide-closing-with-image .closing-layout {{
    gap: clamp(0.75rem, 3vw, 1.5rem);
  }}
  .slide-closing-with-image .closing-media {{
    max-height: min(58vh, 480px);
  }}
  .bio-grid {{
    grid-template-columns: 1fr;
    min-height: auto;
  }}
  .bio-visual {{
    justify-content: flex-start;
  }}
  .bio-media {{
    width: min(62vw, 320px);
  }}
  .slide-footer {{
    grid-template-columns: 1fr;
    gap: 0.2rem;
    padding: 0.2rem 1rem calc(0.2rem + env(safe-area-inset-bottom));
  }}
  .footer-center,
  .footer-right {{ text-align: left; }}
  .slide-num {{ top: 0.8rem; left: 0.7rem; }}
  .top-controls {{ right: 0.7rem; top: 0.7rem; gap: 0.4rem; }}
  #fs-hint {{ font-size: 0.72rem; }}
  .toc-panel,
  .notes-panel {{ width: min(38rem, 94vw); }}
}}

/* ── Inverse (fond clair) ────────────────────────────────────────────── */
.slide-inverse,
.slide-inverse.slide-title,
.slide-inverse.slide-agenda,
.slide-inverse.slide-text,
.slide-inverse.slide-stat,
.slide-inverse.slide-stats-row,
.slide-inverse.slide-cards,
.slide-inverse.slide-quote,
.slide-inverse.slide-image,
.slide-inverse.slide-bio,
.slide-inverse.slide-subtitle-break,
.slide-inverse.slide-closing {{
  background: var(--corpo-blue-light) !important;
  color: #0a0a1e;
}}
.slide-inverse::before {{
  background-image:
    repeating-linear-gradient(0deg, rgba(0,0,139,0.05) 0 1px, transparent 1px 3px),
    repeating-linear-gradient(90deg, rgba(0,0,0,0.04) 0 1px, transparent 1px 4px);
}}
.slide-inverse::after {{ background: none !important; }}
.slide-inverse h1,
.slide-inverse h2,
.slide-inverse h3 {{
  color: #0a0a1e;
}}
.slide-inverse p,
.slide-inverse li {{
  color: #0a0a1e;
}}
.slide-inverse .slide-subtitle {{
  color: #0a0a1e;
  opacity: 0.88;
}}
.slide-inverse .tag {{
  background: var(--corpo-red);
  color: #fff;
}}
.slide-inverse .card {{
  background: rgba(0, 0, 143, 0.06);
  border-left-color: var(--corpo-red);
}}
.slide-inverse .card h3 {{ color: var(--corpo-blue); }}
.slide-inverse .card p {{ color: #0a0a1e; opacity: 0.8; }}
.slide-inverse .agenda-num {{ color: var(--corpo-blue); }}
.slide-inverse .bullets:not(.bullets-ordered) li::before,
.slide-inverse .bullets.bullets-ordered li::before {{
  color: var(--corpo-blue);
}}
.slide-inverse .big-number {{ color: var(--corpo-red); }}
.slide-inverse .stat-label-heading {{ color: #0a0a1e !important; }}
.slide-inverse .stat-num {{ color: var(--corpo-blue); }}
.slide-inverse .stat-label {{ color: #0a0a1e; }}
.slide-inverse blockquote {{ color: #0a0a1e; }}
.slide-inverse .quote-attr strong {{ color: var(--corpo-blue); }}
.slide-inverse .quote-copy-btn {{
  background: rgba(0,0,143,0.1);
  border-color: rgba(0,0,143,0.3);
  color: #0a0a1e;
}}
.slide-inverse .quote-copy-btn:hover {{
  background: rgba(0,0,143,0.2);
  border-color: rgba(0,0,143,0.45);
}}
.slide-inverse .ext-link {{ color: var(--corpo-blue); }}
.slide-inverse .ext-link:hover {{ color: #0a0a1e; }}
.slide-inverse .inline-emph {{
  background: rgba(0,0,143,0.1);
  border-color: rgba(0,0,143,0.3);
  color: var(--corpo-blue);
  box-shadow: inset 0 -1px 0 rgba(0,0,0,0.08);
}}
.slide-inverse.slide-closing h1 {{ color: var(--corpo-blue); }}
.slide-inverse .slide-image-frame {{
  border-color: rgba(0,0,0,0.12);
  box-shadow: 0 14px 40px rgba(0,0,0,0.15);
  background: rgba(255,255,255,0.5);
}}
.slide-inverse .mermaid-wrap {{
  border-color: rgba(0,0,0,0.16);
  background: rgba(255,255,255,0.55);
}}
.slide-inverse .bio-media {{
  border-color: rgba(0,0,0,0.12);
  box-shadow: 0 20px 48px rgba(0,0,0,0.12);
  background: rgba(255,255,255,0.42);
}}
.slide-inverse .bio-media-missing {{
  color: #0a0a1e;
}}
.slide-inverse.slide-bio h1 {{ color: var(--corpo-blue); }}
.slide-inverse .image-caption {{ color: #0a0a1e; }}
.slide-inverse .image-missing {{
  border-color: rgba(0,0,0,0.25);
  color: #0a0a1e;
}}
.slide-inverse .slide-num {{ color: #0a0a1e; }}
.slide-inverse .code-block {{
  border-color: rgba(0,0,0,0.22);
  box-shadow: 0 12px 34px rgba(0,0,0,0.18);
}}

body.theme-corail {{
  --corail-ink: #243447;
  --corail-paper: #fffaf1;
  --corail-coral: #ff6b5f;
  --corail-mint: #b8eedc;
  --corail-sky: #b9e1ff;
  --corail-yellow: #ffd166;
  --font-display: "Caveat", "Segoe Print", "Bradley Hand", cursive;
  --font-body: "Nunito", "Avenir Next", sans-serif;
  --corpo-blue: var(--corail-coral);
  --corpo-blue-mid: #e85d52;
  --corpo-blue-light: #e8f5ff;
  --corpo-red: var(--corail-coral);
  --corpo-teal: #159a83;
  --heading-em-gradient: linear-gradient(110deg, var(--corail-coral) 0%, var(--corail-teal) 92%);
  background: var(--corail-paper);
  color: var(--corail-ink);
}}
body.theme-corail .slide {{
  align-items: center;
  justify-content: flex-start;
  padding: clamp(4.5rem, 8vh, 6rem) clamp(1.25rem, 4vw, 4rem);
}}
body.theme-corail .slide::before {{
  opacity: 0.22;
  background-image:
    radial-gradient(circle at 12% 18%, rgba(255, 107, 95, 0.17) 0 0.35rem, transparent 0.4rem),
    radial-gradient(circle at 87% 78%, rgba(21, 154, 131, 0.15) 0 0.45rem, transparent 0.5rem);
  background-size: 13rem 13rem, 17rem 17rem;
}}
body.theme-corail .slide:not(.slide-image-fullscreen):not(.slide-iframe-fullscreen) .slide-content {{
  max-width: min(92vw, 1500px);
  margin-inline: auto;
}}
body.theme-corail .slide-image-fullscreen,
body.theme-corail .slide-image-fullscreen {{
  padding: 0 0 var(--slide-footer-height);
}}
body.theme-corail .slide-iframe-fullscreen {{
  padding: 3.5rem 30px max(2rem, var(--iframe-footer-height, var(--slide-footer-height)));
}}
body.theme-corail h1,
body.theme-corail h2,
body.theme-corail h3,
body.theme-corail blockquote,
body.theme-corail .big-number,
body.theme-corail .agenda-num,
body.theme-corail .stat-num {{
  letter-spacing: 0;
}}
body.theme-corail h1,
body.theme-corail h2 {{
  color: var(--corail-ink);
  line-height: 1.04;
}}
body.theme-corail p,
body.theme-corail li {{ color: var(--corail-ink); }}
body.theme-corail .slide:not(.slide-title):not(.slide-closing):not(.slide-subtitle-break) h1 {{
  font-size: clamp(2.75rem, 6.5vh, 5.5rem);
  margin-bottom: clamp(1.75rem, 4vh, 3.5rem);
}}
body.theme-corail .slide-title h1 {{
  font-size: clamp(4rem, 9vw, 7rem);
  line-height: 0.98;
  max-width: 15ch;
}}
body.theme-corail .slide-title .subtitle,
body.theme-corail .slide-subtitle {{
  margin-top: clamp(1rem, 2vh, 1.75rem);
}}
body.theme-corail .slide-title,
body.theme-corail .slide-bio,
body.theme-corail .slide-closing {{
  background: var(--corail-coral);
  color: #fff;
}}
body.theme-corail .slide-title::after {{
  width: 46vw;
  background: linear-gradient(135deg, transparent 35%, rgba(255, 209, 102, 0.52) 36% 48%, transparent 49% 58%, rgba(184, 238, 220, 0.5) 59% 72%, transparent 73%);
}}
body.theme-corail .slide-agenda,
body.theme-corail .slide-text,
body.theme-corail .slide-stat,
body.theme-corail .slide-stats-row,
body.theme-corail .slide-cards,
body.theme-corail .slide-image,
body.theme-corail .slide-iframe {{
  background: var(--corail-paper);
  color: var(--corail-ink);
}}
body.theme-corail .slide-subtitle-break,
body.theme-corail .slide-quote {{
  background: var(--corail-mint);
  color: var(--corail-ink);
}}
body.theme-corail .tag {{
  background: var(--corail-yellow);
  color: var(--corail-ink);
  border-radius: 999px;
  transform: rotate(-2deg);
  letter-spacing: 0.04em;
  box-shadow: 3px 4px 0 rgba(36, 52, 71, 0.12);
}}
body.theme-corail .slide-title h1,
body.theme-corail .slide-title h2,
body.theme-corail .slide-title p,
body.theme-corail .slide-bio h1,
body.theme-corail .slide-bio h2,
body.theme-corail .slide-bio p,
body.theme-corail .slide-closing h1,
body.theme-corail .slide-closing h2,
body.theme-corail .slide-closing p {{ color: #fff; }}
body.theme-corail .slide-title .speaker,
body.theme-corail .slide-closing .contact {{ opacity: 0.78; }}
body.theme-corail .slide-subtitle-break .slide-content {{ min-height: 58vh; }}
body.theme-corail .slide-subtitle-break h1 {{ max-width: 18ch; }}
body.theme-corail .agenda-list li {{ opacity: 1; }}
body.theme-corail .agenda-num,
body.theme-corail .bullets:not(.bullets-ordered) li::before,
body.theme-corail .bullets.bullets-ordered li::before {{ color: var(--corail-coral); }}
body.theme-corail .card {{
  background: #fff;
  border: 2px solid var(--corail-sky);
  border-left: 8px solid var(--corail-coral);
  border-radius: 18px 7px 18px 7px;
  box-shadow: 5px 6px 0 rgba(36, 52, 71, 0.1);
  transform: rotate(-0.7deg);
}}
body.theme-corail .card:nth-child(even) {{
  border-left-color: var(--corail-yellow);
  transform: rotate(0.7deg);
}}
body.theme-corail .card h3 {{ color: var(--corail-ink); }}
body.theme-corail .card p {{ color: var(--corail-ink); opacity: 0.76; }}
body.theme-corail .big-number {{ color: var(--corail-coral); }}
body.theme-corail .stat-label {{ color: var(--corail-ink); opacity: 0.64; }}
body.theme-corail .stat-num {{ color: var(--corail-coral) !important; }}
body.theme-corail blockquote::before,
body.theme-corail blockquote::after {{ color: var(--corail-coral); }}
body.theme-corail .quote-attr strong {{ color: var(--corail-coral); }}
body.theme-corail .quote-copy-btn,
body.theme-corail .code-copy-btn {{
  background: var(--corail-yellow);
  border-color: var(--corail-ink);
  color: var(--corail-ink);
}}
body.theme-corail .inline-emph {{
  background: var(--corail-sky);
  border-color: transparent;
  color: var(--corail-ink);
  box-shadow: none;
}}
body.theme-corail .ext-link {{ color: var(--corail-coral); }}
body.theme-corail .slide-image-frame,
body.theme-corail .slide-iframe-frame,
body.theme-corail .mermaid-wrap {{
  border-color: rgba(36, 52, 71, 0.16);
  background: rgba(255, 255, 255, 0.58);
  box-shadow: 8px 10px 0 rgba(36, 52, 71, 0.1);
}}
body.theme-corail .content-table {{
  width: 100%;
  max-width: none;
}}
body.theme-corail .md-table-wrap {{
  width: 100%;
  max-width: none;
  background: #f4f5f3;
  border: 1px solid rgba(36, 52, 71, 0.2);
  border-radius: 12px;
  box-shadow: 8px 10px 0 rgba(36, 52, 71, 0.1);
  overflow: hidden;
}}
body.theme-corail .md-table th,
body.theme-corail .md-table td {{
  border-right: 1px solid rgba(36, 52, 71, 0.1);
  border-bottom: 1px solid rgba(36, 52, 71, 0.12);
}}
body.theme-corail .md-table th:last-child,
body.theme-corail .md-table td:last-child {{ border-right: 0; }}
body.theme-corail .md-table tbody tr:last-child td {{ border-bottom: 0; }}
body.theme-corail .md-table th {{
  color: var(--corail-ink);
  background: #eaeeeb;
}}
body.theme-corail .md-table td {{ color: var(--corail-ink); }}
body.theme-corail .code-block {{
  background: #243447;
  border-color: rgba(36, 52, 71, 0.22);
  box-shadow: 8px 10px 0 rgba(36, 52, 71, 0.12);
}}
body.theme-corail .code-lang {{ color: var(--corail-yellow); }}
body.theme-corail .slide-footer {{
  min-height: clamp(1.7rem, 2.7vh, 2rem);
  padding: 0 clamp(1.25rem, 4vw, 4rem);
  font-size: clamp(0.75rem, 0.9vw, 0.9rem);
  background: rgba(242, 157, 46, 0.6);
  border-top: 0;
  color: var(--corail-ink);
  opacity: 1;
  align-items: center;
}}
body.theme-corail .toc-toggle,
body.theme-corail .notes-toggle {{
  background: var(--corail-ink);
  border-color: rgba(255,255,255,0.55);
}}
body.theme-corail .toc-panel,
body.theme-corail .notes-panel {{
  background: var(--corail-paper);
  border-left-color: rgba(36, 52, 71, 0.18);
  color: var(--corail-ink);
}}
body.theme-corail .toc-title,
body.theme-corail .toc-item-btn,
body.theme-corail .notes-content {{ color: var(--corail-ink); }}
body.theme-corail .toc-item-btn:hover {{ background: rgba(185, 225, 255, 0.55); }}
body.theme-corail .toc-item-btn.active {{ background: rgba(255, 209, 102, 0.55); }}
body.theme-corail .slide-inverse,
body.theme-corail .slide-inverse.slide-title,
body.theme-corail .slide-inverse.slide-agenda,
body.theme-corail .slide-inverse.slide-text,
body.theme-corail .slide-inverse.slide-stat,
body.theme-corail .slide-inverse.slide-stats-row,
body.theme-corail .slide-inverse.slide-cards,
body.theme-corail .slide-inverse.slide-quote,
body.theme-corail .slide-inverse.slide-image,
body.theme-corail .slide-inverse.slide-bio,
body.theme-corail .slide-inverse.slide-subtitle-break,
body.theme-corail .slide-inverse.slide-closing {{
  background: #e8f5ff !important;
  color: var(--corail-ink);
}}
body.theme-corail .slide-inverse h1,
body.theme-corail .slide-inverse h2,
body.theme-corail .slide-inverse h3,
body.theme-corail .slide-inverse p,
body.theme-corail .slide-inverse li {{ color: var(--corail-ink); }}
body.theme-corail .slide-inverse .tag {{ background: var(--corail-yellow); color: var(--corail-ink); }}
body.theme-corail .slide-inverse .card {{ background: rgba(255,255,255,0.72); }}
body.theme-corail .slide-inverse .slide-title::after {{ display: none; }}

/* ── Heading emphasis ───────────────────────────────────────────────── */
h1 em,
h2 em,
h3 em,
.slide-subtitle em,
.subtitle em {{
  background-image: var(--heading-em-gradient);
  background-clip: text;
  -webkit-background-clip: text;
  color: transparent;
  -webkit-text-fill-color: transparent;
}}
.slide-inverse h1 em,
.slide-inverse h2 em,
.slide-inverse h3 em,
.slide-inverse .slide-subtitle em,
.slide-inverse .subtitle em {{
  --heading-em-gradient: linear-gradient(110deg, var(--corpo-blue) 0%, var(--corpo-teal) 92%);
}}
body.theme-corail .slide-inverse h1 em,
body.theme-corail .slide-inverse h2 em,
body.theme-corail .slide-inverse h3 em,
body.theme-corail .slide-inverse .slide-subtitle em,
body.theme-corail .slide-inverse .subtitle em {{
  --heading-em-gradient: linear-gradient(110deg, var(--corail-coral) 0%, var(--corail-teal, #159a83) 92%);
}}

/* ── Print ───────────────────────────────────────────────────────────── */
@media print {{
  html, body {{ overflow: visible; scroll-snap-type: none; -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .slide {{ page-break-after: always; height: auto; min-height: 100vh; overflow: visible; scroll-snap-align: none; }}
  .slide::before {{ display: none !important; }}
  .top-controls,
  .toc-backdrop,
  .toc-panel,
  .notes-panel {{ display: none !important; }}
  @page {{ size: landscape; margin: 0; }}
  * {{ animation: none !important; transition: none !important; }}
  .reveal {{ opacity: 1 !important; transform: none !important; filter: none !important; }}
  .code-scroll {{ max-height: none; overflow: visible; }}
  .code-scroll-hint {{ display: none !important; }}
}}
</style>
</head>
<body class="{theme_class}">

<div class="top-controls" data-no-nav="true">
  <div id="fs-hint">F — Plein écran &nbsp;·&nbsp; ↑↓ Naviguer &nbsp;·&nbsp; M — Menu</div>
  <button type="button" id="notes-toggle" class="notes-toggle" aria-controls="notes-panel" aria-expanded="false">Notes</button>
  <button type="button" id="toc-toggle" class="toc-toggle" aria-label="Ouvrir le menu des slides" aria-controls="toc-panel" aria-expanded="false">
    <span class="toc-toggle-icon"><span></span></span>
  </button>
</div>

<div id="toc-backdrop" class="toc-backdrop" hidden data-no-nav="true"></div>
<aside id="toc-panel" class="toc-panel" aria-hidden="true" data-no-nav="true">
  <div class="toc-header">
    <strong class="toc-title">Table des matieres</strong>
    <button type="button" id="toc-close" class="toc-close" aria-label="Fermer le menu">×</button>
  </div>
  <ol id="toc-list" class="toc-list"></ol>
</aside>
<aside id="notes-panel" class="notes-panel" aria-hidden="true" data-no-nav="true">
  <div class="toc-header">
    <strong class="toc-title">Notes intervenant</strong>
    <button type="button" id="notes-close" class="toc-close" aria-label="Fermer les notes">×</button>
  </div>
  <div id="notes-content" class="notes-content"></div>
</aside>

{footer_html}

{slides_html}

<script type="module">
import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";

mermaid.initialize({{
  startOnLoad: false,
  securityLevel: "strict",
  htmlLabels: false,
  theme: "base",
  themeVariables: {{
    background: "#080818",
    primaryColor: "#1414A0",
    primaryTextColor: "#FFFFFF",
    primaryBorderColor: "#5CC8E2",
    lineColor: "#5CC8E2",
    secondaryColor: "#101046",
    tertiaryColor: "#161616",
    fontFamily: "Satoshi, system-ui, sans-serif"
  }},
  flowchart: {{
    useMaxWidth: true,
    wrappingWidth: 360
  }}
}});

await mermaid.run({{ nodes: document.querySelectorAll(".mermaid") }});
</script>

<script src="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.11.1/build/highlight.min.js"></script>

<script>
// Navigation helpers
const slides = Array.from(document.querySelectorAll('.slide'));
const footerEl = document.querySelector('.slide-footer');
const tocToggleBtn = document.querySelector('#toc-toggle');
const tocPanelEl = document.querySelector('#toc-panel');
const tocListEl = document.querySelector('#toc-list');
const tocBackdropEl = document.querySelector('#toc-backdrop');
const tocCloseBtn = document.querySelector('#toc-close');
const notesToggleBtn = document.querySelector('#notes-toggle');
const notesPanelEl = document.querySelector('#notes-panel');
const notesContentEl = document.querySelector('#notes-content');
const notesCloseBtn = document.querySelector('#notes-close');
const speakerNotes = {speaker_notes_json};
let _currentIdx = 0;
let _activeRevealIdx = -1;
let _revealTimer = 0;
let _typewriterRun = 0;
let _tocButtonsBySlide = new Map();

function slideMainTitle(slide, idx) {{
  const titleEl = slide ? slide.querySelector('h1') : null;
  const subtitleEl = slide ? slide.querySelector('.slide-subtitle') : null;
  const tagEl = slide ? slide.querySelector('.tag') : null;
  const raw = (titleEl?.textContent || subtitleEl?.textContent || tagEl?.textContent || '').trim();
  if (raw) return raw;
  return `Slide ${{idx + 1}}`;
}}

function slideSubTitle(slide, idx) {{
  const subtitleEl = slide ? slide.querySelector('.slide-subtitle, .subtitle') : null;
  const raw = (subtitleEl?.textContent || '').trim();
  if (raw) return raw;
  return slideMainTitle(slide, idx);
}}

function setTocActive(idx) {{
  if (!_tocButtonsBySlide.size) return;

  const allButtons = new Set();
  _tocButtonsBySlide.forEach(btns => {{
    btns.forEach(btn => allButtons.add(btn));
  }});
  allButtons.forEach(btn => {{
    btn.classList.remove('active');
    btn.setAttribute('aria-current', 'false');
  }});

  const current = _tocButtonsBySlide.get(idx) || [];
  current.forEach(btn => {{
    btn.classList.add('active');
    btn.setAttribute('aria-current', 'true');
  }});
}}

function openToc() {{
  if (!tocPanelEl) return;
  tocPanelEl.classList.add('open');
  tocPanelEl.setAttribute('aria-hidden', 'false');
  if (tocBackdropEl) tocBackdropEl.hidden = false;
  if (tocToggleBtn) tocToggleBtn.setAttribute('aria-expanded', 'true');
}}

function closeToc() {{
  if (!tocPanelEl) return;
  tocPanelEl.classList.remove('open');
  tocPanelEl.setAttribute('aria-hidden', 'true');
  if (tocBackdropEl) tocBackdropEl.hidden = true;
  if (tocToggleBtn) tocToggleBtn.setAttribute('aria-expanded', 'false');
}}

function toggleToc() {{
  if (!tocPanelEl) return;
  if (tocPanelEl.classList.contains('open')) closeToc();
  else openToc();
}}

function renderSpeakerNotes(idx) {{
  if (!notesContentEl) return;
  const notes = speakerNotes[idx] || [];
  notesContentEl.textContent = notes.length ? notes.join("\n\n") : "Aucune note pour cette slide.";
}}

function openNotes() {{
  if (!notesPanelEl) return;
  notesPanelEl.classList.add('open');
  notesPanelEl.setAttribute('aria-hidden', 'false');
  if (tocBackdropEl) tocBackdropEl.hidden = false;
  if (notesToggleBtn) notesToggleBtn.setAttribute('aria-expanded', 'true');
}}

function closeNotes() {{
  if (!notesPanelEl) return;
  notesPanelEl.classList.remove('open');
  notesPanelEl.setAttribute('aria-hidden', 'true');
  if (tocBackdropEl) tocBackdropEl.hidden = true;
  if (notesToggleBtn) notesToggleBtn.setAttribute('aria-expanded', 'false');
}}

function toggleNotes() {{
  if (!notesPanelEl) return;
  if (notesPanelEl.classList.contains('open')) closeNotes();
  else openNotes();
}}

function buildToc() {{
  if (!tocListEl) return;
  tocListEl.innerHTML = '';
  _tocButtonsBySlide = new Map();

  const mainTitles = slides.map((slide, idx) => slideMainTitle(slide, idx));

  function registerButtonForSlide(slideIdx, btn) {{
    const entry = _tocButtonsBySlide.get(slideIdx) || [];
    entry.push(btn);
    _tocButtonsBySlide.set(slideIdx, entry);
  }}

  function createTocButton(slideIdx, titleText, extraClass) {{
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `toc-item-btn ${{extraClass}}`.trim();
    btn.dataset.slideIndex = String(slideIdx);
    btn.setAttribute('aria-label', `Aller au slide ${{slideIdx + 1}}`);

    const num = document.createElement('span');
    num.className = 'toc-item-num';
    num.textContent = String(slideIdx + 1).padStart(2, '0');

    const title = document.createElement('span');
    title.className = 'toc-item-title';
    title.textContent = titleText;

    btn.appendChild(num);
    btn.appendChild(title);

    btn.addEventListener('click', e => {{
      e.preventDefault();
      e.stopPropagation();
      goToIndex(slideIdx, true);
      closeToc();
    }});

    registerButtonForSlide(slideIdx, btn);
    return btn;
  }}

  let i = 0;
  while (i < slides.length) {{
    const groupTitle = mainTitles[i];
    let j = i + 1;
    while (j < slides.length && mainTitles[j] === groupTitle) {{
      j += 1;
    }}

    const groupSize = j - i;
    if (groupSize >= 2) {{
      const groupLi = document.createElement('li');
      groupLi.className = 'toc-group';

      const groupMainBtn = createTocButton(i, groupTitle, 'toc-main');
      groupLi.appendChild(groupMainBtn);

      const subList = document.createElement('ol');
      subList.className = 'toc-sublist';

      for (let k = i; k < j; k++) {{
        const subLi = document.createElement('li');
        const subBtn = createTocButton(k, slideSubTitle(slides[k], k), 'toc-sub');
        subLi.appendChild(subBtn);
        subList.appendChild(subLi);

        // Un slide groupe active aussi l'entree principale du groupe.
        registerButtonForSlide(k, groupMainBtn);
      }}

      groupLi.appendChild(subList);
      tocListEl.appendChild(groupLi);
    }} else {{
      const li = document.createElement('li');
      li.appendChild(createTocButton(i, groupTitle, 'toc-main'));
      tocListEl.appendChild(li);
    }}

    i = j;
  }}
}}

function runQuoteTypewriter(slide, immediate = false) {{
  const quoteEl = slide ? slide.querySelector('.quote-typewriter') : null;
  if (!quoteEl) return;

  const fullText = String(quoteEl.dataset.typewriterText || quoteEl.textContent || '');
  _typewriterRun += 1;
  const runId = _typewriterRun;

  quoteEl.classList.remove('typing');

  if (immediate) {{
    quoteEl.textContent = fullText;
    return;
  }}

  quoteEl.textContent = '';
  quoteEl.classList.add('typing');

  const n = fullText.length;
  if (!n) {{
    quoteEl.classList.remove('typing');
    return;
  }}

  const maxTotal = 1500;
  const base = n > 320 ? 1.8 : n > 220 ? 2.4 : n > 140 ? 3.1 : n > 90 ? 4.1 : 5.0;
  let i = 0;
  let elapsed = 0;

  function tick() {{
    if (runId !== _typewriterRun) return;

    quoteEl.textContent += fullText[i] || '';
    i += 1;

    if (i >= n) {{
      quoteEl.classList.remove('typing');
      return;
    }}

    const typedChar = fullText[i - 1];
    let delay = typedChar === ' '
      ? Math.max(1, base * 0.28)
      : base * (0.65 + Math.random() * 0.95);

    elapsed += delay;
    const remaining = n - i;
    const minFuture = remaining * Math.max(1, base * 0.52);
    if (elapsed + minFuture > maxTotal) {{
      delay = Math.max(1, (maxTotal - elapsed) / Math.max(1, remaining));
    }}

    window.setTimeout(tick, Math.max(1, Math.round(delay)));
  }}

  tick();
}}

function animateSlideReveal(slide, immediate = false) {{
  if (!slide) return;
  const items = Array.from(slide.querySelectorAll('.reveal'));
  if (!items.length) return;

  items.forEach(el => {{
    el.classList.remove('visible');
    el.style.transitionDelay = '0ms';
  }});

  requestAnimationFrame(() => {{
    items.forEach((el, idx) => {{
      const delay = immediate ? 0 : idx * 95;
      el.style.transitionDelay = `${{delay}}ms`;
      el.classList.add('visible');
    }});
  }});

  const quoteEl = slide.querySelector('.quote-typewriter');
  if (quoteEl) {{
    const quoteIdx = Math.max(0, items.indexOf(quoteEl));
    const twStartDelay = immediate ? 0 : (quoteIdx * 95) + 70;
    window.setTimeout(() => runQuoteTypewriter(slide, immediate), twStartDelay);
  }}
}}

function setActiveSlide(idx, immediate = false) {{
  const clamped = Math.max(0, Math.min(idx, slides.length - 1));
  if (clamped === _activeRevealIdx && !immediate) return;

  slides.forEach((slide, i) => {{
    if (i !== clamped) {{
      slide.querySelectorAll('.reveal.visible').forEach(el => el.classList.remove('visible'));
    }}
  }});

  _activeRevealIdx = clamped;
  renderSpeakerNotes(clamped);
  animateSlideReveal(slides[clamped], immediate);
  setTocActive(clamped);
}}

function currentSlideIndex() {{
  if (!slides.length) return 0;
  let bestIdx = 0;
  let bestDist = Infinity;
  for (let i = 0; i < slides.length; i++) {{
    const dist = Math.abs(slides[i].getBoundingClientRect().top);
    if (dist < bestDist) {{
      bestDist = dist;
      bestIdx = i;
    }}
  }}
  return bestIdx;
}}
function setHashForIndex(idx) {{
  if (!slides.length) return;
  const slide = slides[Math.max(0, Math.min(idx, slides.length - 1))];
  if (!slide || !slide.id) return;
  const nextHash = `#${{slide.id}}`;
  if (window.location.hash !== nextHash) {{
    history.replaceState(null, '', nextHash);
  }}
}}
function refreshFooterVisibility(idx) {{
  if (!footerEl || !slides.length) return;
  const slide = slides[Math.max(0, Math.min(idx, slides.length - 1))];
  const hide = !!(slide && (slide.classList.contains('slide-title') || slide.classList.contains('slide-closing')));
  footerEl.style.display = hide ? 'none' : 'grid';
}}
function goToIndex(idx, smooth = true) {{
  if (!slides.length) return;
  const clamped = Math.max(0, Math.min(idx, slides.length - 1));
  _currentIdx = clamped;
  refreshFooterVisibility(clamped);
  setHashForIndex(clamped);
  slides[clamped].scrollIntoView({{ behavior: smooth ? 'smooth' : 'auto', block: 'start' }});

  if (_revealTimer) window.clearTimeout(_revealTimer);
  _revealTimer = window.setTimeout(() => {{
    setActiveSlide(clamped);
  }}, smooth ? 220 : 0);
}}
function goNext() {{ goToIndex(currentSlideIndex() + 1); }}
function goPrev() {{ goToIndex(currentSlideIndex() - 1); }}
function goHome() {{ goToIndex(0); }}
function goEnd() {{ goToIndex(slides.length - 1); }}
function keyData(e) {{
  return {{
    key: (e.key || ''),
    code: (e.code || ''),
    keyCode: Number(e.keyCode || e.which || 0)
  }};
}}
function isNextKey(e) {{
  const k = keyData(e);
  return (
    k.key === 'ArrowDown' || k.key === 'ArrowRight' || k.key === ' ' || k.key === 'PageDown' ||
    k.key === 'Down' || k.key === 'Right' ||
    k.code === 'ArrowDown' || k.code === 'ArrowRight' || k.code === 'Space' || k.code === 'PageDown' ||
    k.keyCode === 32 || k.keyCode === 34 || k.keyCode === 39 || k.keyCode === 40
  );
}}
function isPrevKey(e) {{
  const k = keyData(e);
  return (
    k.key === 'ArrowUp' || k.key === 'ArrowLeft' || k.key === 'PageUp' ||
    k.key === 'Up' || k.key === 'Left' ||
    k.code === 'ArrowUp' || k.code === 'ArrowLeft' || k.code === 'PageUp' ||
    k.keyCode === 33 || k.keyCode === 37 || k.keyCode === 38
  );
}}
function shouldIgnoreTarget(target) {{
  if (!target || !(target instanceof Element)) return false;
  return !!target.closest('a, button, input, textarea, select, [contenteditable="true"], [data-no-nav="true"]');
}}

// Assure un focus clavier actif, utile dans les viewers intégrés.
if (document.body) {{
  document.body.setAttribute('tabindex', '-1');
}}
window.addEventListener('load', () => {{
  if (document.body) document.body.focus();
  buildToc();

  // Restore depuis l'ancre URL si présente (ex: #s12)
  const hash = (window.location.hash || '').replace('#', '');
  if (hash) {{
    const targetIdx = slides.findIndex(s => s.id === hash);
    if (targetIdx >= 0) {{
      setActiveSlide(targetIdx, true);
      goToIndex(targetIdx, false);
      return;
    }}
  }}
  // Initialise l'ancre au slide courant au chargement
  _currentIdx = currentSlideIndex();
  refreshFooterVisibility(_currentIdx);
  setActiveSlide(_currentIdx, true);
  setHashForIndex(_currentIdx);
}});
if (tocToggleBtn) {{
  tocToggleBtn.addEventListener('click', e => {{
    e.preventDefault();
    e.stopPropagation();
    toggleToc();
  }});
}}
if (tocCloseBtn) {{
  tocCloseBtn.addEventListener('click', e => {{
    e.preventDefault();
    e.stopPropagation();
    closeToc();
  }});
}}
if (notesToggleBtn) {{
  notesToggleBtn.addEventListener('click', e => {{
    e.preventDefault();
    e.stopPropagation();
    toggleNotes();
  }});
}}
if (notesCloseBtn) {{
  notesCloseBtn.addEventListener('click', e => {{
    e.preventDefault();
    e.stopPropagation();
    closeNotes();
  }});
}}
if (tocBackdropEl) {{
  tocBackdropEl.addEventListener('click', e => {{
    e.preventDefault();
    e.stopPropagation();
    closeToc();
    closeNotes();
  }});
}}
document.addEventListener('click', e => {{
  if (shouldIgnoreTarget(e.target)) return;
  if (document.body) document.body.focus();
}}, {{ passive: true }});

// ── Clavier ───────────────────────────────────────────────────────────────
const handleKeyNav = e => {{
  if (shouldIgnoreTarget(e.target)) return;
  const k = keyData(e);

  if (isNextKey(e)) {{
    e.preventDefault();
    goNext();
    return;
  }}

  if (isPrevKey(e)) {{
    e.preventDefault();
    goPrev();
    return;
  }}

  if (k.key === 'Home' || k.code === 'Home' || k.keyCode === 36) {{
    e.preventDefault();
    goHome();
    return;
  }}

  if (k.key === 'End' || k.code === 'End' || k.keyCode === 35) {{
    e.preventDefault();
    goEnd();
    return;
  }}

  if (k.key === 'f' || k.key === 'F') {{
    e.preventDefault();
    if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {{}});
    else document.exitFullscreen().catch(() => {{}});
    return;
  }}

  if (k.key === 'm' || k.key === 'M') {{
    e.preventDefault();
    toggleToc();
    return;
  }}

  if (k.key === 'n' || k.key === 'N') {{
    e.preventDefault();
    toggleNotes();
    return;
  }}

  if (k.key === 'Escape' || k.code === 'Escape' || k.keyCode === 27) {{
    if (tocPanelEl && tocPanelEl.classList.contains('open')) {{
      e.preventDefault();
      closeToc();
      return;
    }}
    if (notesPanelEl && notesPanelEl.classList.contains('open')) {{
      e.preventDefault();
      closeNotes();
      return;
    }}
  }}
}};
window.addEventListener('keydown', handleKeyNav, {{ capture: true }});

// ── Souris ─────────────────────────────────────────────────────────────────
document.addEventListener('click', e => {{
  if (shouldIgnoreTarget(e.target)) return;
  goNext();
}});

document.addEventListener('contextmenu', e => {{
  if (shouldIgnoreTarget(e.target)) return;
  e.preventDefault();
  goPrev();
}});

// ── Citation: copie presse-papiers ───────────────────────────────────────
document.addEventListener('click', async e => {{
  const btn = e.target && e.target.closest ? e.target.closest('.quote-copy-btn') : null;
  if (!btn) return;

  e.preventDefault();
  e.stopPropagation();

  const quoteEl = btn.closest('.slide')?.querySelector('blockquote');
  const text = String(quoteEl?.dataset?.typewriterText || quoteEl?.textContent || '').trim();
  if (!text) return;

  try {{
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      await navigator.clipboard.writeText(text);
    }} else {{
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }}
    const old = btn.textContent;
    btn.textContent = 'Copiee';
    setTimeout(() => {{ btn.textContent = old || 'Copier la citation'; }}, 900);
  }} catch (_err) {{
    const old = btn.textContent;
    btn.textContent = 'Echec copie';
    setTimeout(() => {{ btn.textContent = old || 'Copier la citation'; }}, 1200);
  }}
}});

// ── Blocs de code: coloration, indicateur de scroll, copie ──────────────
if (window.hljs) {{
  document.querySelectorAll('.code-scroll code').forEach(el => hljs.highlightElement(el));
}}

document.querySelectorAll('.code-block').forEach(wrap => {{
  const pre = wrap.querySelector('.code-scroll');
  if (!pre) return;
  const updateHint = () => {{
    wrap.classList.toggle('is-scrollable', pre.scrollHeight > pre.clientHeight + 2);
    wrap.classList.toggle('at-bottom', pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 2);
  }};
  updateHint();
  pre.addEventListener('scroll', updateHint, {{ passive: true }});
  window.addEventListener('resize', updateHint);
}});

document.addEventListener('click', async e => {{
  const btn = e.target && e.target.closest ? e.target.closest('.code-copy-btn') : null;
  if (!btn) return;

  e.preventDefault();
  e.stopPropagation();

  const codeEl = btn.closest('.code-block')?.querySelector('code');
  const text = codeEl ? String(codeEl.textContent || '') : '';
  if (!text) return;

  try {{
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      await navigator.clipboard.writeText(text);
    }} else {{
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }}
    const old = btn.textContent;
    btn.textContent = 'Copie !';
    setTimeout(() => {{ btn.textContent = old || 'Copier'; }}, 900);
  }} catch (_err) {{
    btn.textContent = 'Echec';
    setTimeout(() => {{ btn.textContent = 'Copier'; }}, 1200);
  }}
}});

// ── Swipe tactile ─────────────────────────────────────────────────────────
let _ty = 0;
document.addEventListener('touchstart', e => {{ _ty = e.touches[0].clientY; }}, {{ passive: true }});
document.addEventListener('touchend', e => {{
  if (shouldIgnoreTarget(e.target)) return;
  const dy = _ty - e.changedTouches[0].clientY;
  if (Math.abs(dy) > 50) {{
    if (dy > 0) {{
      goNext();
    }} else {{
      goPrev();
    }}
  }}
}}, {{ passive: true }});

// Maintient l'ancre synchronisée pendant le scroll manuel.
let _hashSyncTimer = 0;
window.addEventListener('scroll', () => {{
  if (_hashSyncTimer) window.clearTimeout(_hashSyncTimer);
  _hashSyncTimer = window.setTimeout(() => {{
    const idx = currentSlideIndex();
    if (idx !== _currentIdx) {{
      _currentIdx = idx;
      refreshFooterVisibility(idx);
      setActiveSlide(idx);
      setHashForIndex(idx);
    }}
  }}, 120);
}}, {{ passive: true }});
</script>
</body>
</html>"""


# ── Génération ────────────────────────────────────────────────────────────────
def generate(font_b64: str, source_file: str) -> None:
    with open(source_file, "r", encoding="utf-8") as f:
        text = f.read()

    meta, body = parse_front_matter(text)
    slides = parse_content(body)
    if not slides:
        print("⚠️  Aucune slide trouvée dans content.md")
        return

    footer_cfg = build_footer_config(meta)
    page_title = build_page_title(meta)
    theme = normalize_theme(meta.get("theme"))
    conference_dir = conference_dir_from_source(source_file)
    html = build_html(slides, font_b64, footer_cfg, page_title, source_file, conference_dir, theme)
    html = minify_html(html)  # Minifier avant écriture
    output_file = output_file_from_source(source_file)
    markdown_file = markdown_file_from_source(source_file)

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)

    # Copie la source markdown dans le dossier de la conférence, sauf si c'est deja la source.
    if os.path.abspath(markdown_file) != os.path.abspath(source_file):
      with open(markdown_file, "w", encoding="utf-8") as f:
        f.write(text)

    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] ✅  {len(slides)} slides → {output_file}")
    if os.path.abspath(markdown_file) != os.path.abspath(source_file):
      print(f"[{ts}] 📝  Source markdown → {markdown_file}")


def file_hash(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


# ── Point d'entrée ────────────────────────────────────────────────────────────
def main() -> None:
    args = sys.argv[1:]
    watch = "--watch" in sys.argv or "-w" in sys.argv
    source_file = DEFAULT_CONTENT_FILE

    if "--input" in args:
        i = args.index("--input")
        if i + 1 >= len(args):
            print("❌  Option --input sans chemin.")
            sys.exit(1)
        source_file = args[i + 1]
    elif "-i" in args:
        i = args.index("-i")
        if i + 1 >= len(args):
            print("❌  Option -i sans chemin.")
            sys.exit(1)
        source_file = args[i + 1]

    if not os.path.isabs(source_file):
        source_file = os.path.join(SCRIPT_DIR, source_file)

    if not os.path.isfile(source_file):
        print(f"❌  Fichier markdown introuvable: {source_file}")
        sys.exit(1)

    os.makedirs(CONF_DIR, exist_ok=True)

    print("🔤  Chargement de la police Publico Headline…")
    font_b64 = load_font()
    print(f"✅  Police chargée ({len(font_b64)//1000} ko)")

    generate(font_b64, source_file)

    if watch:
        print(f"\n👁  Surveillance de {source_file} — Ctrl+C pour arrêter\n")
        last_hash = file_hash(source_file)
        try:
            while True:
                time.sleep(0.8)
                try:
                    h = file_hash(source_file)
                except FileNotFoundError:
                    continue
                if h != last_hash:
                    last_hash = h
                    generate(font_b64, source_file)
        except KeyboardInterrupt:
            print("\n👋  Watcher arrêté.")


if __name__ == "__main__":
    main()
