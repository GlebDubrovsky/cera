"""Основной алгоритм анализа релевантности страниц и конкурентов."""

from __future__ import annotations

import math
from collections import Counter
from urllib.parse import urlparse

from modules.relevance_analyzer import text_analyzer as ta
from modules.relevance_analyzer.morph import Morphy


def _domain(url: str) -> str:
    """Возвращает hostname без префикса www для колонок вхождений."""
    host = urlparse(url).hostname or url
    return host[4:] if host.lower().startswith('www.') else host


class Relevance:
    """Хранит и вычисляет статистику текста основной страницы и конкурентов."""

    def __init__(self, config: dict[str, object]) -> None:
        self.link = str(config['link'])
        self.phrase = str(config.get('phrase', ''))
        self.competitors = list(config['sites'])
        self.max_word_length = int(config.get('separator', 3))
        self.conjunctions = bool(config.get('conjunctions', False))
        self.list_words = list(config.get('list_words', []))
        self.count = len(self.competitors)
        self.main_page = {
            'html': '', 'default_html': '', 'link_text': '', 'hidden_text': '', 'passages': '',
        }
        self.sites: dict[str, dict[str, object]] = {}
        self.word_forms: dict[str, dict[str, dict[str, object]]] = {}
        self.recommendations: dict[str, dict[str, object]] = {}
        self.phrases: dict[str, dict[str, object]] = {}
        self.ignored_words: list[str] = []
        self.competitors_links = ''
        self.competitors_text = ''
        self.competitors_text_and_links = ''
        self.count_symbols = 0
        self.count_words = 0
        self.count_not_ignored_sites = 0
        self.count_symbols_in_my_page = 0
        self.count_words_in_my_page = 0
        self.avg_coverage_percent = 0
        self.avg: dict[str, float] = {}
        self.morphy = Morphy()

    def run(self) -> Relevance:
        """Запускает последовательно загрузку, нормализацию, статистику и оценки."""
        stages = (
            ('FETCH', self._fetch_pages),
            ('TEXT', self._separate_links_from_text),
            ('FILTER', self._remove_parts_of_speech),
            ('EXCLUSIONS', self._remove_list_words),
            ('CORPUS', self._get_text_from_competitors),
            ('NORMALIZE', self._separate_all_text),
            ('PHRASES', self._prepare_phrases_table),
            ('WORD_FORMS', self._search_word_forms),
            ('STATISTICS', self._processing_of_general_information),
            ('AGGREGATION', self._prepare_unigram_table),
            ('RECOMMENDATIONS', self._analyse_recommendations),
            ('SCORING', self._prepare_analysed_sites_table),
        )
        for stage, process in stages:
            print(f'[RELEVANCE_ANALYZER][{stage}][START] Этап анализа запущен.', flush=True)
            process()
            print(f'[RELEVANCE_ANALYZER][{stage}][SUCCESS] Этап анализа завершён.', flush=True)
        return self

    def _fetch_pages(self) -> None:
        """Загружает целевую страницу и конкурентов; сбои конкурентов частичные."""
        main_html = ta.remove_styles_and_scripts(ta.fetch_html(self.link))
        if not main_html:
            raise ValueError('Не удалось получить целевую страницу.')
        self.main_page['html'] = main_html
        self.main_page['default_html'] = main_html
        for index, url in enumerate(self.competitors, start=1):
            html = ta.remove_styles_and_scripts(ta.fetch_html(url))
            self.sites[url] = {
                'site': url,
                'domain': _domain(url),
                'html': html,
                'default_html': html,
                'danger': html == '',
                'ignored': False,
                'main_page': False,
                'position': index,
                'equally_host': False,
                'link_text': '',
                'hidden_text': '',
                'passages': '',
            }
            status = 'ERROR' if not html else 'SUCCESS'
            print(f'[RELEVANCE_ANALYZER][FETCH][{status}] Обработано страниц конкурентов: {index}/{len(self.competitors)}.', flush=True)
        self.sites[self.link] = {
            'site': self.link,
            'domain': _domain(self.link),
            'html': main_html,
            'default_html': main_html,
            'danger': False,
            'ignored': False,
            'main_page': True,
            'position': 0,
            'equally_host': False,
            'link_text': '',
            'hidden_text': '',
            'passages': '',
        }

    def _separate_links_from_text(self) -> None:
        """Разделяет текст ссылок и основной текст на каждой странице."""
        for page in self.sites.values():
            page['link_text'] = ta.get_link_text(page['html'])
            page['html'] = ta.delete_everything_except_characters(ta.clear_html_from_links(page['html']))
            page['passages'] = ''
            page['hidden_text'] = ''
            if page['main_page']:
                self.main_page.update({
                    'link_text': page['link_text'],
                    'html': page['html'],
                    'passages': page['passages'],
                })

    def _remove_parts_of_speech(self) -> None:
        """Удаляет союзы, предлоги и местоимения, если это выбрано в настройках."""
        if self.conjunctions:
            return
        self.main_page['html'] = ta.remove_conjunctions_prepositions_pronouns(self.main_page['html'])
        self.main_page['link_text'] = ta.remove_conjunctions_prepositions_pronouns(self.main_page['link_text'])
        self.main_page['hidden_text'] = ta.remove_conjunctions_prepositions_pronouns(self.main_page['hidden_text'])
        for page in self.sites.values():
            for field in ('html', 'link_text', 'hidden_text'):
                page[field] = ta.remove_conjunctions_prepositions_pronouns(page[field])

    def _remove_list_words(self) -> None:
        """Применяет исключения пользователя до подсчёта частотности."""
        if not self.list_words:
            return
        joined = '\n'.join(self.list_words)
        for page in self.sites.values():
            for field in ('html', 'link_text', 'hidden_text'):
                page[field] = ta.remove_words(joined, page[field])
            if page['main_page']:
                self.main_page.update({field: page[field] for field in ('html', 'link_text', 'hidden_text')})

    def _get_text_from_competitors(self) -> None:
        """Собирает тексты страниц, участвующие в расчёте частот и покрытия."""
        self.competitors_links = ''
        self.competitors_text = ''
        for page in self.sites.values():
            if not page['ignored']:
                self.competitors_links += ' ' + page['link_text'] + ' '
                self.competitors_text += ' ' + page['hidden_text'] + ' ' + page['html'] + ' '
            page['coverage'] = 0
            page['coverage_tf'] = 0

    def _separate_text(self, text: str) -> str:
        """Исключает слова короче настроенного минимального числа символов."""
        return ' '.join(word for word in text.split(' ') if len(word) >= self.max_word_length)

    def _separate_all_text(self) -> None:
        """Применяет ограничение длины токенов ко всем анализируемым текстам."""
        self.competitors_links = self._separate_text(self.competitors_links)
        self.competitors_text = self._separate_text(self.competitors_text)
        for field in ('html', 'link_text', 'hidden_text'):
            self.main_page[field] = self._separate_text(self.main_page[field])
        self.competitors_text_and_links = ' ' + self.competitors_links + ' ' + self.competitors_text + ' '

    def _search_phrases(self) -> list[str]:
        """Формирует уникальные пары соседних токенов для отчёта TLPs."""
        words = self.competitors_text_and_links.split(' ')
        phrases = [words[index] + ' ' + words[index + 1] for index in range(0, len(words) - 1, 2)]
        return list(dict.fromkeys(phrases))

    def _prepare_phrases_table(self) -> None:
        """Считает частоты биграмм в корпусе и на целевой странице."""
        result = {}
        phrases = self._search_phrases()
        total_count = len(phrases)
        count_sites = max(len(self.sites), 1)
        for phrase in phrases:
            if phrase == '':
                continue
            repeat_spam = number_text = number_link = number_occurrences = 0
            occurrences = {}
            for page in self.sites.values():
                if page['ignored']:
                    continue
                html_count = (' ' + page['html'] + ' ').count(' ' + phrase + ' ')
                hidden_count = (' ' + page['hidden_text'] + ' ').count(' ' + phrase + ' ')
                link_count = (' ' + page['link_text'] + ' ').count(' ' + phrase + ' ')
                number_text += html_count + hidden_count
                number_link += link_count
                if html_count or hidden_count or link_count:
                    count_repeat = html_count + hidden_count + link_count
                    number_occurrences += 1
                    occurrences[page['domain']] = count_repeat
                    repeat_spam = max(repeat_spam, count_repeat)
            count_occurrences = number_text + number_link
            if number_occurrences and total_count and count_occurrences:
                repeat_in_text = (self.main_page['html'] + ' ' + self.main_page['hidden_text']).count(phrase)
                repeat_in_link = self.main_page['link_text'].count(phrase)
                result[phrase] = {
                    'tf': round(count_occurrences / total_count, 6),
                    'idf': round(math.log10(total_count / count_occurrences), 6),
                    'number_occurrences': number_occurrences,
                    're_spam': repeat_spam,
                    'avg_in_total_competitors': int(math.ceil(count_occurrences / count_sites)),
                    'avg_in_link': int(math.ceil(number_link / count_sites)),
                    'avg_in_text': int(math.ceil(number_text / count_sites)),
                    'repeat_in_link_main_page': repeat_in_link,
                    'repeat_in_text_main_page': repeat_in_text,
                    'total_repeat_main_page': repeat_in_link + repeat_in_text,
                    'occurrences': dict(sorted(occurrences.items(), key=lambda item: -item[1])),
                }
        self.phrases = dict(sorted(result.items(), key=lambda item: -item[1]['tf'])[:600])

    def _search_word_forms(self) -> None:
        """Группирует наиболее частые словоформы по нормализованной основе."""
        counter = Counter(self.competitors_text_and_links.split(' '))
        grouped: dict[str, dict[str, int]] = {}
        for word, frequency in sorted(counter.items(), key=lambda item: -item[1]):
            if word in self.ignored_words:
                continue
            self.ignored_words.append(word)
            root = self.morphy.base(word) or word
            grouped.setdefault(root, {})[word] = frequency
            if len(grouped) >= 3500:
                break
        forms = {next(iter(words)): words for words in grouped.values() if words}
        self.word_forms = dict(sorted(forms.items(), key=lambda item: -sum(item[1].values()))[:1000])

    def _processing_of_general_information(self) -> None:
        """Рассчитывает TF-IDF, повторения и встречаемость слов на страницах."""
        count_sites = max(sum(not page['ignored'] for page in self.sites.values()), 1)
        my_text = self.main_page['html'] + ' ' + self.main_page['hidden_text']
        my_text_counts = Counter(my_text.split(' '))
        my_link_counts = Counter(self.main_page['link_text'].split(' '))
        word_count = max(len(self.competitors_text_and_links.split(' ')), 1)
        for root, word_form in list(self.word_forms.items()):
            for word, frequency in list(word_form.items()):
                if word == 'total':
                    continue
                repeat_spam = number_text = number_link = number_passage = 0
                occurrences = {}
                competitor_index = 1
                for page in self.sites.values():
                    if not page['ignored'] and self.count >= competitor_index:
                        html_count = (' ' + page['html'] + ' ').count(' ' + word + ' ')
                        hidden_count = (' ' + page['hidden_text'] + ' ').count(' ' + word + ' ')
                        link_count = (' ' + page['link_text'] + ' ').count(' ' + word + ' ')
                        passage_count = (' ' + page['passages'] + ' ').count(' ' + word + ' ')
                        number_text += html_count + hidden_count
                        number_link += link_count
                        number_passage += passage_count
                        if html_count or hidden_count or link_count or passage_count:
                            count_repeat = html_count + hidden_count + link_count + passage_count
                            occurrences[page['domain']] = count_repeat
                            repeat_spam = max(repeat_spam, count_repeat)
                        competitor_index += 1
                occurrences = dict(sorted(occurrences.items(), key=lambda item: -item[1]))
                repeat_in_text = my_text_counts.get(word, 0)
                repeat_in_link = my_link_counts.get(word, 0)
                word_form[word] = {
                    'tf': round(frequency / word_count, 7),
                    'idf': round(math.log10(word_count / frequency), 7),
                    'number_occurrences': len(occurrences),
                    're_spam': repeat_spam,
                    'avg_in_total_competitors': int(math.ceil((number_link + number_text) / count_sites)),
                    'avg_in_link': int(math.ceil(number_link / count_sites)),
                    'avg_in_text': int(math.ceil(number_text / count_sites)),
                    'avg_in_passages': int(math.ceil(number_passage / count_sites)),
                    'repeat_in_link_main_page': repeat_in_link,
                    'repeat_in_text_main_page': repeat_in_text,
                    'repeat_in_passages_main_page': 0,
                    'total_repeat_main_page': repeat_in_link + repeat_in_text,
                    'occurrences': occurrences,
                }

    def _prepare_unigram_table(self) -> None:
        """Суммирует метрики всех словоформ в одну запись для каждой основы."""
        for word_form in self.word_forms.values():
            tf = idf = avg_total = avg_link = avg_text = avg_passages = 0.0
            repeat_text = repeat_link = repeat_passages = repeat_spam = 0
            occurrences: dict[str, int] = {}
            danger = False
            for word in word_form.values():
                danger = danger or word['repeat_in_text_main_page'] == 0 or word['repeat_in_link_main_page'] == 0
                tf += word['tf']
                idf += word['idf']
                avg_total += word['avg_in_total_competitors']
                avg_link += word['avg_in_link']
                avg_text += word['avg_in_text']
                avg_passages += word['avg_in_passages']
                repeat_text += word['repeat_in_text_main_page']
                repeat_link += word['repeat_in_link_main_page']
                repeat_passages += word['repeat_in_passages_main_page']
                repeat_spam = max(repeat_spam, word['re_spam'])
                for domain, count in word['occurrences'].items():
                    occurrences[domain] = occurrences.get(domain, 0) + count
            word_form['total'] = {
                'tf': tf,
                'idf': idf,
                'number_occurrences': len(occurrences),
                're_spam': repeat_spam,
                'avg_in_total_competitors': avg_total,
                'avg_in_link': avg_link,
                'avg_in_text': avg_text,
                'avg_in_passages': avg_passages,
                'repeat_in_link_main_page': repeat_link,
                'repeat_in_text_main_page': repeat_text,
                'repeat_in_passages_main_page': repeat_passages,
                'total_repeat_main_page': repeat_text + repeat_link + repeat_passages,
                'danger': danger,
                'occurrences': dict(sorted(occurrences.items(), key=lambda item: -item[1])),
            }

    def _analyse_recommendations(self) -> None:
        """Сравнивает частоту на целевой странице с диапазоном конкурентов."""
        for word_form in self.word_forms.values():
            total = word_form['total']
            for word, form in word_form.items():
                if word == 'total':
                    continue
                average = total['avg_in_total_competitors']
                if average >= 10:
                    recommendation_min = int(math.ceil(average * 0.9))
                    recommendation_max = int(math.ceil(average * 1.1))
                elif average >= 2:
                    recommendation_min = average - 1
                    recommendation_max = average + 1
                else:
                    recommendation_min, recommendation_max = 1, 2
                total_repeat = total['total_repeat_main_page']
                if total_repeat < recommendation_min:
                    self.recommendations[word] = {
                        'tf': round(total['tf'], 5), 'avg': average, 'on_page': total_repeat,
                        'diapason': f'{recommendation_min} - {recommendation_max}', 'spam': 0,
                        'add': f'{recommendation_min - total_repeat} - {recommendation_max - total_repeat}',
                        'remove': 0,
                    }
                    break
                if total_repeat > recommendation_max:
                    self.recommendations[word] = {
                        'tf': round(total['tf'], 5), 'avg': average, 'on_page': total_repeat,
                        'diapason': f'{recommendation_min} - {recommendation_max}',
                        'spam': str(round((total_repeat - recommendation_max) / (recommendation_max / 100))) + '%',
                        'add': 0,
                        'remove': f'{total_repeat - recommendation_max} - {total_repeat - recommendation_min}',
                    }
                    break

    def _prepare_analysed_sites_table(self) -> None:
        """Готовит показатели покрытия, плотности, ширины и балла страниц."""
        self._calculate_density()
        self._calculate_coverage_points()
        self._calculate_width_points()
        self._calculate_total_points()
        self._calculate_text_info()
        self._calculate_avg()

    def _calculate_density(self) -> None:
        for page in self.sites.values():
            all_text = page['html'] + ' ' + page['link_text'] + ' ' + page['hidden_text']
            page['density'] = self._calculate_density_points(all_text)

    def _calculate_density_points(self, text: str) -> dict[str, int]:
        """Оценивает плотность важных слов относительно среднего конкурентов."""
        words = Counter(text.split(' '))
        density_main = 0.0
        for word_form in self.word_forms.values():
            for word in word_form:
                if word == 'total':
                    continue
                if word in words:
                    count_repeat = sum(words.get(form_word, 0) for form_word in word_form if form_word != 'total')
                    average = word_form['total']['avg_in_total_competitors']
                    density_main += min(count_repeat / (average / 100), 100) if average else 0
                    break
        return {'density_main': min(round(density_main), 100), 'density_main_percent': round(density_main / 1000)}

    def _calculate_coverage_points(self) -> None:
        total_tf = sum(word_form['total']['tf'] for word_form in self.word_forms.values())
        for page in self.sites.values():
            text = page['html'] + ' ' + page['link_text'] + ' ' + page['hidden_text']
            coverage = self._calculate_coverage(text)
            page['coverage'] = round(coverage['text'] / 10, 2)
            page['coverage_tf'] = round(coverage['tf'] / (total_tf / 100), 2) if total_tf else 0

    def _calculate_coverage(self, text: str) -> dict[str, float | int]:
        """Считает число покрытых основ и сумму их TF на странице."""
        covered = 0
        tf = 0.0
        for word_form in self.word_forms.values():
            for word, form in word_form.items():
                if word != 'total' and (' ' + word + ' ') in text:
                    covered += 1
                    break
        for word_form in self.word_forms.values():
            for word, form in word_form.items():
                if word != 'total' and (' ' + word + ' ') in text:
                    tf += form['tf']
        return {'text': covered, 'tf': tf}

    def _calculate_width_points(self) -> None:
        coverage_total = 0.0
        count = 0
        for page in self.sites.values():
            if not page['ignored']:
                if count == 10:
                    break
                coverage_total += page['coverage']
                count += 1
        average_coverage = coverage_total / 10 if coverage_total else 0
        self.avg_coverage_percent = average_coverage
        for page in self.sites.values():
            points = page['coverage'] / (average_coverage / 100) if average_coverage else 0
            page['width'] = round(min(points, 100), 2)

    def _calculate_total_points(self) -> None:
        for page in self.sites.values():
            points = page['coverage'] + page['coverage_tf'] + page['density']['density_main_percent']
            page['main_points'] = min(round((points / 3) * 2, 2), 100)

    def _calculate_text_info(self) -> None:
        self.count_symbols = self.count_words = self.count_not_ignored_sites = 0
        self.count_symbols_in_my_page = self.count_words_in_my_page = 0
        for page in self.sites.values():
            text = ta.delete_everything_except_characters(page['default_html'])
            symbol_count = len(text)
            word_count = len(text.split(' '))
            if page['main_page']:
                self.count_symbols_in_my_page = symbol_count
                self.count_words_in_my_page = word_count
            elif not page['ignored']:
                self.count_not_ignored_sites += 1
                self.count_symbols += symbol_count
                self.count_words += word_count
            page['count_symbols'] = max(symbol_count, 0)

    def _calculate_avg(self) -> None:
        """Сохраняет средние показатели пяти лучших страниц для сводного отчёта."""
        metrics = {
            'coverage': [page['coverage'] for page in self.sites.values()],
            'coverage_tf': [page['coverage_tf'] for page in self.sites.values()],
            'density': [page['density']['density_main_percent'] for page in self.sites.values()],
            'width': [page['width'] for page in self.sites.values()],
            'points': [page['main_points'] for page in self.sites.values()],
            'count_symbols': [page['count_symbols'] for page in self.sites.values()],
        }
        self.avg = {}
        for name, values in metrics.items():
            values.sort(reverse=True)
            self.avg[name] = sum(values[:5]) / 5
