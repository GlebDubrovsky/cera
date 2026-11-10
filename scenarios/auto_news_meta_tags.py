"""Сценарий подготовки метатегов новостей через общий сборщик и OpenAI API."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from modules.openai_api import (
    OpenAIAPIError,
    OpenAIConfigurationError,
    OpenAIInputError,
    chat_completion,
)
from shared.page_content import PageFetchError, PageInputError, fetch_page_content
from shared.prompt_templates import PromptTemplateError, load_prompt_template, render_prompt_template

MAX_URLS_PER_RUN = 50
PROMPT_TEMPLATE_NAME = 'auto_news_meta_tags.md'


class AutoNewsInputError(ValueError):
    """Список URL не соответствует контракту сценария."""


@dataclass(frozen=True)
class AutoNewsMetaTagsResult:
    """Результат обработки одного URL: ответ модели или краткая ошибка."""

    url: str
    title: str
    answer: str
    error: str


def _normalize_urls(urls: Sequence[str]) -> list[str]:
    if isinstance(urls, (str, bytes)) or not isinstance(urls, Sequence):
        raise AutoNewsInputError('Передай список URL, по одному на строку.')
    normalized = [url.strip() for url in urls if isinstance(url, str) and url.strip()]
    if len(normalized) != len(urls):
        raise AutoNewsInputError('Каждая заполненная строка должна содержать URL.')
    if not normalized or len(normalized) > MAX_URLS_PER_RUN:
        raise AutoNewsInputError(f'Укажи от 1 до {MAX_URLS_PER_RUN} URL.')
    return normalized


def run_auto_news_meta_tags(urls: Sequence[str]) -> list[AutoNewsMetaTagsResult]:
    """Собирает новости, заполняет общий промпт и запрашивает метатеги у модели.

    Сценарий вызывается напрямую из Python или через адаптер интерфейса. Ошибка
    отдельной страницы не прекращает пакет; глобальная ошибка конфигурации API
    завершает запуск, поскольку дальнейшие запросы в той же конфигурации не помогут.
    """
    normalized_urls = _normalize_urls(urls)
    template = load_prompt_template(PROMPT_TEMPLATE_NAME)
    print(
        f'[AUTO_NEWS][START][SUCCESS] Запуск обработки страниц: {len(normalized_urls)}.',
        flush=True,
    )
    results: list[AutoNewsMetaTagsResult] = []

    for index, url in enumerate(normalized_urls, start=1):
        print(f'[AUTO_NEWS][PAGE][START] Обработка страницы {index}/{len(normalized_urls)}.', flush=True)
        title = ''
        try:
            page = fetch_page_content(url)
            title = page.title
            prompt = render_prompt_template(template, {'title': page.title, 'content': page.content})
            response = chat_completion([{'role': 'user', 'content': prompt}])
            choices = response.get('choices')
            answer = choices[0].get('message', {}).get('content') if choices else None
            if not isinstance(answer, str) or not answer.strip():
                raise OpenAIAPIError('Модель вернула пустой ответ.')
            results.append(AutoNewsMetaTagsResult(url=url, title=title, answer=answer.strip(), error=''))
            print(f'[AUTO_NEWS][PAGE][SUCCESS] Страница {index}/{len(normalized_urls)} обработана.', flush=True)
        except OpenAIConfigurationError:
            print('[AUTO_NEWS][CONFIG][FAILURE] Конфигурация OpenAI API недоступна.', flush=True)
            raise
        except (PageFetchError, PageInputError) as error:
            print(f'[AUTO_NEWS][COLLECT][FAILURE] Страница {index}/{len(normalized_urls)}: {type(error).__name__}.', flush=True)
            results.append(AutoNewsMetaTagsResult(url=url, title=title, answer='', error='Не удалось собрать данные со страницы.'))
        except (OpenAIAPIError, OpenAIInputError, PromptTemplateError) as error:
            print(f'[AUTO_NEWS][GENERATE][FAILURE] Страница {index}/{len(normalized_urls)}: {type(error).__name__}.', flush=True)
            results.append(AutoNewsMetaTagsResult(url=url, title=title, answer='', error='Не удалось сформировать метатеги.'))
        except Exception as error:
            print(f'[AUTO_NEWS][PAGE][FAILURE] Страница {index}/{len(normalized_urls)}: {type(error).__name__}.', flush=True)
            results.append(AutoNewsMetaTagsResult(url=url, title=title, answer='', error='Не удалось обработать страницу.'))

    successful_count = sum(bool(result.answer) for result in results)
    print(
        f'[AUTO_NEWS][TOTALS][SUCCESS] Успешно: {successful_count}; с ошибками: {len(results) - successful_count}.',
        flush=True,
    )
    return results
