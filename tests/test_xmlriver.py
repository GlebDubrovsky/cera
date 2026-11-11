"""Offline tests for XMLRiver input, dispatch, route output, and XLSX files."""

from __future__ import annotations

import re
import tempfile
import unittest
from contextlib import redirect_stdout
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks
from openpyxl import Workbook, load_workbook

from api.routers import xmlriver as web
from modules.xmlriver.export import append_phrasal_values_xlsx, write_results_xlsx
from modules.xmlriver.registry import ModuleSpec
from modules.xmlriver.service import run_module
from modules.xmlriver.xmlriver_frequency import fetch_frequencies
from modules.xmlriver.xmlriver_google_serp import fetch_google_search_results
from shared.phrase_import import PhraseInputError, parse_phrases


def make_phrase_xlsx() -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["other", "phrase"])
    worksheet.append(["ignored", "первая фраза"])
    worksheet.append(["ignored", "вторая фраза"])
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


class PhraseInputTests(unittest.TestCase):
    def test_parses_textarea_by_nonempty_lines(self) -> None:
        self.assertEqual(parse_phrases(" первая фраза \n\nвторая фраза "), ["первая фраза", "вторая фраза"])

    def test_parses_xlsx_phrase_column_not_only_first_column(self) -> None:
        phrases = parse_phrases(None, "input.xlsx", make_phrase_xlsx())
        self.assertEqual(phrases, ["первая фраза", "вторая фраза"])

    def test_rejects_both_input_sources(self) -> None:
        with self.assertRaises(PhraseInputError):
            parse_phrases("фраза", "input.xlsx", make_phrase_xlsx())

    def test_rejects_xlsx_without_phrase_header(self) -> None:
        workbook = Workbook()
        workbook.active.append(["keyword"])
        output = BytesIO()
        workbook.save(output)
        workbook.close()
        with self.assertRaisesRegex(PhraseInputError, "phrase"):
            parse_phrases(None, "input.xlsx", output.getvalue())


class ModuleServiceTests(unittest.TestCase):
    def test_dispatch_uses_registered_callable_and_emits_stage_logs(self) -> None:
        module_function = Mock(return_value=[{"phrase": "пример", "total_value": 12, "error": None}])
        module_spec = ModuleSpec("frequency", "Сбор частот", module_function, {})
        output = StringIO()
        with patch("modules.xmlriver.service.get_module", return_value=module_spec), \
                patch("modules.xmlriver.service.XMLRIVER_USER", "configured-user"), \
                patch("modules.xmlriver.service.XMLRIVER_KEY", "configured-key"), \
                patch("modules.xmlriver.service.SETTINGS", {}), \
                redirect_stdout(output):
            results = run_module("frequency", ["пример"])
        self.assertEqual(results[0]["total_value"], 12)
        self.assertIn("[XMLRIVER][FREQUENCY][START]", output.getvalue())
        self.assertIn("[XMLRIVER][FREQUENCY][SUCCESS]", output.getvalue())
        module_function.assert_called_once_with(
            ["пример"], user_id="configured-user", api_key="configured-key", settings={}
        )

    def test_rejects_empty_phrase_before_module_call(self) -> None:
        with patch("modules.xmlriver.service.get_module") as get_module:
            with self.assertRaisesRegex(ValueError, "непустые строки"):
                run_module("frequency", [""])
        get_module.assert_called_once_with("frequency")


class GoogleSERPTests(unittest.TestCase):
    def test_dispatch_uses_google_settings_and_top_n(self) -> None:
        module_function = Mock(return_value=[{"phrase": "поиск", "results": [], "error": None}])
        module_spec = ModuleSpec("google_serp", "ТОП Google", module_function, {})
        with patch("modules.xmlriver.service.get_module", return_value=module_spec), \
                patch("modules.xmlriver.service.XMLRIVER_USER", "configured-user"), \
                patch("modules.xmlriver.service.XMLRIVER_KEY", "configured-key"), \
                patch("modules.xmlriver.service.GOOGLE_SEARCH_SETTINGS", {"device": "mobile"}), \
                redirect_stdout(StringIO()):
            results = run_module("google_serp", ["поиск"], top_n=20)

        self.assertEqual(results[0]["phrase"], "поиск")
        module_function.assert_called_once_with(
            ["поиск"], user_id="configured-user", api_key="configured-key",
            settings={"device": "mobile"}, top_n=20,
        )

    def test_pagination_uses_google_page_numbers_starting_at_one(self) -> None:
        def make_page(first_position: int) -> str:
            documents = "".join(
                f"<doc><contenttype>organic</contenttype><url>https://example.test/{position}</url>"
                f"<title>Result {position}</title><passages><passage>Snippet {position}</passage></passages></doc>"
                for position in range(first_position, first_position + 10)
            )
            return f"<root><group>{documents}</group></root>"

        with patch(
            "modules.xmlriver.xmlriver_google_serp._request_page",
            side_effect=[make_page(1), make_page(11)],
        ) as request, redirect_stdout(StringIO()):
            results = fetch_google_search_results(
                ["query"], user_id="user", api_key="key", top_n=20, retries=0
            )

        self.assertEqual([call.args[1] for call in request.call_args_list], [1, 2])
        self.assertEqual(len(results[0]["results"]), 20)
        self.assertEqual(results[0]["results"][0]["position"], "1")
        self.assertEqual(results[0]["results"][-1]["position"], "20")


class FrequencyModeTests(unittest.TestCase):
    def test_both_mode_sends_original_and_quoted_queries(self) -> None:
        with patch("modules.xmlriver.xmlriver_frequency.fetch_frequency", side_effect=[{"totalValue": 21}, {"totalValue": 8}]) as request, \
                redirect_stdout(StringIO()):
            results = fetch_frequencies(["частота"], user_id="user", api_key="key", mode="both")

        self.assertEqual([call.args[0] for call in request.call_args_list], ["частота", '"частота"'])
        self.assertEqual(results[0]["total_value"], 21)
        self.assertEqual(results[0]["phrasal_value"], 8)

    def test_phrasal_mode_sends_only_quoted_query(self) -> None:
        with patch("modules.xmlriver.xmlriver_frequency.fetch_frequency", return_value={"totalValue": 8}) as request, \
                redirect_stdout(StringIO()):
            results = fetch_frequencies(["частота"], user_id="user", api_key="key", mode="phrasal")

        request.assert_called_once()
        self.assertEqual(request.call_args.args[0], '"частота"')
        self.assertIsNone(results[0]["total_value"])
        self.assertEqual(results[0]["phrasal_value"], 8)


class XLSXExportTests(unittest.TestCase):
    def test_exports_frequency_popular_and_serp_as_tables(self) -> None:
        cases = {
            "frequency": ([{"phrase": "частота", "total_value": 21, "error": None}], ["phrase", "total_value", "error"]),
            "popular": ([{"phrase": "исходная", "popular": [{"isAssociations": False, "value": "8", "text": "популярная"}], "error": None}], ["phrase", "popular_phrase", "value", "error"]),
            "serp": ([{"phrase": "поиск", "results": [{"position": "1", "url": "https://example.test", "title": "Заголовок", "snippet": "Описание"}], "error": None}], ["phrase", "position", "url", "title", "snippet", "error"]),
            "google_serp": ([{"phrase": "поиск", "results": [{"position": "1", "url": "https://google.example.test", "title": "Google", "snippet": "Описание"}], "error": None}], ["phrase", "position", "url", "title", "snippet", "error"]),
        }
        with tempfile.TemporaryDirectory() as directory:
            for module_id, (results, expected_headers) in cases.items():
                with self.subTest(module_id=module_id):
                    file_path = Path(directory) / f"{module_id}.xlsx"
                    write_results_xlsx(file_path, module_id, results)
                    workbook = load_workbook(file_path, read_only=True, data_only=True)
                    worksheet = workbook.active
                    self.assertEqual([cell.value for cell in worksheet[1]], expected_headers)
                    self.assertEqual(worksheet.max_row, 2)
                    if module_id == "popular":
                        self.assertEqual([cell.value for cell in worksheet[2]], ["исходная", "популярная", "8", None])
                    workbook.close()

    def test_exports_both_frequency_values_in_three_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / "frequency_both.xlsx"
            write_results_xlsx(file_path, "frequency", [{"phrase": "пример", "total_value": 20, "phrasal_value": 7}])
            workbook = load_workbook(file_path, read_only=True, data_only=True)
            worksheet = workbook.active
            self.assertEqual([cell.value for cell in worksheet[1]], ["phrase", "total_value", "phrasal_value"])
            self.assertEqual([cell.value for cell in worksheet[2]], ["пример", 20, 7])
            workbook.close()

    def test_appends_phrasal_values_without_replacing_source_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            file_path = Path(directory) / "source_with_phrasal.xlsx"
            append_phrasal_values_xlsx(
                file_path,
                make_phrase_xlsx(),
                [{"phrasal_value": 6}, {"phrasal_value": 3}],
            )
            workbook = load_workbook(file_path, read_only=True, data_only=True)
            worksheet = workbook.active
            self.assertEqual([cell.value for cell in worksheet[1]], ["other", "phrase", "phrasal_value"])
            self.assertEqual([cell.value for cell in worksheet[2]], ["ignored", "первая фраза", 6])
            self.assertEqual([cell.value for cell in worksheet[3]], ["ignored", "вторая фраза", 3])
            workbook.close()

    def test_cell_text_is_redacted_and_formula_injection_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("modules.xmlriver.export.XMLRIVER_KEY", "test-secret"):
            file_path = Path(directory) / "safe.xlsx"
            write_results_xlsx(file_path, "frequency", [{"phrase": "=1+1", "total_value": None, "error": "test-secret"}])
            workbook = load_workbook(file_path, read_only=True, data_only=True)
            row = next(workbook.active.iter_rows(min_row=2, values_only=True))
            workbook.close()
        self.assertEqual(row[0], "'=1+1")
        self.assertNotIn("test-secret", row)
        self.assertEqual(row[2], "[скрыто]")


@unittest.skipIf(web is None, "Для HTTP-тестов установи зависимости из requirements.txt, включая python-multipart.")
class XMLRiverRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_google_json_api_dispatches_through_shared_service(self) -> None:
        expected_results = [{"phrase": "query", "results": [], "error": None}]
        request = web.GoogleSERPRequest(phrases=["query"], top_n=20)
        with patch("api.routers.xmlriver.run_with_log_capture", return_value=expected_results) as runner:
            response = await web.run_google_serp_api(request)

        self.assertEqual(response, {"module": "google_serp", "results": expected_results})
        runner.assert_called_once_with(
            "", web.run_module, "google_serp", ["query"], top_n=20
        )

    async def test_frequency_route_returns_downloadable_xlsx(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def temp_manager(request_id: str, action: str, work_type: str) -> str | bool:
                folder = root / f"temp_for_{request_id}_{work_type}"
                if action == "create":
                    folder.mkdir(parents=True, exist_ok=True)
                    return str(folder)
                if action == "get":
                    return str(folder)
                if action == "delete":
                    if folder.exists():
                        import shutil
                        shutil.rmtree(folder)
                    return True
                return False

            with patch("api.routers.xmlriver.manage_temp_dir", side_effect=temp_manager), \
                    patch("api.routers.xmlriver.run_module", return_value=[{"phrase": "пример", "total_value": 5, "error": None}]):
                response = await web.run_frequency("пример", None, "123e4567-e89b-12d3-a456-426614174000")
                self.assertEqual(response.status_code, 200)
                match = re.search(r"/download/xmlriver/frequency/([0-9a-f-]+)", response.body.decode())
                self.assertIsNotNone(match)
                background_tasks = BackgroundTasks()
                download = await web.download_result("frequency", match.group(1), background_tasks)
                workbook = load_workbook(download.path, read_only=True, data_only=True)
                self.assertEqual(workbook.active.cell(row=2, column=2).value, 5)
                workbook.close()
                self.assertEqual(len(background_tasks.tasks), 1)

    def test_frequency_job_uses_both_modes_by_input_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dual_results = [
                {"phrase": "первая", "total_value": 20, "phrasal_value": 5},
                {"phrase": "вторая", "total_value": 12, "phrasal_value": 3},
            ]
            with patch("api.routers.xmlriver.manage_temp_dir", return_value=directory), \
                    patch("api.routers.xmlriver.run_module", return_value=dual_results) as module_runner, \
                    redirect_stdout(StringIO()):
                web._run_job("frequency", "первая\nвторая", "", b"", 10)
            module_runner.assert_called_once_with(
                "frequency", ["первая", "вторая"], top_n=10, frequency_mode="both"
            )
            workbook = load_workbook(Path(directory) / "result.xlsx", read_only=True, data_only=True)
            self.assertEqual([cell.value for cell in workbook.active[1]], ["phrase", "total_value", "phrasal_value"])
            workbook.close()

        with tempfile.TemporaryDirectory() as directory:
            file_content = make_phrase_xlsx()
            dual_file_results = [
                {"phrase": "первая фраза", "total_value": 14, "phrasal_value": 4},
                {"phrase": "вторая фраза", "total_value": 9, "phrasal_value": 2},
            ]
            with patch("api.routers.xmlriver.manage_temp_dir", return_value=directory), \
                    patch("api.routers.xmlriver.run_module", return_value=dual_file_results) as module_runner, \
                    redirect_stdout(StringIO()):
                web._run_job("frequency", "", "input.xlsx", file_content, 10)
            module_runner.assert_called_once_with(
                "frequency", ["первая фраза", "вторая фраза"], top_n=10, frequency_mode="both"
            )
            workbook = load_workbook(Path(directory) / "result.xlsx", read_only=True, data_only=True)
            self.assertEqual([cell.value for cell in workbook.active[1]], ["phrase", "total_value", "phrasal_value"])
            workbook.close()

        with tempfile.TemporaryDirectory() as directory:
            file_content = make_phrase_xlsx()
            phrasal_results = [
                {"phrase": "первая фраза", "phrasal_value": 6},
                {"phrase": "вторая фраза", "phrasal_value": 3},
            ]
            with patch("api.routers.xmlriver.manage_temp_dir", return_value=directory), \
                    patch("api.routers.xmlriver.run_module", return_value=phrasal_results) as module_runner, \
                    redirect_stdout(StringIO()):
                web._run_job("frequency", "", "input.xlsx", file_content, 10, True)
            module_runner.assert_called_once_with(
                "frequency", ["первая фраза", "вторая фраза"], top_n=10, frequency_mode="phrasal"
            )
            workbook = load_workbook(Path(directory) / "result.xlsx", read_only=True, data_only=True)
            self.assertEqual([cell.value for cell in workbook.active[1]], ["other", "phrase", "phrasal_value"])
            self.assertEqual(workbook.active.cell(row=2, column=3).value, 6)
            workbook.close()

    async def test_invalid_form_returns_html_response_without_api_call(self) -> None:
        with patch("api.routers.xmlriver.run_module") as module_runner:
            response = await web.run_frequency("", None, "123e4567-e89b-12d3-a456-426614174001")
        self.assertEqual(response.status_code, 400)
        self.assertIn("alert-danger", response.body.decode())
        module_runner.assert_not_called()

    async def test_unexpected_error_is_not_reflected_to_html(self) -> None:
        response = web._error_response(RuntimeError("sensitive diagnostic"))
        self.assertNotIn("sensitive diagnostic", response.body.decode())
        self.assertIn("Не удалось выполнить обработку", response.body.decode())


if __name__ == "__main__":
    unittest.main()
