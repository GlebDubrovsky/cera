"""Морфологическая нормализация слов для русского и латинского текста."""

import re

try:
    import pymorphy3

    _MORPH = pymorphy3.MorphAnalyzer()
except Exception:  # pragma: no cover - словарь может отсутствовать в окружении
    _MORPH = None

_RUSSIAN = re.compile(r'[а-яё]', re.IGNORECASE)

_PERSPECTIVE_GROUND = re.compile(
    r'((ив|ивши|ившись|ыв|ывши|ывшись)|((?<=[ая])(в|вши|вшись)))$'
)
_REFLEXIVE = re.compile(r'(с[яь])$')
_ADJECTIVE = re.compile(
    r'(ее|ие|ые|ое|ими|ыми|ей|ий|ый|ой|ем|им|ым|ом|его|ого|еых|ую|юю|ая|яя|ою|ею|их)$'
)
_PARTICIPLE = re.compile(r'((ивш|ывш|ующ)|((?<=[ая])(ем|нн|вш|ющ|щ)))$')
_VERB = re.compile(
    r'((ила|ыла|ена|ейте|уйте|ите|или|ыли|ей|уй|ил|ыл|им|ым|ены|ить|ыть|ишь|ую|ю)'
    r'|((?<=[ая])(ла|на|ете|йте|ли|й|л|ем|н|ло|но|ет|ют|ны|ть|ешь|нно)))$'
)
_NOUN = re.compile(
    r'(а|ев|ов|ие|ье|е|иями|ями|ами|еи|ии|и|ией|ей|ой|ий|й|ы|ь|ию|ью|ю|ия|ья|я)$'
)
_RARE = re.compile(r'^(.*?[аеиоуыэюя])(.*)$')
_DERIVATION = re.compile(r'[^аеиоуыэюя][аеиоуыэюя]+[^аеиоуыэюя]+[аеиоуыэюя].*(?<=о)сть?$')


def _sub(rv: str, pattern: re.Pattern[str], repl: str) -> tuple[str, bool]:
    new = pattern.sub(repl, rv)
    return new, new != rv


def russian_stem(word: str) -> str:
    """Возвращает основу слова резервным русским стеммером Портера."""
    stem = word
    match = _RARE.match(word)
    if not match:
        return stem
    start, rv = match.groups()
    if not rv or len(rv) <= 3:
        return stem

    rv, changed = _sub(rv, _PERSPECTIVE_GROUND, '')
    if not changed:
        rv, _ = _sub(rv, _REFLEXIVE, '')
        rv, changed_adjective = _sub(rv, _ADJECTIVE, '')
        if changed_adjective:
            rv, _ = _sub(rv, _PARTICIPLE, '')
        else:
            rv, changed_verb = _sub(rv, _VERB, '')
            if not changed_verb:
                rv, _ = _sub(rv, _NOUN, '')

    rv, _ = _sub(rv, re.compile(r'и$'), '')
    if _DERIVATION.search(rv):
        rv, _ = _sub(rv, re.compile(r'ость?$'), '')
    rv, changed_soft = _sub(rv, re.compile(r'ь$'), '')
    if not changed_soft:
        rv, _ = _sub(rv, re.compile(r'ейше?$'), '')
        rv, _ = _sub(rv, re.compile(r'нн$'), 'н')
    return start + rv


class Morphy:
    """Кеширует pymorphy3-разборы и использует стеммер как резервный вариант."""

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    def base(self, word: str) -> str:
        word = (word or '').strip()
        if not word:
            return word
        if word not in self._cache:
            self._cache[word] = self._base(word)
        return self._cache[word]

    def _base(self, word: str) -> str:
        low = word.lower()
        if not _RUSSIAN.search(low):
            return low
        if _MORPH is not None:
            try:
                parsed = _MORPH.parse(low)
                if parsed:
                    return parsed[0].normal_form
            except Exception:
                pass
        return russian_stem(low)
