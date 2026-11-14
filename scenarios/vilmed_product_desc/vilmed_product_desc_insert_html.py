"""Вставка всех подготовленных HTML-описаний в административную панель Vilmed.

Статус в базе меняется только после появления подтверждения сохранения в Bitrix;
Selenium запускает видимый Chrome, а остановка проверяется между товарами.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from time import sleep
from typing import Any
from urllib.parse import quote

from sqlalchemy import Engine, text

from config.config import VILMED_INSERT_PRODUCT_DESCRIPTION, VILMED_LOGIN, VILMED_PASSWORD

TABLE_NAME = "vilmed_description_products"
WAIT_TIMEOUT_SECONDS = int(VILMED_INSERT_PRODUCT_DESCRIPTION["wait_timeout_seconds"])
BETWEEN_PRODUCTS_DELAY_SECONDS = float(
    VILMED_INSERT_PRODUCT_DESCRIPTION["between_products_delay_seconds"]
)
AFTER_TEXT_ENTRY_DELAY_SECONDS = float(
    VILMED_INSERT_PRODUCT_DESCRIPTION["after_text_entry_delay_seconds"]
)
_SELECT_TOTAL = text(f"SELECT COUNT(*) FROM {TABLE_NAME}")
_SELECT_PRODUCTS = text(
    f"SELECT row_id, product_id, html_desc FROM {TABLE_NAME} "
    "WHERE COALESCE(TRIM(html_desc), '') <> '' AND desc_status = 'missing' "
    "ORDER BY row_id"
)
_UPDATE_STATUS = text(
    f"UPDATE {TABLE_NAME} SET desc_status = 'inserted' WHERE row_id = :row_id"
)


def _create_visible_chrome() -> Any:
    """Создаёт видимый Chrome и разворачивает окно на весь доступный экран."""
    from selenium import webdriver

    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(options=options)
    driver.maximize_window()
    return driver


def _wait_until(driver: Any, timeout: int, stage: str, condition: Callable[[Any], Any]) -> Any:
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait

    try:
        return WebDriverWait(driver, timeout).until(condition)
    except TimeoutException:
        print(
            f"[VILMED_PRODUCT_DESC_INSERT_HTML][WAIT][FAILURE] "
            f"Этап: {stage}; тайм-аут: {timeout} сек.",
            flush=True,
        )
        raise


def _wait_for_page_ready(
    driver: Any, timeout: int = WAIT_TIMEOUT_SECONDS, stage: str = "page_ready"
) -> None:
    _wait_until(
        driver, timeout, stage,
        lambda browser: browser.execute_script("return document.readyState") == "complete",
    )


def _wait_for_visible(
    driver: Any, selector: str, timeout: int = WAIT_TIMEOUT_SECONDS,
    stage: str = "visible_element",
) -> Any:
    from selenium.webdriver.support import expected_conditions as conditions

    return _wait_until(
        driver, timeout, stage,
        conditions.visibility_of_element_located(("css selector", selector)),
    )


def _wait_for_login(
    driver: Any, login_selector: str, timeout: int = WAIT_TIMEOUT_SECONDS,
    stage: str = "login_completion",
) -> None:
    _wait_until(
        driver, timeout, stage,
        lambda browser: not browser.find_elements("css selector", login_selector),
    )


def _wait_for_save_result(
    driver: Any, success_selector: str, error_selector: str,
    timeout: int = WAIT_TIMEOUT_SECONDS, stage: str = "save_confirmation",
) -> None:
    _wait_until(
        driver, timeout, stage,
        lambda browser: (
            browser.find_elements("css selector", success_selector)
            or browser.find_elements("css selector", error_selector)
        ),
    )
    if driver.find_elements("css selector", error_selector):
        raise RuntimeError("Административная панель сообщила об ошибке сохранения.")
    if not driver.find_elements("css selector", success_selector):
        raise RuntimeError("Не найден признак успешного сохранения.")


def _focus(driver: Any, element: Any) -> None:
    """Прокручивает элемент в область видимости перед вводом или нажатием."""
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)


def _click(driver: Any, element: Any) -> None:
    """Нажимает элемент обычным способом, затем обходит перекрытие оверлеем."""
    from selenium.common.exceptions import ElementClickInterceptedException

    _focus(driver, element)
    try:
        element.click()
    except ElementClickInterceptedException:
        # В административной форме фиксированная панель может закрыть точку клика;
        # JS-клик запускает обработчик самого элемента, а не попавшего поверх слоя.
        driver.execute_script("arguments[0].click();", element)


def _login(driver: Any, selectors: dict[str, str], timeout: int) -> None:
    _wait_for_page_ready(driver, timeout, stage="login_page_load")
    login_fields = driver.find_elements("css selector", selectors["login"])
    if not login_fields:
        return
    login = _wait_for_visible(driver, selectors["login"], timeout, stage="login_username")
    password = _wait_for_visible(driver, selectors["password"], timeout, stage="login_password")
    _focus(driver, login)
    login.clear()
    login.send_keys(VILMED_LOGIN)
    _focus(driver, password)
    password.clear()
    password.send_keys(VILMED_PASSWORD)
    submit = _wait_for_visible(driver, selectors["login_submit"], timeout, stage="login_submit")
    _click(driver, submit)
    _wait_for_page_ready(driver, timeout, stage="login_redirect")
    _wait_for_login(driver, selectors["login"], timeout, stage="login_completion")


def _insert_product(driver: Any, product_id: Any, html_desc: str, selectors: dict[str, str], timeout: int) -> None:
    url = VILMED_INSERT_PRODUCT_DESCRIPTION["edit_url_template"].format(
        product_id=quote(str(product_id), safe="")
    )
    driver.get(url)
    _wait_for_page_ready(driver, timeout, stage="product_page_load")
    detail_tab = _wait_for_visible(driver, selectors["detail_tab"], timeout, stage="detail_tab")
    _click(driver, detail_tab)
    html_mode = _wait_for_visible(driver, selectors["html_mode"], timeout, stage="html_mode_toggle")
    _click(driver, html_mode)
    textarea = _wait_for_visible(driver, selectors["html_textarea"], timeout, stage="html_textarea")
    _focus(driver, textarea)
    textarea.clear()
    textarea.send_keys(html_desc)
    # The admin editor can still be processing the input; pause before clicking save.
    sleep(AFTER_TEXT_ENTRY_DELAY_SECONDS)
    save = _wait_for_visible(driver, selectors["save"], timeout, stage="save_button")
    _click(driver, save)
    _wait_for_page_ready(driver, timeout, stage="save_page_transition")
    _wait_for_save_result(
        driver, selectors["save_success"], selectors["save_error"], timeout,
        stage="save_confirmation",
    )


def run_vilmed_product_desc_insert_html(
    engine: Engine,
    *,
    stop_event: threading.Event | None = None,
    progress_callback: Callable[..., None] | None = None,
    driver_factory: Callable[[], Any] = _create_visible_chrome,
    delay_seconds: float = BETWEEN_PRODUCTS_DELAY_SECONDS,
    wait_timeout_seconds: int = WAIT_TIMEOUT_SECONDS,
) -> dict[str, int | str]:
    """Вставляет HTML во все подходящие товары со статусом ``missing``."""
    if not VILMED_LOGIN or not VILMED_PASSWORD:
        raise RuntimeError("Не заданы VILMED_LOGIN и VILMED_PASSWORD в окружении.")

    cancellation = stop_event or threading.Event()
    report = progress_callback or (lambda **_: None)
    with engine.connect() as connection:
        total_count = int(connection.execute(_SELECT_TOTAL).scalar_one())
        products = connection.execute(_SELECT_PRODUCTS).mappings().all()

    candidate_count = len(products)
    processed_count = 0
    error_count = 0
    report(
        total_count=total_count, candidate_count=candidate_count,
        processed_count=0, error_count=0,
        message=f"Подходящих товаров для обработки: {candidate_count}.",
    )
    print(
        f"[VILMED_PRODUCT_DESC_INSERT_HTML][START][INFO] "
        f"Ожидают вставки: {candidate_count}; выбрано: {candidate_count}; "
        f"ограничение на размер пакета отсутствует.", flush=True,
    )
    if not products:
        print("[VILMED_PRODUCT_DESC_INSERT_HTML][FINISH][SUCCESS] Нет подходящих товаров.", flush=True)
        return {"status": "completed", "total_count": total_count,
                "candidate_count": 0, "processed_count": 0, "error_count": 0}

    driver = driver_factory()
    selectors = VILMED_INSERT_PRODUCT_DESCRIPTION["selectors"]
    try:
        driver.get(VILMED_INSERT_PRODUCT_DESCRIPTION["login_url"])
        _login(driver, selectors, wait_timeout_seconds)
        for index, product in enumerate(products, start=1):
            if cancellation.is_set():
                break
            row_id = product["row_id"]
            processed_count += 1
            print(
                f"[VILMED_PRODUCT_DESC_INSERT_HTML][PRODUCT][START] "
                f"Товар {index}/{candidate_count}; row_id={row_id}.", flush=True,
            )
            try:
                if product["product_id"] is None or not str(product["product_id"]).strip():
                    raise ValueError("Не задан product_id.")
                html_desc = product["html_desc"]
                if not isinstance(html_desc, str) or not html_desc.strip():
                    raise ValueError("HTML-описание пустое.")
                _insert_product(
                    driver, product["product_id"], html_desc, selectors, wait_timeout_seconds
                )
                with engine.begin() as connection:
                    connection.execute(_UPDATE_STATUS, {"row_id": row_id})
                print(
                    f"[VILMED_PRODUCT_DESC_INSERT_HTML][PRODUCT][SUCCESS] "
                    f"Товар {index}/{candidate_count}; row_id={row_id}; статус inserted.", flush=True,
                )
            except Exception as error:
                error_count += 1
                print(
                    f"[VILMED_PRODUCT_DESC_INSERT_HTML][PRODUCT][FAILURE] "
                    f"Товар {index}/{candidate_count}; row_id={row_id}; "
                    f"ошибка: {type(error).__name__}.", flush=True,
                )
            report(
                total_count=total_count, candidate_count=candidate_count,
                processed_count=processed_count, error_count=error_count,
                message=f"Обработано {processed_count}/{candidate_count}; ошибок: {error_count}.",
            )
            if index < candidate_count and cancellation.wait(delay_seconds):
                break
    finally:
        driver.quit()

    final_status = "stopped" if cancellation.is_set() else "completed"
    print(
        f"[VILMED_PRODUCT_DESC_INSERT_HTML][FINISH][{'STOPPED' if final_status == 'stopped' else 'SUCCESS'}] "
        f"Обработано: {processed_count}; ошибок: {error_count}; выбрано: {candidate_count}.",
        flush=True,
    )
    return {
        "status": final_status, "total_count": total_count,
        "candidate_count": candidate_count, "processed_count": processed_count,
        "error_count": error_count,
    }


__all__ = ["run_vilmed_product_desc_insert_html"]
