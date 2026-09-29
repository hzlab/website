# Maintaining publications

The 109 papers originally filed under 2023 and earlier are now maintained in
`data/publications.json`. The published site remains a static HTML page and needs
no API calls or JavaScript to display citations. Existing 2024–2026 and preprint
entries remain hand-maintained; three reclassified papers are generated inside
the existing 2024 section.

## Consistent style

Authors. Title. Journal. Year; volume(issue): pages or article number. (Notes; IF: value)

- Use surname plus initials. Preserve the lab's underlining of Helen and the
  existing contribution symbols. Consortium author lists may remain abbreviated.
- Use the final issue year once available, even when online publication was earlier.
- Preserve article identifiers such as `fcad192` and `e77745`; they are not missing pages.
- Use complete page ranges throughout. Omit the issue if the journal has none.
- Conference papers use proceedings and pages; book chapters use the book title
  and pages. A conference short paper without assigned pagination has an explicit
  `exception` in the data instead of invented bibliographic fields.
- Preserve historical IF values. Crossref does not supply JCR impact factors,
  Cover designations, or reliable joint-author roles. These require manual sources.

## Commands

Python 3.10 or newer is sufficient; no packages, accounts, API keys, or installs.
Run from the repository root:

```powershell
# Validate required fields, duplicate IDs/DOIs, local PDFs, and HTML synchronization.
python scripts/publications.py check

# Retrieve a new record from its exact DOI for review (prints JSON; changes no files).
python scripts/publications.py lookup 10.1038/s41586-022-04554-y

# After editing the curated data, regenerate the two marked HTML regions.
python scripts/publications.py render
python scripts/publications.py check

# Recheck all 108 DOI records against live Crossref metadata.
python scripts/publications.py audit --output "$env:TEMP\publications-audit.json"

# Regenerate the human-readable before/after report.
python scripts/publications.py report
```

`audit` includes retry/backoff and reports network failures explicitly. It compares
current metadata with the saved publisher metadata snapshot, not with accepted
manual corrections. Exit status 1 means a source changed or a lookup failed;
inspect the report. It never rewrites the website or overwrites curated fields.
`--limit 2` can be used for a quick connection check. It does not test external
PDF/media URL availability or independently verify IF/author-contribution claims.

## Reviewing additions and updates

1. Retrieve the exact DOI with `lookup`, then check the title and publisher page.
   Title search alone can select a different paper, a preprint, or a correction.
2. Review year, journal, volume, issue, and complete pages/article ID. Crossref
   sometimes stores only the first page or omits a volume: retain a sourced manual
   correction rather than blindly replacing it.
3. Edit the structured record in `data/publications.json`; retain evidence in
   `sources` and the unmodified source metadata in `metadata_snapshot`. The raw
   historical text is retained as `original_citation` for comparison.
4. Run `render`, `check`, and inspect the HTML diff and browser preview.

The current managed regions accept 2005–2024 records only. Extending automatic
generation to newer years requires adding a marked region for that year and
reviewing the existing hand-maintained entries for duplicates first. Do not edit
generated citations directly in `publications.html`; edit their JSON records.

See `publications-audit.md` for per-paper sources, year regrouping, and exceptions.
