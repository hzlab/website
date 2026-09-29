#!/usr/bin/env python3
"""Generate and audit the curated bibliography. Python 3.10+, standard library only."""
import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/publications.json'
PAGE = ROOT / 'publications.html'
ARCHIVE_START = '<!-- BEGIN GENERATED PUBLICATIONS: archive -->'
ARCHIVE_END = '<!-- END GENERATED PUBLICATIONS: archive -->'
MOVED_START = '<!-- BEGIN GENERATED PUBLICATIONS: 2024 additions -->'
MOVED_END = '<!-- END GENERATED PUBLICATIONS: 2024 additions -->'
UL_STYLE = 'font-family:Arial;overflow:hidden;padding-left:3.4em!important;margin:5px 0px!important;list-style-position:outside!important'
LI_STYLE = 'list-style-type:disc!important;padding-left:5px!important;margin:5px 40px 5px!important;font-size:110%'
HEADING_STYLE = 'margin:0px;padding:0.3em 0px;line-height:1.3;font-weight:700;color:rgb(235,176,88);text-transform:uppercase;letter-spacing:normal;font-family:Arial!important'


def load():
    return json.loads(DATA.read_text(encoding='utf-8'))


def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', '', str(value)))).strip()


def authors_markup(value):
    """Escape text while allowing only the lab's underline markup."""
    return html.escape(value, quote=False).replace('&lt;u&gt;', '<u>').replace('&lt;/u&gt;', '</u>')


def citation(record):
    e = lambda value: html.escape(str(value), quote=False)
    title = e(record['title'].rstrip('.'))
    title += '' if title.endswith('?') else '.'
    result = f"{authors_markup(record['authors_html'])}. {title} {e(record['journal'].rstrip('.'))}. {record['year']}"
    volume, issue, pages = (record[k] for k in ('volume', 'issue', 'pages_or_article'))
    if volume:
        result += '; ' + e(volume)
        if issue:
            result += '(' + e(issue) + ')'
        if pages:
            result += ': ' + e(pages)
    elif pages:
        result += '; pp. ' + e(pages)
    result += '.'
    notes = ['<strong>Cover</strong>' if n == 'Cover' else e(n) for n in record['annotations']]
    if record['impact_factor']:
        notes.append('IF: ' + e(record['impact_factor']))
    if notes:
        result += ' (' + '; '.join(notes) + ')'
    return result


def entry(record):
    links = []
    for link in record['links']:
        label = html.escape(link['label'])
        if not link['url']:
            links.append(label)  # Keep an existing unlinked media mention as text.
        else:
            url = html.escape(link['url'], quote=True)
            links.append(f'<a href="{url}" style="color:rgb(255,102,0)!important" target="_blank" rel="noopener noreferrer">{label}</a>')
    return (f'\t<li id="publication-{record["id"]}" style="{LI_STYLE}">\n'
            f'\t\t<font size="3" color="#2a2a2a">{citation(record)} '
            + ' | '.join(links) + '</font>\n\t</li>')


def entries(records):
    if not records:
        return ''
    return f'<ul style="{UL_STYLE}">\n' + '\n'.join(entry(r) for r in records) + '\n</ul>'


def generated_archive(records):
    groups = {}
    for record in records:
        if record['year'] > 2023:
            continue
        section = str(record['year']) if record['year'] >= 2010 else '2005 - 2009'
        groups.setdefault(section, []).append(record)
    parts = []
    for section in sorted(groups, reverse=True):
        parts.append(f'<h2 id="publications-{section[:4]}" style="{HEADING_STYLE}"><font size="5">{section}</font></h2>\n'
                     '<div style="line-height:1.5;margin:0px;padding:0.5em 0px">\n'
                     + entries(groups[section]) + '\n</div>')
    return '\n\n'.join(parts)


def replace_region(page, start, end, contents):
    if page.count(start) != 1 or page.count(end) != 1:
        raise ValueError(f'Expected exactly one managed region: {start}')
    before, remainder = page.split(start)
    _, after = remainder.split(end)
    return before + start + '\n' + contents + '\n' + end + after


def rendered_page(page, records):
    page = replace_region(page, ARCHIVE_START, ARCHIVE_END, generated_archive(records))
    return replace_region(page, MOVED_START, MOVED_END, entries([r for r in records if r['year'] == 2024]))


def validate(records):
    errors = []
    seen_ids, seen_dois = set(), set()
    required = ('id', 'authors_html', 'title', 'journal', 'year', 'kind', 'sources', 'verified_on')
    for record in records:
        label = record.get('id', '(no id)')
        for key in required:
            if not record.get(key):
                errors.append(f'{label}: missing {key}')
        if label in seen_ids:
            errors.append(f'{label}: duplicate id')
        seen_ids.add(label)
        doi = record.get('doi', '').lower()
        if doi and doi in seen_dois:
            errors.append(f'{label}: duplicate DOI {doi}')
        if doi and not re.fullmatch(r'10\.\d{4,9}/\S+', doi):
            errors.append(f'{label}: invalid DOI')
        if doi:
            seen_dois.add(doi)
        if not isinstance(record.get('year'), int) or not 2005 <= record['year'] <= 2024:
            errors.append(f'{label}: managed archive supports years 2005–2024')
        if record.get('kind') == 'journal' and not record.get('volume'):
            errors.append(f'{label}: journal volume missing')
        if not record.get('pages_or_article') and not record.get('exception'):
            errors.append(f'{label}: missing pages/article number without an explained exception')
        if record.get('issue') and not record.get('volume'):
            errors.append(f'{label}: issue without volume')
        if re.search(r'In press|pii:|0\(0\)', citation(record), re.I):
            errors.append(f'{label}: unresolved provisional citation')
        for link in record.get('links', []):
            url = link['url']
            if url and not url.startswith(('https://', 'http://', 'assets/')):
                errors.append(f'{label}: unsupported link {url}')
            if url.startswith('assets/') and not (ROOT / url).is_file():
                errors.append(f'{label}: missing local resource {url}')
    return errors


def crossref(doi):
    doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', doi.strip(), flags=re.I)
    if not re.fullmatch(r'10\.\d{4,9}/\S+', doi):
        raise ValueError('Supply a DOI or a doi.org URL.')
    url = 'https://api.crossref.org/works/' + urllib.parse.quote(doi, safe='')
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'MNNDL-publications/1.0 (bibliography maintenance)'})
            with urllib.request.urlopen(request, timeout=30) as response:
                message = json.load(response)['message']
            if message.get('DOI', '').lower() != doi.lower():
                raise ValueError('Returned DOI does not match the requested DOI.')
            return message
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == 3:
                raise
            retry = error.headers.get('Retry-After', '') if isinstance(error, urllib.error.HTTPError) else ''
            delay = min(int(retry), 30) if retry.isdigit() else 2 ** (attempt + 1)
            time.sleep(delay)


def metadata_fields(message):
    return {
        'title': plain(' '.join(message.get('title', []))),
        'journal': plain(' / '.join(message.get('container-title', []))),
        'year': message.get('published-print', message.get('published', {})).get('date-parts', [[None]])[0][0],
        'volume': str(message.get('volume', '')),
        'issue': str(message.get('issue', '')),
        'pages_or_article': str(message.get('page') or message.get('article-number', '')),
    }


def audit_online(records, limit=None):
    results = []
    selected = [r for r in records if r['doi']]
    if limit:
        selected = selected[:limit]
    for record in selected:
        try:
            current = metadata_fields(crossref(record['doi']))
            previous = metadata_fields(record['metadata_snapshot'])
            changes = {k: {'saved_source': previous[k], 'current_source': current[k]} for k in current if current[k] != previous[k]}
            results.append({'id': record['id'], 'doi': record['doi'], 'changes': changes})
            print(record['id'], 'SOURCE CHANGED — review needed' if changes else 'source unchanged', flush=True)
        except Exception as error:
            results.append({'id': record['id'], 'doi': record['doi'], 'error': str(error)})
            print(record['id'], 'LOOKUP FAILED', str(error), flush=True)
        time.sleep(0.5)
    return {'checked_on': date.today().isoformat(), 'checked_count': len(results), 'records': results}


def report(records):
    lines = ['# Publications audit — 2026-09-29', '',
             f'Checked and standardized the {len(records)} entries originally listed under 2023 and earlier.', '',
             'Format: Authors. Title. Journal. Year; volume(issue): pages or article number. (Notes; IF: original value)', '',
             '- Bibliographic fields were matched by title/DOI against publisher-deposited Crossref records, with publisher/proceedings sources for missing fields.',
             '- Use the final issue year when assigned; retain article numbers and complete page ranges. Do not derive years from DOI strings.',
             '- Existing 2024–2026 entries and preprints were not rewritten. Three old entries were moved into 2024.',
             '- Existing author lists and contribution markers were retained, with punctuation normalization and selected source-verified name corrections. Long consortium lists remain abbreviated; this is not an exhaustive contributor-role audit.',
             '- Historical IF values were retained, not independently verified or updated. Their JCR years are not recorded in the old page.', '',
             '## Year regrouping', '', '| ID | Old section | Final issue year | Paper |', '| --- | --- | --- | --- |']
    for r in records:
        if r['original_section'] != '2005 - 2009' and int(r['original_section']) != r['year']:
            lines.append(f"| {r['id']} | {r['original_section']} | {r['year']} | [{r['title']}](https://doi.org/{r['doi']}) |")
    lines += ['', '## Exceptions and notable corrections', '',
              '- MIDL 2022 short paper (legacy-019): the conference programme confirms the listing; no journal volume/issue or proceedings page range is assigned. Kept as a short paper, with an explicit validation exception.',
              '- Ho et al. (legacy-068): Neuropsychopharmacology corrected from 22(1):142–152 to 42(6):1361–1370.',
              '- Guo et al. (legacy-080): PNAS issue corrected from 27 to 17. Existing 2016_06.pdf is a correction notice; its link is now labelled Correction PDF.',
              '- Brain Circuits chapter (legacy-069): Oxford lists publication in 2016, pages 98–122; corrected the old citation year 2017.',
              '- Canonical DOI links added for every DOI-matched record. Conference preprints, editorials, media links, and local PDFs retained.', '',
              '## Per-record evidence', '']
    for r in records:
        lines += [f"### {r['id']} — {r['year']}", '', '**Before:** ' + r['original_citation'], '',
                  '**After:** ' + plain(citation(r)), '',
                  '**Sources:** ' + '; '.join(f"[{s['note']}]({s['url']})" for s in r['sources']), '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('check', help='Offline validation and generated-HTML drift check; no writes')
    sub.add_parser('render', help='Regenerate only the two marked HTML regions')
    sub.add_parser('report', help='Write docs/publications-audit.md')
    audit = sub.add_parser('audit', help='Fetch DOI metadata and report source changes without modifying the website')
    audit.add_argument('--limit', type=int)
    audit.add_argument('--output', type=Path, required=True)
    lookup = sub.add_parser('lookup', help='Retrieve metadata by DOI for review, without modifying the website')
    lookup.add_argument('doi')
    args = parser.parse_args()
    if args.command == 'lookup':
        message = crossref(args.doi)
        fields = metadata_fields(message)
        fields.update({'doi': message['DOI'], 'authors': message.get('author', []),
                       'review_required': 'Check publisher page, final issue year, full page range, and author markers before adding to the curated JSON.'})
        print(json.dumps(fields, ensure_ascii=False, indent=2))
        return
    records = load()
    errors = validate(records)
    if errors:
        raise ValueError('\n'.join(errors))
    if args.command in ('check', 'render'):
        page = PAGE.read_text(encoding='utf-8')
        rendered = rendered_page(page, records)
        if args.command == 'render':
            # Preserve the original site's CRLF line endings.
            with PAGE.open('w', encoding='utf-8', newline='\r\n') as file:
                file.write(rendered)
        elif rendered != page:
            raise ValueError('HTML differs from curated data. Run: python scripts/publications.py render')
        for r in records:
            if rendered.count(f'id="publication-{r["id"]}"') != 1:
                raise ValueError(f'{r["id"]}: expected exactly one rendered entry')
        print(f'{args.command}: {len(records)} records, {sum(bool(r["doi"]) for r in records)} unique DOIs, all local resource links present; HTML synchronized.')
    elif args.command == 'report':
        target = ROOT / 'docs/publications-audit.md'
        target.parent.mkdir(exist_ok=True)
        target.write_text(report(records), encoding='utf-8')
        print(target)
    elif args.command == 'audit':
        if args.limit is not None and args.limit < 1:
            raise ValueError('--limit must be positive')
        result = audit_online(records, args.limit)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        if any(r.get('error') or r.get('changes') for r in result['records']):
            sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
