from __future__ import annotations

import asyncio
import json
from io import BytesIO
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from fastapi import UploadFile
from openpyxl import Workbook, load_workbook

from api.routers.site_tools import (
    _extract_urls_from_xlsx,
    _run_url_status_job,
    check_urls_htmx,
    start_url_status_check,
    url_status_check_results,
)
from modules.site_tools.url_status_checker import URLStatusChecker, write_results_xlsx
from shared.page_content import PageInputError


class URLStatusCheckerTests(unittest.TestCase):
    def make_response(self, status_code: int, headers: dict[str, str] | None = None) -> Mock:
        response = Mock()
        response.status_code = status_code
        response.headers = headers or {}
        return response

    @patch("modules.site_tools.url_status_checker.validate_public_url", side_effect=lambda value: value)
    @patch("modules.site_tools.url_status_checker.requests.get")
    def test_one_url_returns_response_using_headers_and_timeout(
        self, get: Mock, validate_url: Mock
    ) -> None:
        response = self.make_response(200)
        get.return_value = response
        checker = URLStatusChecker(timeout_seconds=8, attempts=1, pause_seconds=0, headers={"X-Test": "yes"})

        result = checker.check_url("https://example.com/page")

        self.assertIs(result, response)
        get.assert_called_once_with(
            "https://example.com/page",
            headers={"X-Test": "yes"},
            timeout=8.0,
            allow_redirects=False,
            stream=True,
        )
        validate_url.assert_called_once_with("https://example.com/page")

    @patch("modules.site_tools.url_status_checker.time.sleep")
    @patch("modules.site_tools.url_status_checker.validate_public_url", side_effect=lambda value: value)
    @patch("modules.site_tools.url_status_checker.requests.get")
    def test_network_error_retries_then_returns_response(
        self, get: Mock, _validate_url: Mock, sleep: Mock
    ) -> None:
        response = self.make_response(200)
        get.side_effect = [requests.Timeout(), requests.ConnectionError(), response]
        checker = URLStatusChecker(attempts=3, pause_seconds=0.25)

        self.assertIs(checker.check_url("https://example.com"), response)

        self.assertEqual(get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        sleep.assert_called_with(0.25)

    @patch("modules.site_tools.url_status_checker.validate_public_url", side_effect=lambda value: value)
    @patch("modules.site_tools.url_status_checker.requests.get")
    def test_http_404_is_returned_without_retry(self, get: Mock, _validate_url: Mock) -> None:
        response = self.make_response(404)
        get.return_value = response

        result = URLStatusChecker(attempts=4, pause_seconds=0).check_url("https://example.com/missing")

        self.assertEqual(result.status_code, 404)
        get.assert_called_once()

    @patch("modules.site_tools.url_status_checker.validate_public_url")
    @patch("modules.site_tools.url_status_checker.requests.get")
    def test_redirect_to_private_address_is_rejected(self, get: Mock, validate_url: Mock) -> None:
        redirect = self.make_response(302, {"Location": "http://127.0.0.1/admin"})
        get.return_value = redirect
        validate_url.side_effect = ["https://public.example/", PageInputError("blocked")]

        with self.assertRaises(PageInputError):
            URLStatusChecker(attempts=1).check_url("https://public.example/")

        redirect.close.assert_called_once()
        get.assert_called_once()

    def test_invalid_settings_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            URLStatusChecker(timeout_seconds=0)
        with self.assertRaises(ValueError):
            URLStatusChecker(attempts=0)
        with self.assertRaises(ValueError):
            URLStatusChecker(pause_seconds=-1)

    def test_xlsx_reads_url_header_case_insensitively(self) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Name", " URL "])
        sheet.append(["first", " https://example.com/a "])
        sheet.append(["second", "https://example.com/b"])
        buffer = BytesIO()
        workbook.save(buffer)

        self.assertEqual(
            _extract_urls_from_xlsx(buffer.getvalue()),
            ["https://example.com/a", "https://example.com/b"],
        )


class URLStatusCheckerEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_textarea_returns_two_column_html_table(self) -> None:
        results = [{"url": "https://example.com/?a=<b>", "status_code": 200}]
        with patch("api.routers.site_tools.check_urls_module", return_value=results) as check_urls:
            response = await check_urls_htmx(
                urls_text="https://example.com/?a=<b>",
                file=None,
                timeout_seconds=6,
                attempts=2,
                pause_seconds=0,
            )

        body = response.body.decode("utf-8")
        self.assertEqual(response.status_code, 200)
        self.assertIn("<th>url</th><th>status_code</th>", body)
        self.assertIn("https://example.com/?a=&lt;b&gt;", body)
        self.assertIn("<td>200</td>", body)
        check_urls.assert_called_once_with(
            ["https://example.com/?a=<b>"],
            timeout_seconds=6,
            attempts=2,
            pause_seconds=0,
        )

    async def test_xlsx_upload_is_sent_to_checker(self) -> None:
        workbook = Workbook()
        workbook.active.append(["url"])
        workbook.active.append(["https://example.com/from-xlsx"])
        buffer = BytesIO()
        workbook.save(buffer)
        upload = UploadFile(filename="links.xlsx", file=BytesIO(buffer.getvalue()))

        with patch("api.routers.site_tools.check_urls_module", return_value=[]) as check_urls:
            response = await check_urls_htmx(
                urls_text="",
                file=upload,
                timeout_seconds=10,
                attempts=3,
                pause_seconds=1,
            )

        self.assertEqual(response.status_code, 200)
        check_urls.assert_called_once_with(
            ["https://example.com/from-xlsx"],
            timeout_seconds=10,
            attempts=3,
            pause_seconds=1,
        )

    async def test_endpoint_requires_exactly_one_source(self) -> None:
        response = await check_urls_htmx(
            urls_text="https://example.com",
            file=UploadFile(filename="links.xlsx", file=BytesIO(b"x")),
            timeout_seconds=10,
            attempts=3,
            pause_seconds=1,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Укажите список ссылок или XLSX-файл", response.body.decode("utf-8"))


class URLStatusCheckerJobTests(unittest.TestCase):
    def test_stop_event_preserves_partial_results_and_reports_progress(self) -> None:
        checker = URLStatusChecker(pause_seconds=0)
        response = Mock(status_code=200)
        checker.check_url = Mock(return_value=response)
        stop_event = threading.Event()
        progress_updates = []

        def record_progress(**updates: object) -> None:
            progress_updates.append(updates)
            if updates.get("processed_count") == 1:
                stop_event.set()

        with patch("builtins.print"):
            results = checker.check_urls(
                ["https://example.com/1", "https://example.com/2"],
                stop_event=stop_event,
                progress_callback=record_progress,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status_code"], 200)
        checker.check_url.assert_called_once_with("https://example.com/1")
        response.close.assert_called_once()
        self.assertEqual(progress_updates[-1]["processed_count"], 1)

    def test_background_worker_saves_json_and_safe_xlsx(self) -> None:
        result_id = str(uuid.uuid4())
        results = [{"url": "=1+1", "status_code": 200}]
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch("api.routers.site_tools.manage_temp_dir", return_value=temp_dir),
                patch("api.routers.site_tools.check_urls_module", return_value=results),
                patch("builtins.print"),
            ):
                _run_url_status_job(
                    result_id,
                    ["=1+1"],
                    10,
                    1,
                    0,
                    stop_event=threading.Event(),
                    progress_callback=Mock(),
                )

            with (Path(temp_dir) / "result.json").open(encoding="utf-8") as result_file:
                saved = json.load(result_file)
            workbook = load_workbook(Path(temp_dir) / "result.xlsx", data_only=True)
            try:
                self.assertEqual(saved, {"input_count": 1, "results": results})
                self.assertEqual(workbook.active.cell(2, 1).value, "'=1+1")
                self.assertEqual(workbook.active.cell(2, 2).value, 200)
            finally:
                workbook.close()


class URLStatusCheckerBackgroundEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_results_hide_table_when_input_count_exceeds_300(self) -> None:
        result_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "result.json"
            result_path.write_text(
                json.dumps({"input_count": 301, "results": [{"url": "https://example.com", "status_code": 200}]}),
                encoding="utf-8",
            )
            with patch("api.routers.site_tools.manage_temp_dir", return_value=temp_dir):
                response = await url_status_check_results(result_id)

        body = response.body.decode("utf-8")
        self.assertIn("только скачивание XLSX", body)
        self.assertIn(f"/download/site-tools/url-status/{result_id}", body)
        self.assertNotIn("<table", body)

    async def test_start_endpoint_starts_job_with_log_id_and_normalized_urls(self) -> None:
        log_id = str(uuid.uuid4())
        result_id = uuid.uuid4()
        manager = Mock()
        manager.start.return_value = True
        manager.get_status.return_value = {"status": "running", "processed_count": 0}
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(job_manager=manager)))

        with patch("api.routers.site_tools.uuid.uuid4", return_value=result_id):
            response = await start_url_status_check(
                request,
                urls_text=" https://example.com/1 \n\nhttps://example.com/2 ",
                file=None,
                timeout_seconds=5,
                attempts=2,
                pause_seconds=0,
                log_id=log_id,
            )

        self.assertTrue(response["started"])
        self.assertEqual(response["result_id"], str(result_id))
        manager.start.assert_called_once()
        args = manager.start.call_args.args
        self.assertEqual(args[2], log_id)
        self.assertEqual(args[4], str(result_id))
        self.assertEqual(args[5], ["https://example.com/1", "https://example.com/2"])


if __name__ == "__main__":
    unittest.main()
