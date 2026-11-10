"""Offline tests for shared prompt/page utilities and the auto-news scenario."""

from __future__ import annotations

import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks, HTTPException

from api.routers import auto_news_meta_tags as web
from modules.openai_api import OpenAIConfigurationError
from scenarios.auto_news_meta_tags import (
    AutoNewsInputError,
    run_auto_news_meta_tags,
)
from shared.page_content import PageContent, PageFetchError, PageInputError, fetch_page_content
from shared.prompt_templates import PromptTemplateError, load_prompt_template, render_prompt_template


class PromptTemplateTests(unittest.TestCase):
    def test_loads_shared_news_prompt_and_substitutes_page_data(self) -> None:
        template = load_prompt_template('auto_news_meta_tags.md')
        rendered = render_prompt_template(template, {'title': 'Заголовок', 'content': 'Текст новости'})
        self.assertIn('«Заголовок»', rendered)
        self.assertIn('Текст новости', rendered)
        self.assertNotIn('{{title}}', rendered)

    def test_rejects_missing_and_unsafe_template_variables(self) -> None:
        with self.assertRaises(PromptTemplateError):
            render_prompt_template('Заголовок: {{title}}', {})
        with self.assertRaises(PromptTemplateError):
            load_prompt_template('../outside.md')


class PageContentTests(unittest.TestCase):
    def test_extracts_text_from_configurable_selectors(self) -> None:
        html = '<h2>Заголовок</h2><article><script>не текст</script><p>Первая часть</p><p>Вторая часть</p></article>'
        with patch('shared.page_content._request_html', return_value=html):
            page = fetch_page_content('https://example.com/news', title_selector='h2', content_selector='article')
        self.assertEqual(page, PageContent('Заголовок', 'Первая часть Вторая часть'))

    def test_rejects_private_ip_urls_before_request(self) -> None:
        with self.assertRaises(PageInputError):
            fetch_page_content('http://127.0.0.1/admin')

    def test_rejects_empty_selected_content(self) -> None:
        with patch('shared.page_content._request_html', return_value='<h1>Title</h1>'):
            with self.assertRaises(PageFetchError):
                fetch_page_content('https://example.com/news')


class AutoNewsScenarioTests(unittest.TestCase):
    def test_continues_after_page_failure_and_generates_for_remaining_url(self) -> None:
        page = PageContent(title='Новости GEELY', content='Описание новости')
        with patch('scenarios.auto_news_meta_tags.fetch_page_content', side_effect=[PageFetchError('blocked'), page]), \
                patch('scenarios.auto_news_meta_tags.chat_completion', return_value={
                    'choices': [{'message': {'content': 'Description\n1. Текст\nKeywords\n1. слова'}}],
                }) as completion, redirect_stdout(StringIO()):
            results = run_auto_news_meta_tags(['https://first.example/news', 'https://second.example/news'])
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0].error)
        self.assertEqual(results[1].title, 'Новости GEELY')
        self.assertIn('Description', results[1].answer)
        prompt = completion.call_args.args[0][0]['content']
        self.assertIn('Новости GEELY', prompt)
        self.assertIn('Описание новости', prompt)

    def test_validates_url_count_before_loading_services(self) -> None:
        with self.assertRaises(AutoNewsInputError):
            run_auto_news_meta_tags([])

    def test_stops_when_global_openai_configuration_is_missing(self) -> None:
        page = PageContent(title='News', content='Body')
        with patch('scenarios.auto_news_meta_tags.fetch_page_content', return_value=page), \
                patch('scenarios.auto_news_meta_tags.chat_completion', side_effect=OpenAIConfigurationError('missing')), \
                redirect_stdout(StringIO()):
            with self.assertRaises(OpenAIConfigurationError):
                run_auto_news_meta_tags(['https://example.com/news'])


class AutoNewsRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_returns_download_link_and_partial_failure_count(self) -> None:
        request_id = '123e4567-e89b-12d3-a456-426614174000'
        with patch('api.routers.auto_news_meta_tags.run_with_log_capture', return_value=(request_id, 2, 1)):
            response = await web.submit_auto_news_meta_tags(
                links_text='https://one.example/\n\nhttps://two.example/', log_id='',
            )
        body = response.body.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn('/download/auto-landings/meta-tags-news/' + request_id, body)
        self.assertIn('Ошибок: 1', body)

    async def test_job_creates_separate_text_entries_named_from_titles(self) -> None:
        results = [
            SimpleNamespace(title='Новость / GEELY', answer='Ответ один'),
            SimpleNamespace(title='Новость / GEELY', answer='Ответ два'),
            SimpleNamespace(title='Без ответа', answer=''),
        ]
        with tempfile.TemporaryDirectory() as directory, \
                patch('api.routers.auto_news_meta_tags.run_auto_news_meta_tags', return_value=results), \
                patch('api.routers.auto_news_meta_tags.manage_temp_dir', return_value=directory), \
                redirect_stdout(StringIO()):
            request_id, success_count, failed_count = web._run_job(['https://example.com/'])
            self.assertIsNotNone(request_id)
            self.assertEqual((success_count, failed_count), (2, 1))
            with zipfile.ZipFile(Path(directory) / 'result.zip') as archive:
                self.assertEqual(len(archive.namelist()), 2)
                self.assertTrue(archive.namelist()[0].startswith('Новость _ GEELY'))
                self.assertNotEqual(archive.namelist()[0], archive.namelist()[1])
                self.assertEqual(archive.read(archive.namelist()[0]).decode(), 'Ответ один')

    async def test_download_rejects_invalid_identifier(self) -> None:
        with self.assertRaises(HTTPException):
            await web.download_auto_news_result('not-a-uuid', BackgroundTasks())


if __name__ == '__main__':
    unittest.main()
