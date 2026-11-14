"""Офлайн-проверки пакетной вставки HTML через замоканный Selenium WebDriver."""

import io
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, text

import scenarios.vilmed_product_desc.vilmed_product_desc_insert_html as scenario


class VilmedInsertHtmlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        with self.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE vilmed_description_products ("
                "row_id INTEGER PRIMARY KEY, product_id INTEGER, html_desc TEXT, desc_status TEXT)"
            ))

    def tearDown(self) -> None:
        self.engine.dispose()

    def add_product(self, row_id: int, *, status: str = "missing", html: str | None = "<p>Описание</p>") -> None:
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO vilmed_description_products (row_id, product_id, html_desc, desc_status) "
                "VALUES (:row_id, :product_id, :html, :status)"
            ), {"row_id": row_id, "product_id": row_id + 100, "html": html, "status": status})

    def run_scenario(self, **kwargs: object) -> tuple[dict[str, int | str], Mock, dict[str, Mock]]:
        driver = Mock()
        driver.find_elements.return_value = []
        elements: dict[str, Mock] = {}

        def find_element(
            _driver: Mock, selector: str, _timeout: int, **_kwargs: str
        ) -> Mock:
            return elements.setdefault(selector, Mock())

        with patch.object(scenario, "VILMED_LOGIN", "test-login"), \
             patch.object(scenario, "VILMED_PASSWORD", "test-password"), \
             patch.object(scenario, "_wait_for_page_ready"), \
             patch.object(scenario, "_wait_for_visible", side_effect=find_element), \
             patch.object(scenario, "_wait_for_save_result"), \
             patch.object(scenario, "sleep"):
            with redirect_stdout(io.StringIO()):
                result = scenario.run_vilmed_product_desc_insert_html(
                    self.engine, driver_factory=Mock(return_value=driver), delay_seconds=0,
                    **kwargs,
                )
        return result, driver, elements

    def test_waits_three_seconds_after_typing_before_save_click(self) -> None:
        selectors = scenario.VILMED_INSERT_PRODUCT_DESCRIPTION["selectors"]
        elements = {
            selectors[name]: Mock()
            for name in ("detail_tab", "html_mode", "html_textarea", "save")
        }
        events: list[object] = []
        elements[selectors["html_textarea"]].send_keys.side_effect = (
            lambda _value: events.append("typed")
        )

        with patch.object(scenario, "_wait_for_page_ready"), \
             patch.object(scenario, "_wait_for_visible", side_effect=lambda _driver, selector, _timeout, **_kwargs: elements[selector]), \
             patch.object(scenario, "_wait_for_save_result"), \
             patch.object(scenario, "_focus"), \
             patch.object(scenario, "_click", side_effect=lambda *_args: events.append("click")), \
             patch.object(scenario, "sleep", side_effect=lambda delay: events.append(("pause", delay))):
            scenario._insert_product(Mock(), 123, "<p>test</p>", selectors, 30)

        self.assertEqual(
            events[-3:],
            ["typed", ("pause", scenario.AFTER_TEXT_ENTRY_DELAY_SECONDS), "click"],
        )
        self.assertEqual(scenario.AFTER_TEXT_ENTRY_DELAY_SECONDS, 3.0)

    def test_chrome_starts_maximized(self) -> None:
        driver = Mock()
        with patch("selenium.webdriver.ChromeOptions") as options_factory, \
             patch("selenium.webdriver.Chrome", return_value=driver) as chrome_factory:
            result = scenario._create_visible_chrome()

        options = options_factory.return_value
        options.add_argument.assert_called_once_with("--start-maximized")
        chrome_factory.assert_called_once_with(options=options)
        driver.maximize_window.assert_called_once_with()
        self.assertIs(result, driver)

    def test_intercepted_click_retries_with_javascript(self) -> None:
        from selenium.common.exceptions import ElementClickInterceptedException

        driver = Mock()
        element = Mock()
        element.click.side_effect = ElementClickInterceptedException("overlay")

        scenario._click(driver, element)

        self.assertEqual(element.click.call_count, 1)
        self.assertEqual(driver.execute_script.call_count, 2)
        self.assertEqual(
            driver.execute_script.call_args_list[1].args[0],
            "arguments[0].click();",
        )

    def test_processes_all_eligible_products_without_batch_limit(self) -> None:
        for row_id in range(1, 8):
            self.add_product(row_id)
        self.add_product(8, status="inserted")
        self.add_product(9, html="")

        result, driver, elements = self.run_scenario()

        self.assertEqual(result["candidate_count"], 7)
        self.assertEqual(result["processed_count"], 7)
        self.assertEqual(result["error_count"], 0)
        self.assertTrue(driver.quit.called)
        visited_urls = [call.args[0] for call in driver.get.call_args_list]
        self.assertTrue(any("ID=101" in url for url in visited_urls))
        self.assertTrue(any("ID=107" in url for url in visited_urls))
        self.assertFalse(any("ID=108" in url for url in visited_urls))
        self.assertTrue(elements[scenario.VILMED_INSERT_PRODUCT_DESCRIPTION["selectors"]["html_textarea"]].send_keys.called)
        with self.engine.connect() as connection:
            statuses = connection.execute(text(
                "SELECT row_id, desc_status FROM vilmed_description_products ORDER BY row_id"
            )).all()
        self.assertEqual([status for _, status in statuses[:7]], ["inserted"] * 7)
        self.assertEqual([status for _, status in statuses[7:]], ["inserted", "missing"])

    def test_failed_save_keeps_status_missing_and_counts_failure(self) -> None:
        self.add_product(1)
        driver = Mock()
        driver.find_elements.return_value = []
        with patch.object(scenario, "VILMED_LOGIN", "test-login"), \
             patch.object(scenario, "VILMED_PASSWORD", "test-password"), \
             patch.object(scenario, "_wait_for_page_ready"), \
             patch.object(scenario, "_wait_for_visible", side_effect=lambda *_args, **_kwargs: Mock()), \
             patch.object(scenario, "_wait_for_save_result", side_effect=RuntimeError("save failed")):
            with redirect_stdout(io.StringIO()):
                result = scenario.run_vilmed_product_desc_insert_html(
                    self.engine, driver_factory=Mock(return_value=driver), delay_seconds=0,
                )
        self.assertEqual(result["error_count"], 1)
        self.assertTrue(driver.quit.called)
        with self.engine.connect() as connection:
            status = connection.execute(text(
                "SELECT desc_status FROM vilmed_description_products WHERE row_id = 1"
            )).scalar_one()
        self.assertEqual(status, "missing")

    def test_stop_event_stops_before_next_product(self) -> None:
        self.add_product(1)
        self.add_product(2)
        stop_event = threading.Event()
        driver = Mock()
        driver.find_elements.return_value = []
        with patch.object(scenario, "VILMED_LOGIN", "test-login"), \
             patch.object(scenario, "VILMED_PASSWORD", "test-password"), \
             patch.object(scenario, "_wait_for_page_ready"), \
             patch.object(scenario, "_wait_for_visible", side_effect=lambda *_args, **_kwargs: Mock()), \
             patch.object(scenario, "_wait_for_save_result", side_effect=lambda *_args, **_kwargs: stop_event.set()):
            with redirect_stdout(io.StringIO()):
                result = scenario.run_vilmed_product_desc_insert_html(
                    self.engine, stop_event=stop_event, driver_factory=Mock(return_value=driver),
                    delay_seconds=1,
                )
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["processed_count"], 1)
        self.assertTrue(driver.quit.called)

    def test_empty_queue_does_not_start_browser(self) -> None:
        driver_factory = Mock()
        with patch.object(scenario, "VILMED_LOGIN", "test-login"), \
             patch.object(scenario, "VILMED_PASSWORD", "test-password"), \
             redirect_stdout(io.StringIO()):
            result = scenario.run_vilmed_product_desc_insert_html(
                self.engine, driver_factory=driver_factory,
            )
        self.assertEqual(result["candidate_count"], 0)
        driver_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
