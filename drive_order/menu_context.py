"""Store-scoped alias and conservative ASR candidate hints; never rewrite evidence."""
import copy
import re
from difflib import SequenceMatcher

COMMON_ALIASES = {
    '아이스아메리카노': ['아아'],
    '아이스티샷추가': ['아샷추'],
    '감자튀김': ['감튀'],
}

def compact(text):
    return re.sub(r'\s+', '', text)

def prepare_menu(menu):
    result = copy.deepcopy(menu)
    for item in result['items']:
        aliases = list(item.get('aliases', []))
        names = {compact(s) for s in [item['name']] + aliases}
        for name, additions in COMMON_ALIASES.items():
            # Exact catalogue match only: never turn a burger set into fries,
            # or assume that a plain iced tea offers an espresso-shot option.
            if name in names:
                aliases.extend(a for a in additions if a not in aliases)
        item['aliases'] = aliases
    return result

def menu_hints(text, menu):
    menu = prepare_menu(menu)
    forms = {}
    for item in menu['items']:
        for name in [item['name']] + item.get('aliases', []):
            forms.setdefault(compact(name), set()).add(item['id'])
    hints = []
    # Word boundaries avoid matching 아아 inside another word. Allow Korean particles.
    for token in re.findall(r'[가-힣A-Za-z]+', text):
        word = re.sub(r'(으로|이랑|하고|주세요|로|을|를|은|는|요)$', '', token)
        exact = forms.get(token) or forms.get(word)
        if exact:
            hints.append({'heard': token, 'kind': 'catalogue_alias', 'menu_ids': sorted(exact), 'ambiguous': len(exact) > 1})
            continue
        if len(word) < 4:
            continue
        scores = {}
        for form, ids in forms.items():
            if len(form) < 4 or abs(len(form)-len(word)) > 1:
                continue
            similarity = SequenceMatcher(None, word, form).ratio()
            if similarity >= .8:
                for mid in ids:
                    scores[mid] = max(similarity, scores.get(mid, 0))
        if scores:
            ranked = sorted(scores, key=lambda mid: (-scores[mid], mid))
            best = scores[ranked[0]]
            candidates = [mid for mid in ranked if best-scores[mid] < .1]
            hints.append({'heard': token, 'kind': 'possible_asr_typo', 'menu_ids': candidates, 'ambiguous': len(candidates) > 1})
    return hints
