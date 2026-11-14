"""Отмечает обработанные товары в административной таблице Vilmed через Selenium."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import Engine, text

from config.config import VILMED_INSERT_PRODUCT_DESCRIPTION, VILMED_LOGIN, VILMED_PASSWORD
from scenarios.vilmed_product_desc.vilmed_product_desc_insert_html import (
    _click,
    _create_visible_chrome,
    _focus,
    _login,
    _wait_for_page_ready,
)


TABLE_NAME = "vilmed_description_products"
WORK_URL = "https://vilmed.ru/bitrix/admin/titlo_relevance_names.php?lang=ru"
WAIT_TIMEOUT_SECONDS = int(VILMED_INSERT_PRODUCT_DESCRIPTION["wait_timeout_seconds"])
STEP_DELAY_SECONDS = 0.75
BETWEEN_PRODUCTS_DELAY_SECONDS = 3.0
LOGIN_SELECTORS = VILMED_INSERT_PRODUCT_DESCRIPTION["selectors"]
_SELECT_TOTAL = text(
    f"SELECT COUNT(*) FROM {TABLE_NAME} "
    "WHERE desc_status = 'inserted' AND mark_in_table IS FALSE"
)
_SELECT_PRODUCTS = text(
    f"SELECT row_id, product_id FROM {TABLE_NAME} "
    "WHERE desc_status = 'inserted' AND mark_in_table IS FALSE "
    "ORDER BY row_id"
)
_MARK_PRODUCT = text(
    f"UPDATE {TABLE_NAME} SET mark_in_table = TRUE "
    "WHERE row_id = :row_id AND desc_status = 'inserted' AND mark_in_table IS FALSE"
)


def _wait_until(driver: Any, timeout: int, stage: str, condition: Callable[[Any], Any]) -> Any:
    """Ожидает Selenium-условие и помечает тайм-аут логами этого сценария."""
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait

    try:
        return WebDriverWait(driver, timeout).until(condition)
    except TimeoutException:
        print(
            f"[VILMED_PRODUCT_DESC_MARK_IN_TABLE][WAIT][FAILURE] "
            f"Этап: {stage}; тайм-аут: {timeout} сек.",
            flush=True,
        )
        raise


def _find_product_row(driver: Any, product_id: Any) -> Any:
    """Ищет строку по точному data-id, не включая значение БД в CSS-селектор."""
    expected_id = str(product_id)
    for row in driver.find_elements("css selector", "tr[data-id]"):
        if row.get_attribute("data-id") == expected_id:
            return row
    raise LookupError("Строка товара не найдена в административной таблице.")


def _mark_product_in_admin(driver: Any, product_id: Any, timeout: int) -> None:
    """Запускает отметку товара и ждёт отключения генерации как сигнал успеха."""
    from selenium.webdriver.support.ui import Select

    filter_select = Select(driver.find_element("css selector", "select#titlo-filter"))
    filter_select.select_by_value("all")
    time.sleep(STEP_DELAY_SECONDS)
    search = driver.find_element("css selector", "input#titlo-q")
    _focus(driver, search)
    search.clear()
    search.send_keys(str(product_id))
    time.sleep(STEP_DELAY_SECONDS)
    reload_button = driver.find_element("css selector", "input#titlo-reload")
    _click(driver, reload_button)
    time.sleep(STEP_DELAY_SECONDS)

    row = _wait_until(
        driver,
        timeout,
        "product_row",
        lambda browser: _find_product_row_or_none(browser, product_id),
    )
    skip = row.find_element("css selector", "input.titlo-skip")
    _click(driver, skip)
    time.sleep(STEP_DELAY_SECONDS)

    def generation_disabled(browser: Any) -> Any:
        current_row = _find_product_row_or_none(browser, product_id)
        if current_row is None:
            return False
        buttons = current_row.find_elements(
            "css selector", 'input[value="Сгенерировать"]'
        )
        if buttons and buttons[0].get_attribute("disabled") is not None:
            return buttons[0]
        return False

    _wait_until(driver, timeout, "generation_disabled", generation_disabled)


def _find_product_row_or_none(driver: Any, product_id: Any) -> Any | None:
    expected_id = str(product_id)
    for row in driver.find_elements("css selector", "tr[data-id]"):
        if row.get_attribute("data-id") == expected_id:
            return row
    return None


def run_vilmed_product_desc_mark_in_table(
    engine: Engine,
    *,
    stop_event: threading.Event | None = None,
    progress_callback: Callable[..., None] | None = None,
    driver_factory: Callable[[], Any] = _create_visible_chrome,
    wait_timeout_seconds: int = WAIT_TIMEOUT_SECONDS,
    delay_seconds: float = BETWEEN_PRODUCTS_DELAY_SECONDS,
) -> dict[str, int | str]:
    """Отмечает все строки со статусом ``inserted`` и ``mark_in_table = false``.

    Сначала фиксируется результат действия в административной странице, затем — в БД;
    поэтому исключение или неотключившийся генератор не меняет флаг в таблице.
    """
    if not VILMED_LOGIN or not VILMED_PASSWORD:
        raise RuntimeError("Не заданы VILMED_LOGIN и VILMED_PASSWORD в окружении.")

    cancellation = stop_event or threading.Event()
    report = progress_callback or (lambda **_: None)
    with engine.connect() as connection:
        candidate_count = int(connection.execute(_SELECT_TOTAL).scalar_one())
        products = connection.execute(_SELECT_PRODUCTS).mappings().all()

    total_count = candidate_count
    processed_count = 0
    error_count = 0
    report(
        total_count=total_count,
        candidate_count=len(products),
        processed_count=0,
        error_count=0,
        message=f"В очереди: {candidate_count}; выбрано товаров: {len(products)}.",
    )
    print(
        f"[VILMED_PRODUCT_DESC_MARK_IN_TABLE][START][INFO] "
        f"В очереди: {candidate_count}; выбрано: {len(products)}; "
        f"паузы между шагами: {STEP_DELAY_SECONDS} сек.; "
        f"между товарами: {BETWEEN_PRODUCTS_DELAY_SECONDS} сек.",
        flush=True,
    )
    if not products:
        print(
            "[VILMED_PRODUCT_DESC_MARK_IN_TABLE][FINISH][SUCCESS] Нет подходящих товаров.",
            flush=True,
        )
        return {
            "status": "completed", "total_count": total_count,
            "candidate_count": 0, "processed_count": 0, "error_count": 0,
        }

    driver = driver_factory()
    try:
        driver.get(VILMED_INSERT_PRODUCT_DESCRIPTION["login_url"])
        _login(driver, LOGIN_SELECTORS, wait_timeout_seconds)
        driver.get(WORK_URL)
        _wait_for_page_ready(driver, wait_timeout_seconds, stage="work_page_load")

        for index, product in enumerate(products, start=1):
            if cancellation.is_set():
                break
            processed_count += 1
            row_id = product["row_id"]
            product_id = product["product_id"]
            try:
                if product_id is None or not str(product_id).strip():
                    raise ValueError("Не задан product_id.")
                _mark_product_in_admin(driver, product_id, wait_timeout_seconds)
                with engine.begin() as connection:
                    result = connection.execute(_MARK_PRODUCT, {"row_id": row_id})
                    if result.rowcount != 1:
                        raise RuntimeError("Строка изменилась до сохранения флага.")
                print(
                    f"[VILMED_PRODUCT_DESC_MARK_IN_TABLE][PRODUCT][SUCCESS] "
                    f"Обработано {index}/{len(products)}; отметка сохранена.",
                    flush=True,
                )
            except Exception as error:
                error_count += 1
                print(
                    f"[VILMED_PRODUCT_DESC_MARK_IN_TABLE][PRODUCT][FAILURE] "
                    f"Обработано {index}/{len(products)}; этап товара; "
                    f"ошибка: {type(error).__name__}.",
                    flush=True,
                )
            finally:
                try:
                    driver.refresh()
                    _wait_for_page_ready(
                        driver, wait_timeout_seconds, stage="work_page_refresh"
                    )
                except Exception as error:
                    error_count += 1
                    print(
                        f"[VILMED_PRODUCT_DESC_MARK_IN_TABLE][REFRESH][FAILURE] "
                        f"Этап обновления страницы; ошибка: {type(error).__name__}.",
                        flush=True,
                    )
            report(
                total_count=total_count,
                candidate_count=len(products),
                processed_count=processed_count,
                error_count=error_count,
                message=(
                    f"Обработано {processed_count}/{len(products)}; "
                    f"ошибок: {error_count}."
                ),
            )
            if index < len(products) and cancellation.wait(delay_seconds):
                break
    finally:
        driver.quit()

    final_status = "stopped" if cancellation.is_set() else "completed"
    print(
        f"[VILMED_PRODUCT_DESC_MARK_IN_TABLE][FINISH]["
        f"{'STOPPED' if final_status == 'stopped' else 'SUCCESS'}] "
        f"Обработано: {processed_count}; ошибок: {error_count}; "
        f"выбрано: {len(products)}.",
        flush=True,
    )
    return {
        "status": final_status,
        "total_count": total_count,
        "candidate_count": len(products),
        "processed_count": processed_count,
        "error_count": error_count,
    }


__all__ = ["run_vilmed_product_desc_mark_in_table"]
