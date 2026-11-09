"""Offline tests for relevance-analysis input, execution, exports and HTTP adapter."""

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
from openpyxl import load_workbook

from api.routers import relevance_analyzer as web
from modules.relevance_analyzer.config_input import parse_config, parse_txt
from modules.relevance_analyzer.export import export_xlsx
from modules.relevance_analyzer.service import RelevanceInputError, run_analysis, validate_config
from modules.relevance_analyzer.text_analyzer import UnsafePageURL, fetch_html


class RelevanceInputTests(unittest.TestCase):
    def test_parses_original_text_format(self) -> None:
        config = parse_txt(
            'Посадочная страница:\nhttps://main.example/\nКлючевая фраза:\n'
            'пример товара\nСписок сканируемых сайтов:\nhttps://competitor.example/\n'
            'Обрезать слова короче 4\nУчитывать союзы - да\nИсключать слова:\nбренд\n---\n'
        )
        self.assertEqual(config['link'], 'https://main.example/')
        self.assertEqual(config['sites'], ['https://competitor.example/'])
        self.assertEqual(config['separator'], 4)
        self.assertTrue(config['conjunctions'])
        self.assertEqual(config['list_words'], ['бренд'])

    def test_parses_json_config_and_validates_bounds(self) -> None:
        config = parse_config('{"link":"https://main.example/","sites":["https://competitor.example/"]}', file_name='config.json')
        self.assertEqual(validate_config(config)['separator'], 3)
        with self.assertRaises(RelevanceInputError):
            validate_config({'link': 'http://127.0.0.1/', 'sites': ['https://competitor.example/']})
        with self.assertRaises(RelevanceInputError):
            validate_config({'link': 'https://main.example/', 'sites': ['https://main.example/']})

    def test_run_analysis_with_mocked_page_downloads(self) -> None:
        pages = {
            'https://main.example/': '<html><body><p>дерматоскоп качественный прибор купить</p></body></html>',
            'https://competitor.example/': '<html><body><p>дерматоскоп качественный прибор для диагностики</p></body></html>',
        }
        with patch('modules.relevance_analyzer.relevance.ta.fetch_html', side_effect=pages.__getitem__), redirect_stdout(StringIO()):
            result = run_analysis({'link': 'https://main.example/', 'sites': ['https://competitor.example/']})
        self.assertIn('https://main.example/', result.sites)
        self.assertTrue(result.word_forms)
        self.assertIn('coverage', result.avg)


class RelevanceFetchTests(unittest.TestCase):
    def test_redirect_to_private_host_is_rejected_before_following(self) -> None:
        response = Mock(status_code=302, headers={'Location': 'http://127.0.0.1/admin'})
        session = Mock()
        session.get.return_value = response
        with patch('modules.relevance_analyzer.text_analyzer._validate_public_url', side_effect=['https://public.example/', UnsafePageURL('blocked')]):
            self.assertEqual(fetch_html('https://public.example/', session), '')
        session.get.assert_called_once()
        response.close.assert_called_once()


class RelevanceExportTests(unittest.TestCase):
    def test_creates_four_reports_and_blocks_formula_cells(self) -> None:
        result = SimpleNamespace(
            recommendations={'=1+1': {'tf': 0.5, 'avg': 2, 'on_page': 0, 'diapason': '1 - 3', 'spam': 0, 'add': '1 - 3', 'remove': 0}},
            count_words_in_my_page=10,
            word_forms={},
            phrases={},
            sites={},
        )
        with tempfile.TemporaryDirectory() as directory:
            paths = export_xlsx(result, directory)
            self.assertEqual(len(paths), 4)
            workbook = load_workbook(Path(directory) / paths[0].name, read_only=True, data_only=True)
            self.assertEqual(workbook.active['B3'].value, "'=1+1")
            workbook.close()


class RelevanceRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_form_returns_safe_html_without_network_access(self) -> None:
        response = await web.submit_analysis(
            link='http://127.0.0.1/', phrase='', sites_text='https://competitor.example/',
            separator=3, conjunctions=False, list_words_text='', log_id='',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('alert-danger', response.body.decode())

    async def test_successful_job_packages_and_serves_all_reports(self) -> None:
        result = SimpleNamespace(
            recommendations={}, count_words_in_my_page=0, word_forms={}, phrases={}, sites={},
        )
        config = {'link': 'https://main.example/', 'sites': ['https://competitor.example/']}
        with tempfile.TemporaryDirectory() as directory, \
                patch('api.routers.relevance_analyzer.manage_temp_dir', return_value=directory), \
                patch('api.routers.relevance_analyzer.run_analysis', return_value=result), \
                redirect_stdout(StringIO()):
            request_id = web._run_job(config)
            archive_path = Path(directory) / 'result.zip'
            with zipfile.ZipFile(archive_path) as archive:
                reports = archive.namelist()
            self.assertEqual(len(reports), 4)
            self.assertTrue(all(name.endswith('.xlsx') for name in reports))
            background_tasks = BackgroundTasks()
            with patch('api.routers.relevance_analyzer.manage_temp_dir', return_value=directory):
                download = await web.download_result(request_id, background_tasks)
            self.assertEqual(download.filename, 'relevance_analyzer_reports.zip')
            self.assertEqual(len(background_tasks.tasks), 1)

    async def test_submit_returns_archive_link_after_job_success(self) -> None:
        request_id = '123e4567-e89b-12d3-a456-426614174000'
        with patch('api.routers.relevance_analyzer.run_with_log_capture', return_value=request_id):
            response = await web.submit_analysis(
                link='https://main.example/', phrase='', sites_text='https://competitor.example/',
                separator=3, conjunctions=False, list_words_text='', log_id='',
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'/download/relevance-analyzer/{request_id}', response.body.decode())

    async def test_download_route_rejects_invalid_identifier(self) -> None:
        with self.assertRaises(HTTPException):
            await web.download_result('not-a-uuid', BackgroundTasks())


if __name__ == '__main__':
    unittest.main()
