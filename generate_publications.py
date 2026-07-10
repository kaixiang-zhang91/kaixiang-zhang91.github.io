#!/usr/bin/env python3
"""
Generate Academic Pages publication Markdown files from a BibTeX file.

Usage:
    python3 generate_publications.py
    python3 generate_publications.py publications.bib
    python3 generate_publications.py publications.bib --clean

Default input:
    publications.bib

Default output:
    _publications/

Notes:
- Uses only the Python standard library.
- Generates fields for a custom publication layout:
  title, authors, venue, year, category, paperurl, arxivurl,
  codeurl, videourl, slidesurl, doi, highlight, citation.
- Prevents Jekyll/Liquid errors caused by BibTeX braces such as {{O2RNet}}.
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


DEFAULT_BIB_FILE = "publications.bib"
DEFAULT_OUTPUT_DIR = "_publications"

# Add all versions of your name that may appear in BibTeX.
OWNER_NAMES = [
    "Kaixiang Zhang",
    "K. Zhang",
    "Zhang, Kaixiang",
]

# Optional custom notes keyed by BibTeX key.
# Example:
# HIGHLIGHTS = {
#     "zhang2025example": "Best Paper Award",
# }
HIGHLIGHTS: Dict[str, str] = {}

# Optional manually supplied links keyed by BibTeX key.
# BibTeX fields take precedence when present.
EXTRA_LINKS: Dict[str, Dict[str, str]] = {
    # "zhang2025example": {
    #     "paperurl": "https://example.com/paper.pdf",
    #     "codeurl": "https://github.com/example/repo",
    #     "videourl": "https://youtu.be/example",
    #     "slidesurl": "https://example.com/slides.pdf",
    # },
}


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def strip_outer_braces(value: str) -> str:
    """Remove balanced outer braces repeatedly, but preserve internal text."""
    value = value.strip()
    changed = True
    while changed and len(value) >= 2:
        changed = False
        if value.startswith("{") and value.endswith("}"):
            depth = 0
            balanced = True
            for index, char in enumerate(value):
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0 and index != len(value) - 1:
                        balanced = False
                        break
                if depth < 0:
                    balanced = False
                    break
            if balanced and depth == 0:
                value = value[1:-1].strip()
                changed = True
    return value


LATEX_REPLACEMENTS = {
    r"\&": "&",
    r"\%": "%",
    r"\_": "_",
    r"\#": "#",
    r"\$": "$",
    r"\textendash": "–",
    r"\textemdash": "—",
    r"\textquotedblleft": "“",
    r"\textquotedblright": "”",
    r"\textquotesingle": "'",
    r"\textregistered": "®",
    r"\texttrademark": "™",
    "~": " ",
}


def clean_text(value: str) -> str:
    """
    Convert common BibTeX/LaTeX formatting into safe readable text.

    All braces are removed so strings like {{O2RNet}} cannot be interpreted
    by Liquid as {{ ... }}.
    """
    if not value:
        return ""

    value = strip_outer_braces(value)
    value = normalize_whitespace(value)

    for source, replacement in LATEX_REPLACEMENTS.items():
        value = value.replace(source, replacement)

    # Convert simple LaTeX accents, e.g. {\"o}, \'e, \c{c}.
    accent_patterns = [
        (r'\{?\\"([A-Za-z])\}?', r"\1"),
        (r"\{?\\'([A-Za-z])\}?", r"\1"),
        (r"\{?\\`([A-Za-z])\}?", r"\1"),
        (r"\{?\\\^([A-Za-z])\}?", r"\1"),
        (r"\{?\\~([A-Za-z])\}?", r"\1"),
        (r"\{?\\c\{([A-Za-z])\}\}?", r"\1"),
    ]
    for pattern, replacement in accent_patterns:
        value = re.sub(pattern, replacement, value)

    # Remove common LaTeX formatting commands while retaining their contents.
    value = re.sub(
        r"\\(?:textbf|textit|emph|mathrm|mathbf|mathit|operatorname)\s*\{([^{}]*)\}",
        r"\1",
        value,
    )

    # Remove remaining backslash commands.
    value = re.sub(r"\\[A-Za-z]+", "", value)

    # Critical for Jekyll/Liquid safety.
    value = value.replace("{{", "").replace("}}", "")
    value = value.replace("{", "").replace("}", "")

    return normalize_whitespace(html.unescape(value))


def yaml_single_quote(value: str) -> str:
    """Return a YAML-safe single-quoted scalar."""
    value = "" if value is None else str(value)
    value = value.replace("\r", " ").replace("\n", " ")
    value = normalize_whitespace(value)
    return "'" + value.replace("'", "''") + "'"


def slugify(value: str, max_length: int = 90) -> str:
    value = clean_text(value).lower()
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value[:max_length].rstrip("-") or "publication"


def split_bibtex_entries(text: str) -> List[str]:
    """Split a BibTeX document into complete @type{...} entries."""
    entries: List[str] = []
    index = 0
    length = len(text)

    while index < length:
        match = re.search(r"@\s*[A-Za-z]+\s*[\{\(]", text[index:])
        if not match:
            break

        start = index + match.start()
        opening_index = index + match.end() - 1
        opening = text[opening_index]
        closing = "}" if opening == "{" else ")"

        depth = 0
        in_quote = False
        escaped = False
        cursor = opening_index

        while cursor < length:
            char = text[cursor]

            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_quote = not in_quote
            elif not in_quote:
                if char == opening:
                    depth += 1
                elif char == closing:
                    depth -= 1
                    if depth == 0:
                        entries.append(text[start : cursor + 1])
                        index = cursor + 1
                        break
            cursor += 1
        else:
            raise ValueError(
                f"Unterminated BibTeX entry beginning near character {start}."
            )

    return entries


def split_entry_header(entry: str) -> Tuple[str, str, str]:
    match = re.match(
        r"@\s*([A-Za-z]+)\s*[\{\(]\s*([^,\s]+)\s*,",
        entry,
        flags=re.DOTALL,
    )
    if not match:
        raise ValueError("Could not parse BibTeX entry header.")

    entry_type = match.group(1).lower()
    key = match.group(2).strip()
    body = entry[match.end() :]

    # Remove the final closing brace/parenthesis.
    body = body.rstrip()
    if body and body[-1] in "})":
        body = body[:-1]

    return entry_type, key, body


def parse_bibtex_fields(body: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    index = 0
    length = len(body)

    while index < length:
        while index < length and (body[index].isspace() or body[index] == ","):
            index += 1
        if index >= length:
            break

        key_match = re.match(r"([A-Za-z][A-Za-z0-9_:\-]*)\s*=", body[index:])
        if not key_match:
            # Skip malformed text until the next comma.
            next_comma = body.find(",", index)
            if next_comma == -1:
                break
            index = next_comma + 1
            continue

        field_name = key_match.group(1).lower()
        index += key_match.end()

        while index < length and body[index].isspace():
            index += 1

        if index >= length:
            fields[field_name] = ""
            break

        if body[index] == "{":
            index += 1
            start = index
            depth = 1
            escaped = False
            while index < length and depth > 0:
                char = body[index]
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        break
                index += 1
            raw_value = body[start:index]
            index += 1
        elif body[index] == '"':
            index += 1
            start = index
            escaped = False
            while index < length:
                char = body[index]
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    break
                index += 1
            raw_value = body[start:index]
            index += 1
        else:
            start = index
            while index < length and body[index] not in ",\n":
                index += 1
            raw_value = body[start:index].strip()

        fields[field_name] = raw_value.strip()

        while index < length and body[index] != ",":
            index += 1
        if index < length and body[index] == ",":
            index += 1

    return fields


def split_authors(author_field: str) -> List[str]:
    """
    Split a BibTeX author string on top-level ' and ' separators.
    """
    if not author_field:
        return []

    parts: List[str] = []
    buffer: List[str] = []
    depth = 0
    index = 0

    while index < len(author_field):
        char = author_field[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth = max(0, depth - 1)

        if depth == 0 and author_field[index : index + 5].lower() == " and ":
            parts.append("".join(buffer).strip())
            buffer = []
            index += 5
            continue

        buffer.append(char)
        index += 1

    if buffer:
        parts.append("".join(buffer).strip())

    return [part for part in parts if part]


def format_person_name(name: str) -> str:
    name = clean_text(name)
    if not name:
        return ""

    # BibTeX commonly stores "Last, First".
    if "," in name:
        components = [part.strip() for part in name.split(",")]
        if len(components) >= 2:
            last = components[0]
            first = components[-1]
            return normalize_whitespace(f"{first} {last}")

    return name


def is_owner_name(name: str) -> bool:
    normalized = re.sub(r"[^a-z]", "", name.lower())
    for owner_name in OWNER_NAMES:
        owner_normalized = re.sub(r"[^a-z]", "", owner_name.lower())
        if normalized == owner_normalized:
            return True
    return False


def format_authors(author_field: str) -> str:
    names = [format_person_name(item) for item in split_authors(author_field)]
    names = [name for name in names if name]

    formatted = [
        f"<strong>{name}</strong>" if is_owner_name(name) else name
        for name in names
    ]

    if not formatted:
        return ""
    if len(formatted) == 1:
        return formatted[0]
    if len(formatted) == 2:
        return f"{formatted[0]} and {formatted[1]}"
    return ", ".join(formatted[:-1]) + f", and {formatted[-1]}"


def determine_category(entry_type: str, fields: Dict[str, str]) -> str:
    note = clean_text(fields.get("note", "")).lower()
    journal = clean_text(fields.get("journal", "")).lower()

    if entry_type in {"inproceedings", "conference", "proceedings"}:
        return "conferences"
    if entry_type in {"incollection", "book", "inbook", "booklet"}:
        return "chapters"
    if entry_type in {"phdthesis", "mastersthesis", "techreport"}:
        return "other"
    if entry_type in {"misc", "unpublished"}:
        return "preprints"
    if "arxiv" in journal or "preprint" in note:
        return "preprints"
    return "manuscripts"


def get_venue(fields: Dict[str, str]) -> str:
    for field_name in (
        "journal",
        "booktitle",
        "series",
        "publisher",
        "institution",
        "school",
    ):
        value = clean_text(fields.get(field_name, ""))
        if value:
            return value
    return ""


MONTH_MAP = {
    "jan": "01",
    "january": "01",
    "feb": "02",
    "february": "02",
    "mar": "03",
    "march": "03",
    "apr": "04",
    "april": "04",
    "may": "05",
    "jun": "06",
    "june": "06",
    "jul": "07",
    "july": "07",
    "aug": "08",
    "august": "08",
    "sep": "09",
    "sept": "09",
    "september": "09",
    "oct": "10",
    "october": "10",
    "nov": "11",
    "november": "11",
    "dec": "12",
    "december": "12",
}


def publication_date(fields: Dict[str, str]) -> str:
    year_match = re.search(r"\d{4}", clean_text(fields.get("year", "")))
    year = year_match.group(0) if year_match else "1900"

    month_text = clean_text(fields.get("month", "")).lower()
    month = MONTH_MAP.get(month_text, "01")

    return f"{year}-{month}-01"


def get_year(fields: Dict[str, str]) -> str:
    match = re.search(r"\d{4}", clean_text(fields.get("year", "")))
    return match.group(0) if match else "1900"


def first_nonempty(fields: Dict[str, str], names: Iterable[str]) -> str:
    for name in names:
        value = clean_text(fields.get(name, ""))
        if value:
            return value
    return ""


def normalize_doi(value: str) -> str:
    value = clean_text(value)
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
    return value.strip()


def derive_links(
    bibtex_key: str,
    fields: Dict[str, str],
) -> Dict[str, str]:
    doi = normalize_doi(fields.get("doi", ""))

    paperurl = first_nonempty(
        fields,
        ("paperurl", "pdf", "file", "url"),
    )

    arxivurl = first_nonempty(
        fields,
        ("arxivurl", "arxiv", "eprint"),
    )
    if arxivurl and not re.match(r"https?://", arxivurl):
        arxivurl = f"https://arxiv.org/abs/{arxivurl}"

    codeurl = first_nonempty(
        fields,
        ("codeurl", "code", "github", "repository"),
    )
    videourl = first_nonempty(
        fields,
        ("videourl", "video"),
    )
    slidesurl = first_nonempty(
        fields,
        ("slidesurl", "slides"),
    )

    extras = EXTRA_LINKS.get(bibtex_key, {})
    paperurl = paperurl or extras.get("paperurl", "")
    arxivurl = arxivurl or extras.get("arxivurl", "")
    codeurl = codeurl or extras.get("codeurl", "")
    videourl = videourl or extras.get("videourl", "")
    slidesurl = slidesurl or extras.get("slidesurl", "")

    if not paperurl and doi:
        paperurl = f"https://doi.org/{doi}"

    return {
        "doi": doi,
        "paperurl": paperurl,
        "arxivurl": arxivurl,
        "codeurl": codeurl,
        "videourl": videourl,
        "slidesurl": slidesurl,
    }


def make_citation(
    authors_plain: str,
    title: str,
    venue: str,
    year: str,
) -> str:
    parts: List[str] = []
    if authors_plain:
        parts.append(authors_plain.rstrip(".") + ".")
    if title:
        parts.append(f'"{title.rstrip(".")}."')
    if venue:
        parts.append(venue.rstrip(".") + ".")
    if year and year != "1900":
        parts.append(year + ".")
    return " ".join(parts)


def raw_bibtex_for_markdown(entry: str) -> str:
    # Neutralize Liquid delimiters inside the optional BibTeX code block.
    return entry.replace("{{", "{ {").replace("}}", "} }").strip()


def render_markdown(
    entry_type: str,
    bibtex_key: str,
    fields: Dict[str, str],
    raw_entry: str,
) -> Tuple[str, str]:
    title = clean_text(fields.get("title", "")) or "Untitled"
    year = get_year(fields)
    date = publication_date(fields)
    venue = get_venue(fields)
    category = determine_category(entry_type, fields)

    authors_html = format_authors(fields.get("author", ""))
    authors_plain = re.sub(r"<[^>]+>", "", authors_html)

    links = derive_links(bibtex_key, fields)
    highlight = HIGHLIGHTS.get(
        bibtex_key,
        clean_text(fields.get("highlight", "")),
    )

    slug = f"{year}-{slugify(title)}"
    filename = f"{slug}.md"

    citation = make_citation(
        authors_plain=authors_plain,
        title=title,
        venue=venue,
        year=year,
    )

    abstract = clean_text(fields.get("abstract", ""))
    note = clean_text(fields.get("note", ""))

    front_matter = [
        "---",
        f"title: {yaml_single_quote(title)}",
        "collection: publications",
        f"permalink: /publication/{slug}",
        f"date: {date}",
        f"year: {yaml_single_quote(year)}",
        f"authors: {yaml_single_quote(authors_html)}",
        f"venue: {yaml_single_quote(venue)}",
        f"category: {yaml_single_quote(category)}",
        f"paperurl: {yaml_single_quote(links['paperurl'])}",
        f"arxivurl: {yaml_single_quote(links['arxivurl'])}",
        f"codeurl: {yaml_single_quote(links['codeurl'])}",
        f"videourl: {yaml_single_quote(links['videourl'])}",
        f"slidesurl: {yaml_single_quote(links['slidesurl'])}",
        f"doi: {yaml_single_quote(links['doi'])}",
        f"highlight: {yaml_single_quote(highlight)}",
        f"citation: {yaml_single_quote(citation)}",
        f"bibtex_key: {yaml_single_quote(bibtex_key)}",
        "---",
        "",
    ]

    body: List[str] = []

    if abstract:
        body.extend(["**Abstract:** " + abstract, ""])

    if note:
        body.extend(["**Note:** " + note, ""])

    body.extend(
        [
            "<details>",
            "<summary>BibTeX</summary>",
            "",
            "```bibtex",
            raw_bibtex_for_markdown(raw_entry),
            "```",
            "",
            "</details>",
            "",
        ]
    )

    return filename, "\n".join(front_matter + body)


def clean_output_directory(output_dir: Path) -> None:
    if not output_dir.exists():
        return
    for path in output_dir.glob("*.md"):
        path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Academic Pages publication files from BibTeX."
    )
    parser.add_argument(
        "bib_file",
        nargs="?",
        default=DEFAULT_BIB_FILE,
        help=f"BibTeX input file (default: {DEFAULT_BIB_FILE})",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Delete existing Markdown files in the output directory first.",
    )
    args = parser.parse_args()

    bib_file = Path(args.bib_file)
    output_dir = Path(args.output)

    if not bib_file.is_file():
        raise SystemExit(f"Input file not found: {bib_file}")

    output_dir.mkdir(parents=True, exist_ok=True)

    if args.clean:
        clean_output_directory(output_dir)

    text = bib_file.read_text(encoding="utf-8-sig")
    raw_entries = split_bibtex_entries(text)

    generated = 0
    skipped: List[str] = []
    used_filenames: Dict[str, int] = {}

    for raw_entry in raw_entries:
        try:
            entry_type, bibtex_key, body = split_entry_header(raw_entry)

            # Ignore non-publication entries.
            if entry_type in {"string", "preamble", "comment"}:
                continue

            fields = parse_bibtex_fields(body)
            filename, content = render_markdown(
                entry_type=entry_type,
                bibtex_key=bibtex_key,
                fields=fields,
                raw_entry=raw_entry,
            )

            # Avoid overwriting distinct entries with identical title/year slugs.
            if filename in used_filenames:
                used_filenames[filename] += 1
                stem = Path(filename).stem
                filename = f"{stem}-{used_filenames[filename]}.md"
            else:
                used_filenames[filename] = 1

            (output_dir / filename).write_text(content, encoding="utf-8")
            generated += 1

        except Exception as exc:
            key_hint = "unknown"
            try:
                _, key_hint, _ = split_entry_header(raw_entry)
            except Exception:
                pass
            skipped.append(f"{key_hint}: {exc}")

    print(f"Generated {generated} publication files in {output_dir}/")

    if skipped:
        print(f"Skipped {len(skipped)} entries:")
        for message in skipped:
            print(f"  - {message}")


if __name__ == "__main__":
    main()
