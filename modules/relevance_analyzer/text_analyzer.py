"""Извлечение текста из HTML и безопасная загрузка публичных страниц."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from modules.relevance_analyzer import stopwords

_ONLY_LETTERS_SPLIT = re.compile(r'[^a-zA-ZА-Яа-яЁё]+')
_WHITESPACE = re.compile(r'\s+')
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5


class UnsafePageURL(ValueError):
    """URL не указывает на общедоступную HTTP(S)-страницу."""


def delete_everything_except_characters(html: str) -> str:
    """Удаляет разметку и оставляет слова из латиницы и кириллицы."""
    if not html:
        return ''
    html = html.replace('><', '> <').replace('&nbsp;', ' ')
    soup = BeautifulSoup(html, 'lxml')
    text = soup.get_text()
    parts = _ONLY_LETTERS_SPLIT.split(text)
    return ' '.join(part for part in parts if part)


def remove_styles_and_scripts(html: str) -> str:
    """Исключает из анализируемого HTML код и элементы без текстового вклада."""
    if not html:
        return ''
    soup = BeautifulSoup(html.lower(), 'lxml')
    for tag in ('script', 'link', 'style', 'path', 'noscript', 'svg', 'img', 'title'):
        for element in soup.find_all(tag):
            element.decompose()
    return str(soup)


def get_link_text(html: str) -> str:
    """Извлекает и очищает видимый текст ссылок."""
    if not html:
        return ''
    soup = BeautifulSoup(html, 'lxml')
    parts = [anchor.get_text() for anchor in soup.find_all('a') if anchor.get_text().strip()]
    return delete_everything_except_characters(' '.join(parts))


def clear_html_from_links(html: str) -> str:
    """Убирает anchor-теги, чтобы их текст учитывался отдельно."""
    if not html:
        return ''
    html = html.replace('article', 'div')
    html = _WHITESPACE.sub(' ', html)
    soup = BeautifulSoup(html, 'lxml')
    for anchor in soup.find_all('a'):
        anchor.decompose()
    return str(soup)


def remove_conjunctions_prepositions_pronouns(text: str) -> str:
    """Удаляет известные стоп-слова из нормализованного текста."""
    if not text:
        return ''
    for word in stopwords.ALL:
        text = text.replace(' ' + word + ' ', ' ')
    return text


def remove_words(list_words: str, text: str) -> str:
    """Удаляет заданные пользователем слова как отдельные токены."""
    if not list_words:
        return text
    normalized_words = list_words.replace('\r\n', '\n').replace('\r', '\n').lower()
    for word in normalized_words.split('\n'):
        word = word.strip()
        if word:
            text = text.replace(' ' + word + ' ', ' ')
            text = _WHITESPACE.sub(' ', text)
    return text.strip()


def _validate_public_url(url: str) -> str:
    """Разрешает HTTP(S) только к доменам, разрешающимся в публичные IP-адреса.

    Проверка выполняется для каждого шага редиректа: URL от пользователя не
    должен позволять сканировать loopback, private, link-local или служебные сети.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise UnsafePageURL('Допустимы только публичные URL с протоколом HTTP или HTTPS.')
    try:
        addresses = {record[4][0] for record in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise UnsafePageURL('URL должен вести только на общедоступный хост.')
    except (OSError, ValueError) as error:
        if isinstance(error, UnsafePageURL):
            raise
        raise UnsafePageURL('Не удалось проверить адрес страницы.') from None
    return url


def fetch_html(url: str, session: requests.Session | None = None) -> str:
    """Загружает страницу без автоматических редиректов на непроверенные адреса.

    Ошибка отдельного сайта превращается в пустой результат, чтобы анализатор
    мог сохранить отчёт по оставшимся сайтам; в журнал попадает только тип ошибки.
    """
    owns_session = session is None
    client = session or requests.Session()
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
            '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
    }
    current_url = url
    try:
        for redirect_number in range(_MAX_REDIRECTS + 1):
            _validate_public_url(current_url)
            response = client.get(
                current_url,
                headers=headers,
                timeout=20,
                allow_redirects=False,
            )
            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get('Location')
                response.close()
                if not location or redirect_number == _MAX_REDIRECTS:
                    return ''
                current_url = urljoin(current_url, location)
                continue

            response.raise_for_status()
            if 'pdf' in response.headers.get('Content-Type', '').lower():
                return ''
            if response.encoding and response.encoding.lower() != 'utf-8':
                response.encoding = response.apparent_encoding or response.encoding
            return response.text
        return ''
    except Exception as error:
        print(f'[RELEVANCE_ANALYZER][FETCH][ERROR] Загрузка страницы завершилась ошибкой ({type(error).__name__}).', flush=True)
        return ''
    finally:
        if owns_session:
            client.close()
