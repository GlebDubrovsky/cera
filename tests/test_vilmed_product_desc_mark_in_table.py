"""Офлайн-проверки отметки товаров через подменённый Selenium WebDriver."""

import io
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, text

import scenarios.vilmed_product_desc.vilmed_product_desc_mark_in_table as scenario


class FakeElement:
    def __init__(self, click_action=None, attribute_value=None):
        self.click_action = click_action
        self.attribute_value = attribute_value
        self.value = None

    def clear(self):
        self.value = ""

    def send_keys(self, value):
        self.value = value

    def click(self):
        if self.click_action:
            self.click_action()

    def get_attribute(self, name):
        if name == "disabled":
            return self.attribute_value
        return None


class FakeProductRow:
    def __init__(self, product_id):
        self.product_id = str(product_id)
        self.generate = FakeElement()
        self.skip = FakeElement(click_action=self._disable_generation)

    def _disable_generation(self):
        self.generate.attribute_value = "disabled"

    def get_attribute(self, name):
        return self.product_id if name == "data-id" else None

    def find_element(self, _by, selector):
        if selector == "input.titlo-skip":
            return self.skip
        raise LookupError(selector)

    def find_elements(self, _by, selector):
        if selector == 'input[value="Сгенерировать"]':
            return [self.generate]
        return []


class FakeSelectElement:
    def __init__(self, actions):
        self.actions = actions


class FakeSelect:
    def __init__(self, element):
        self.element = element

    def select_by_value(self, value):
        self.element.actions.append(f"filter:{value}")


class FakeDriver:
    def __init__(self):
        self.search = FakeElement()
        self.actions = []
        self.filter = FakeSelectElement(self.actions)
        self.current_product_id = None
        self.rows = {}
        self.refresh_count = 0
        self.quit = Mock()

    def get(self, _url):
        return None

    def refresh(self):
        self.refresh_count += 1
        self.current_product_id = None

    def find_element(self, _by, selector):
        if selector == "select#titlo-filter":
            return self.filter
        if selector == "input#titlo-q":
            self.search = FakeElement()
            self.search.send_keys = self._set_product_id
            return self.search
        if selector == "input#titlo-reload":
            return FakeElement(click_action=self._load_row)
        raise LookupError(selector)

    def _set_product_id(self, value):
        self.actions.append(f"id:{value}")
        self.current_product_id = str(value)

    def _load_row(self):
        self.actions.append("show")
        self.rows.setdefault(self.current_product_id, FakeProductRow(self.current_product_id))

    def find_elements(self, _by, selector):
        if selector == "tr[data-id]" and self.current_product_id in self.rows:
            return [self.rows[self.current_product_id]]
        return []


class VilmedMarkInTableTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        with self.engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE vilmed_description_products ("
                "row_id INTEGER PRIMARY KEY, product_id INTEGER, desc_status TEXT, "
                "mark_in_table BOOLEAN)"
            ))

    def tearDown(self):
        self.engine.dispose()

    def add_product(self, row_id, *, status="inserted", marked=False):
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO vilmed_description_products "
                "(row_id, product_id, desc_status, mark_in_table) "
                "VALUES (:row_id, :product_id, :status, :marked)"
            ), {"row_id": row_id, "product_id": row_id + 100, "status": status, "marked": marked})

    def run_scenario(self, driver, **kwargs):
        def wait_until(_driver, _timeout, _stage, condition):
            result = condition(_driver)
            if not result:
                raise TimeoutError("condition not fulfilled")
            return result

        with patch.object(scenario, "VILMED_LOGIN", "test-login"), \
             patch.object(scenario, "VILMED_PASSWORD", "test-password"), \
             patch.object(scenario, "_login"), \
             patch.object(scenario, "_wait_for_page_ready"), \
             patch.object(scenario, "_wait_until", side_effect=wait_until), \
             patch.object(scenario, "_focus"), \
             patch("selenium.webdriver.support.ui.Select", FakeSelect), \
             patch.object(scenario.time, "sleep"), \
             patch.object(scenario, "_click", side_effect=lambda _driver, element: element.click()), \
             redirect_stdout(io.StringIO()):
            return scenario.run_vilmed_product_desc_mark_in_table(
                self.engine,
                driver_factory=Mock(return_value=driver),
                delay_seconds=0,
                **kwargs,
            )

    def test_processes_all_eligible_rows_without_batch_limit(self):
        for row_id in range(1, 8):
            self.add_product(row_id)
        self.add_product(8, status="missing")
        self.add_product(9, marked=True)
        driver = FakeDriver()

        result = self.run_scenario(driver)

        self.assertEqual(result["candidate_count"], 7)
        self.assertEqual(result["processed_count"], 7)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(driver.actions[:3], ["filter:all", "id:101", "show"])
        self.assertEqual(driver.actions.count("filter:all"), 7)
        self.assertEqual(driver.refresh_count, 7)
        self.assertTrue(driver.quit.called)
        with self.engine.connect() as connection:
            states = connection.execute(text(
                "SELECT row_id, mark_in_table FROM vilmed_description_products ORDER BY row_id"
            )).all()
        self.assertEqual([bool(value) for row_id, value in states if row_id <= 7], [True] * 7)
        self.assertEqual([bool(value) for row_id, value in states if row_id in (8, 9)], [False, True])

    def test_missing_success_signal_keeps_database_flag_false(self):
        self.add_product(1)
        driver = FakeDriver()
        row = FakeProductRow(101)
        row.skip = FakeElement()
        driver.rows["101"] = row
        with patch.object(scenario, "_find_product_row_or_none", return_value=row), \
             patch.object(scenario, "_wait_until", side_effect=[row, TimeoutError("no confirmation")]):
            with patch.object(scenario, "VILMED_LOGIN", "test-login"), \
                 patch.object(scenario, "VILMED_PASSWORD", "test-password"), \
                 patch.object(scenario, "_login"), \
                 patch.object(scenario, "_wait_for_page_ready"), \
                 patch.object(scenario, "_focus"), \
                 patch("selenium.webdriver.support.ui.Select", FakeSelect), \
                 patch.object(scenario.time, "sleep"), \
                 patch.object(scenario, "_click", side_effect=lambda _driver, element: element.click()), \
                 redirect_stdout(io.StringIO()):
                result = scenario.run_vilmed_product_desc_mark_in_table(
                    self.engine, driver_factory=Mock(return_value=driver), delay_seconds=0,
                )
        self.assertEqual(result["error_count"], 1)
        with self.engine.connect() as connection:
            marked = connection.execute(text(
                "SELECT mark_in_table FROM vilmed_description_products WHERE row_id = 1"
            )).scalar_one()
        self.assertFalse(bool(marked))

    def test_stop_event_prevents_processing_next_product(self):
        self.add_product(1)
        self.add_product(2)
        stop_event = threading.Event()
        driver = FakeDriver()
        with patch.object(scenario, "_mark_product_in_admin", side_effect=lambda *_args: stop_event.set()), \
             patch.object(scenario, "VILMED_LOGIN", "test-login"), \
             patch.object(scenario, "VILMED_PASSWORD", "test-password"), \
             patch.object(scenario, "_login"), \
             patch.object(scenario, "_wait_for_page_ready"), \
             redirect_stdout(io.StringIO()):
            result = scenario.run_vilmed_product_desc_mark_in_table(
                self.engine, stop_event=stop_event, driver_factory=Mock(return_value=driver),
                delay_seconds=1,
            )
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["processed_count"], 1)
        self.assertTrue(driver.quit.called)

    def test_empty_queue_does_not_open_browser(self):
        driver_factory = Mock()
        with patch.object(scenario, "VILMED_LOGIN", "test-login"), \
             patch.object(scenario, "VILMED_PASSWORD", "test-password"), \
             redirect_stdout(io.StringIO()):
            result = scenario.run_vilmed_product_desc_mark_in_table(
                self.engine, driver_factory=driver_factory,
            )
        self.assertEqual(result["candidate_count"], 0)
        driver_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
