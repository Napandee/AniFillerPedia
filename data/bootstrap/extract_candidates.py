import json
import re

with open('/tmp/afp-bootstrap/aod-full.json') as f:
    data = json.load(f)['data']


def extract_id(sources, pattern):
    for s in sources:
        m = re.search(pattern, s)
        if m:
            return int(m.group(1))
    return None


candidates = []
for e in data:
    tags = e.get('tags', [])
    matched = [t for t in tags if t in ('has fillers', 'canon filler')]
    if not matched:
        continue
    sources = e.get('sources', [])
    candidates.append({
        'title': e.get('title'),
        'synonyms': e.get('synonyms', []),
        'anilist_id': extract_id(sources, r'anilist\.co/anime/(\d+)'),
        'mal_id': extract_id(sources, r'myanimelist\.net/anime/(\d+)'),
        'anidb_id': extract_id(sources, r'anidb\.net/anime/(\d+)'),
        'kitsu_id': extract_id(sources, r'kitsu\.(?:io|app)/anime/(\d+)'),
        'matched_tags': matched,
        'episode_count': e.get('episodes'),
        'type': e.get('type'),
        'provenance': 'manami_bootstrap',
        'source_release': '2026-27',
    })

print('Total matched:', len(candidates))
has_fillers = sum(1 for c in candidates if 'has fillers' in c['matched_tags'])
canon_filler = sum(1 for c in candidates if 'canon filler' in c['matched_tags'])
both = sum(1 for c in candidates if len(c['matched_tags']) == 2)
print('has fillers:', has_fillers, '| canon filler:', canon_filler, '| both tags:', both)

with_anilist = sum(1 for c in candidates if c['anilist_id'])
with_mal = sum(1 for c in candidates if c['mal_id'])
with_synonyms = sum(1 for c in candidates if c['synonyms'])
print('with anilist_id:', with_anilist, '| with mal_id:', with_mal, '| with synonyms:', with_synonyms)

out_path = '/var/home/abrantholm/anifillerpedia/.claude/worktrees/agent-a4abefa557e1a2131/data/bootstrap/series-candidates.json'
with open(out_path, 'w') as f:
    json.dump(candidates, f, indent=2, ensure_ascii=False)
print('wrote', out_path)
