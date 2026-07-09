import re
import os
import html
import unicodedata
from datetime import datetime

BIB_FILE = "publications.bib"
OUT_DIR = "_publications"

os.makedirs(OUT_DIR, exist_ok=True)


def clean_text(s):
    if not s:
        return ""
    s = s.replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    s = s.replace("{", "").replace("}", "")
    return s.strip()


def slugify(text):
    text = clean_text(text).lower()
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


def split_bib_entries(bib):
    entries = []
    current = []
    depth = 0
    inside = False

    for line in bib.splitlines():
        stripped = line.strip()
        if stripped.startswith("@"):
            if current:
                entries.append("\n".join(current))
            current = [line]
            inside = True
            depth = line.count("{") - line.count("}")
        elif inside:
            current.append(line)
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                entries.append("\n".join(current))
                current = []
                inside = False

    if current:
        entries.append("\n".join(current))

    return entries


def parse_entry(entry):
    first_line = entry.splitlines()[0]
    m = re.match(r"@(\w+)\s*\{\s*([^,]+),", first_line)
    if not m:
        return None

    entry_type = m.group(1).lower()
    key = m.group(2).strip()

    fields = {}
    body = entry[entry.find(",") + 1 : entry.rfind("}")]

    pattern = re.compile(
        r"(\w+)\s*=\s*[\{|\"](.+?)[\}|\"]\s*,?\s*(?=\n\s*\w+\s*=|\Z)",
        re.DOTALL,
    )

    for field, value in pattern.findall(body):
        fields[field.lower()] = clean_text(value)

    fields["entry_type"] = entry_type
    fields["bibtex_key"] = key
    return fields


def get_venue(fields):
    if fields.get("journal"):
        return fields["journal"]
    if fields.get("booktitle"):
        return fields["booktitle"]
    if fields.get("publisher"):
        return fields["publisher"]
    if fields.get("institution"):
        return fields["institution"]
    return ""


def get_date(fields):
    year = fields.get("year", "")
    month = fields.get("month", "01")

    if not year:
        return "1900-01-01"

    month_map = {
        "jan": "01", "january": "01",
        "feb": "02", "february": "02",
        "mar": "03", "march": "03",
        "apr": "04", "april": "04",
        "may": "05",
        "jun": "06", "june": "06",
        "jul": "07", "july": "07",
        "aug": "08", "august": "08",
        "sep": "09", "sept": "09", "september": "09",
        "oct": "10", "october": "10",
        "nov": "11", "november": "11",
        "dec": "12", "december": "12",
    }

    month = month_map.get(month.lower(), "01")
    return f"{year}-{month}-01"


def make_citation(fields):
    authors = fields.get("author", "")
    title = fields.get("title", "")
    year = fields.get("year", "")
    venue = get_venue(fields)

    citation = ""
    if authors:
        citation += authors + ". "
    if title:
        citation += f'"{title}." '
    if venue:
        citation += f"{venue}. "
    if year:
        citation += f"{year}."

    return citation.strip()


def make_markdown(fields):
    title = fields.get("title", "Untitled")
    year = fields.get("year", "1900")
    date = get_date(fields)
    venue = get_venue(fields)
    doi = fields.get("doi", "")
    url = fields.get("url", fields.get("paperurl", ""))
    abstract = fields.get("abstract", "")
    citation = make_citation(fields)

    slug = f"{year}-{slugify(title)}"
    filename = os.path.join(OUT_DIR, f"{slug}.md")

    permalink = f"/publication/{slug}"

    paperurl = url
    if doi and not paperurl:
        paperurl = f"https://doi.org/{doi}"

    content = f"""---
title: "{title.replace('"', "'")}"
collection: publications
permalink: {permalink}
date: {date}
venue: "{venue.replace('"', "'")}"
paperurl: "{paperurl}"
citation: "{citation.replace('"', "'")}"
---

"""

    if abstract:
        content += f"**Abstract:** {abstract}\n\n"

    if doi:
        content += f"**DOI:** [{doi}](https://doi.org/{doi})\n\n"

    content += "<details>\n<summary>BibTeX</summary>\n\n"
    content += "```bibtex\n"
    content += fields.get("raw_bibtex", "").strip()
    content += "\n```\n\n"
    content += "</details>\n"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    return filename


def main():
    with open(BIB_FILE, "r", encoding="utf-8") as f:
        bib = f.read()

    entries = split_bib_entries(bib)

    count = 0
    for entry in entries:
        fields = parse_entry(entry)
        if not fields:
            continue
        fields["raw_bibtex"] = entry
        make_markdown(fields)
        count += 1

    print(f"Generated {count} publication files in {OUT_DIR}/")


if __name__ == "__main__":
    main()