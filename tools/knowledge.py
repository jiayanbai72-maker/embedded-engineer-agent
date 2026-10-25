"""Import and retrieve scoped knowledge cards; standard library only."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

CATEGORIES = {'requirements', 'architecture', 'hardware', 'concurrency', 'build', 'debugging', 'testing', 'delivery'}
SCOPES = {'general', 'ecosystem', 'device', 'case'}
FIELDS = {'id', 'title', 'category', 'scope', 'applies_to', 'source_kind', 'source_url', 'source_section', 'version', 'reviewed_at', 'content'}


def validate(cards):
    if not isinstance(cards, list):
        raise ValueError('input must be a list of cards')
    ids = set()
    for card in cards:
        if not isinstance(card, dict) or not FIELDS.issubset(card):
            raise ValueError('missing required card fields')
        if not isinstance(card['id'], str) or not card['id'].strip() or card['id'] in ids:
            raise ValueError('invalid or duplicate id')
        ids.add(card['id'])
        if card['category'] not in CATEGORIES or card['scope'] not in SCOPES:
            raise ValueError('invalid category or scope')
        for field in ('title', 'content', 'version', 'reviewed_at'):
            if not isinstance(card[field], str) or not card[field].strip():
                raise ValueError('invalid ' + field)
        if not isinstance(card['applies_to'], list) or not card['applies_to'] or not all(isinstance(v, str) and v.strip() for v in card['applies_to']):
            raise ValueError('applies_to must contain explicit conditions')
        if card['source_kind'] not in ('authored_method', 'official_summary'):
            raise ValueError('unsupported source kind')
        if card['source_kind'] == 'official_summary':
            url = urlparse(card['source_url'] or '')
            if url.scheme != 'https' or not url.netloc or not card['source_section']:
                raise ValueError('official summary requires https URL and section')
    return cards


def search(cards, query, scope='general', category=None):
    terms = query.lower().split()
    if not terms:
        raise ValueError('query cannot be empty')
    found = []
    for card in cards:
        if scope != 'all' and card['scope'] != scope:
            continue
        if category and card['category'] != category:
            continue
        title = card['title'].lower()
        text = (card['content'] + ' ' + ' '.join(card['applies_to'])).lower()
        score = sum(3 * title.count(t) + text.count(t) for t in terms)
        if score:
            found.append(dict(card, score=score))
    return sorted(found, key=lambda c: (-c['score'], c['id']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    importer = commands.add_parser('import')
    importer.add_argument('source', type=Path)
    importer.add_argument('--output', required=True, type=Path)
    finder = commands.add_parser('search')
    finder.add_argument('index', type=Path)
    finder.add_argument('--query', required=True)
    finder.add_argument('--scope', choices=sorted(SCOPES | {'all'}), default='general')
    finder.add_argument('--category', choices=sorted(CATEGORIES))
    args = parser.parse_args()
    try:
        if args.command == 'import':
            if args.source.absolute() == args.output.absolute():
                raise ValueError('source and output must differ')
            cards = validate(json.loads(args.source.read_text(encoding='utf-8-sig')))
            indexed = [dict(c, content_sha256=hashlib.sha256(c['content'].encode()).hexdigest()) for c in cards]
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temp = args.output.with_name(args.output.name + '.tmp')
            temp.write_text(json.dumps({'schema_version': 1, 'cards': indexed}, ensure_ascii=False, indent=2), encoding='utf-8')
            temp.replace(args.output)
            print(json.dumps({'imported_cards': len(cards), 'output': str(args.output)}, ensure_ascii=False))
        else:
            data = json.loads(args.index.read_text(encoding='utf-8-sig'))
            if data.get('schema_version') != 1:
                raise ValueError('unsupported index version')
            print(json.dumps(search(validate(data['cards']), args.query, args.scope, args.category), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
