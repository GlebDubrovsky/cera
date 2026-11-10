"""Безопасная загрузка HTML-страниц и извлечение выбранных текстовых областей."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests import Response
from soupsieve import SelectorSyntaxError

REQUEST_TIMEOUT_SECONDS = 15
MAX_REDIRECTS = 5
MAX_PAGE_BYTES = 3_000_000
USER_AGENT = 'Mozilla/5.0 (compatible; CeraPageFetcher/1.0)'


class PageFetchError(RuntimeError):
    """Страница не загрузилась или не содержит запрошенные данные."""


class PageInputError(ValueError):
    """URL или CSS-селектор не соответствует контракту загрузчика."""


@dataclass(frozen=True)
class PageContent:
    """Извлечённые заголовок и основной текст страницы."""

    title: str
    content: str


def _validate_public_url(value: object) -> str:
    """Разрешает только публичные HTTP(S)-адреса, включая адреса после редиректа."""
    if not isinstance(value, str) or not value.strip() or len(value) > 2048 or any(char.isspace() for char in value):
        raise PageInputError('Укажи корректный публичный URL страницы.')
    parsed = urlparse(value.strip())
    try:
        port = parsed.port
    except ValueError:
        raise PageInputError('В URL указан некорректный порт.') from None
    hostname = parsed.hostname
    if parsed.scheme not in {'http', 'https'} or not hostname or parsed.username or parsed.password:
        raise PageInputError('Разрешены только публичные URL с протоколом HTTP или HTTPS.')
    if port is not None and not 1 <= port <= 65535:
        raise PageInputError('В URL указан некорректный порт.')

    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            addresses = [
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(hostname, port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
            ]
        except (OSError, ValueError):
            raise PageFetchError('Не удалось определить публичный адрес сайта.') from None
    if not addresses or any(not address.is_global for address in addresses):
        raise PageInputError('Загрузка внутренних и непубличных адресов запрещена.')
    return value.strip()


def _read_limited_response(response: Response) -> bytes:
    """Ограничивает объём тела ответа, чтобы большой документ не исчерпал память."""
    content_length = response.headers.get('Content-Length')
    if content_length and content_length.isdigit() and int(content_length) > MAX_PAGE_BYTES:
        raise PageFetchError('Размер страницы превышает допустимый предел.')
    body = bytearray()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) > MAX_PAGE_BYTES:
            raise PageFetchError('Размер страницы превышает допустимый предел.')
    return bytes(body)


def _request_html(url: str) -> str:
    """Выполняет загрузку с ручной проверкой каждого перехода и ограниченным телом."""
    current_url = url
    for redirect_index in range(MAX_REDIRECTS + 1):
        current_url = _validate_public_url(current_url)
        try:
            with requests.get(
                current_url,
                headers={'User-Agent': USER_AGENT},
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
                stream=True,
            ) as response:
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get('Location')
                    if not location or redirect_index == MAX_REDIRECTS:
                        raise PageFetchError('Сайт перенаправляет на недопустимый адрес.')
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get('Content-Type', '').lower()
                if content_type and 'html' not in content_type:
                    raise PageFetchError('Сайт вернул документ не в формате HTML.')
                body = _read_limited_response(response)
                encoding = response.encoding or 'utf-8'
                return body.decode(encoding, errors='replace')
        except PageFetchError:
            raise
        except requests.RequestException as error:
            raise PageFetchError(f'Не удалось загрузить страницу ({type(error).__name__}).') from None
        except (LookupError, UnicodeError):
            raise PageFetchError('Не удалось декодировать HTML страницы.') from None
    raise PageFetchError('Превышено допустимое количество перенаправлений.')


def fetch_page_content(
    url: str,
    *,
    title_selector: str = 'h1',
    content_selector: str = 'div.main-text',
    max_content_characters: int = 50_000,
) -> PageContent:
    """Загружает страницу и извлекает текст по переданным CSS-селекторам.

    Публичный общий контракт позволяет возможностям переиспользовать загрузку,
    задавая собственные селекторы заголовка и содержимого без зависимости от UI.
    Внешние редиректы проверяются до перехода, а размер ответа и текста ограничен.
    """
    if not isinstance(title_selector, str) or not title_selector.strip():
        raise PageInputError('CSS-селектор заголовка не должен быть пустым.')
    if not isinstance(content_selector, str) or not content_selector.strip():
        raise PageInputError('CSS-селектор содержимого не должен быть пустым.')
    if isinstance(max_content_characters, bool) or not isinstance(max_content_characters, int) or not 1 <= max_content_characters <= 100_000:
        raise PageInputError('Лимит текста страницы должен быть от 1 до 100000 символов.')

    html = _request_html(url)
    try:
        document = BeautifulSoup(html, 'html.parser')
        title_element = document.select_one(title_selector)
        content_element = document.select_one(content_selector)
    except SelectorSyntaxError:
        raise PageInputError('Передан некорректный CSS-селектор.') from None
    if title_element is None or content_element is None:
        raise PageFetchError('На странице не найдены заголовок или основной текст.')
    for non_content_element in content_element.select('script, style, noscript, template, svg, iframe'):
        non_content_element.decompose()
    title = title_element.get_text(' ', strip=True)
    content = ' '.join(content_element.stripped_strings)
    if not title or not content:
        raise PageFetchError('На странице пустой заголовок или основной текст.')
    return PageContent(title=title[:500], content=content[:max_content_characters])
