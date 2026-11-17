"""Endpoints for domain-neutral website analysis tools."""

import asyncio
import json
import os
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from html import escape
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from config.config import CONFIG_LINK_SELECTION_BAR_TAGS, HEADERS
from modules.site_tools.bar_tags import link_selection_bar_tags
from modules.site_tools.open_links import open_links_in_browser
from modules.site_tools.url_status_checker import (
    URLStatusChecker,
    check_urls as check_urls_module,
    write_results_xlsx,
)
from shared.link_checker import check_link
from shared.log_stream import run_with_log_capture
from shared.temp_storage import manage_temp_dir

router = APIRouter()


@router.post("/bar_tags", response_class=HTMLResponse)
async def bar_tags_htmx(
    file: UploadFile = File(...),
    category_url: str = Form(...),
    log_id: str = Form(""),
) -> HTMLResponse:
    if not file.filename or not file.filename.endswith(".xlsx"):
        return HTMLResponse('<div class="alert alert-danger">Требуется файл .xlsx</div>', status_code=400)

    if not category_url.startswith("http") or not check_link(category_url, HEADERS):
        return HTMLResponse('<div class="alert alert-danger">Неверный или недоступный URL</div>', status_code=400)

    request_id = str(uuid.uuid4())
    temp_dir = manage_temp_dir(request_id, "create", "bar_tags")
    file_path = os.path.join(temp_dir, file.filename)

    try:
        with open(file_path, "wb") as uploaded_file:
            shutil.copyfileobj(file.file, uploaded_file)

        domain = next((item for item in CONFIG_LINK_SELECTION_BAR_TAGS if item in category_url), None)
        worksheet_path = os.path.join("worksheets", f"work_{domain}.xlsx")
        result_df = await asyncio.to_thread(
            run_with_log_capture,
            log_id,
            link_selection_bar_tags,
            file_path,
            worksheet_path,
            category_url,
            CONFIG_LINK_SELECTION_BAR_TAGS,
        )
        result_path = os.path.join(temp_dir, "result.xlsx")
        result_df.to_excel(result_path, index=False)
    except Exception as error:
        manage_temp_dir(request_id, "delete", "bar_tags")
        return HTMLResponse(
            f'<div class="alert alert-danger">Ошибка при обработке: {escape(str(error))}</div>',
            status_code=500,
        )

    download_url = f"/download/bar_tags/{request_id}"
    return HTMLResponse(
        '<div class="alert alert-success d-flex align-items-center" role="alert">'
        '<div>Обработка завершена! '
        f'<a href="{download_url}" class="btn btn-sm btn-success ms-2" download>Скачать результат</a>'
        "</div></div>"
    )


@router.post("/open_links", response_class=HTMLResponse)
async def open_links_htmx(request: Request, links_text: str = Form(...)) -> HTMLResponse:
    if not links_text or not links_text.strip():
        return HTMLResponse('<div class="alert alert-danger">Введите список ссылок</div>', status_code=400)

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    await loop.run_in_executor(executor, open_links_in_browser, links_text, 1)
    return HTMLResponse('<div class="alert alert-success">Процесс завершен!</div>')


def _extract_urls_from_xlsx(content: bytes) -> list[str]:
    """Извлекает непустые URL из колонки url первого листа книги."""
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, OSError, ValueError) as error:
        raise ValueError("Не удалось прочитать XLSX-файл.") from error

    try:
        rows = workbook.active.iter_rows(values_only=True)
        header = next(rows, None)
        if not header:
            raise ValueError("В XLSX нет строки заголовков.")
        url_column = next(
            (
                index for index, value in enumerate(header)
                if isinstance(value, str) and value.strip().casefold() == "url"
            ),
            None,
        )
        if url_column is None:
            raise ValueError('В первом листе XLSX не найдена колонка "url".')
        urls = []
        for row in rows:
            if url_column < len(row) and row[url_column] is not None:
                url = str(row[url_column]).strip()
                if url:
                    urls.append(url)
        return urls
    finally:
        workbook.close()


@router.post("/check_urls", response_class=HTMLResponse)
async def check_urls_htmx(
    urls_text: str = Form(""),
    file: UploadFile | None = File(default=None),
    timeout_seconds: float = Form(10.0),
    attempts: int = Form(3),
    pause_seconds: float = Form(1.0),
) -> HTMLResponse:
    """Принимает ровно один источник и возвращает таблицу URL и HTTP-кодов."""
    has_text = bool(urls_text.strip())
    has_file = file is not None and bool(file.filename)
    if has_text == has_file:
        return HTMLResponse(
            '<div class="alert alert-danger">Укажите список ссылок или XLSX-файл.</div>',
            status_code=400,
        )

    if has_file:
        if not file.filename.lower().endswith(".xlsx"):
            return HTMLResponse(
                '<div class="alert alert-danger">Требуется файл .xlsx</div>',
                status_code=400,
            )
        try:
            urls = _extract_urls_from_xlsx(await file.read())
        except ValueError as error:
            return HTMLResponse(
                f'<div class="alert alert-danger">{escape(str(error))}</div>',
                status_code=400,
            )
    else:
        urls = [line.strip() for line in urls_text.splitlines() if line.strip()]

    if not urls:
        return HTMLResponse(
            '<div class="alert alert-danger">В выбранном источнике не найдено ссылок.</div>',
            status_code=400,
        )

    try:
        results = await asyncio.to_thread(
            check_urls_module,
            urls,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            pause_seconds=pause_seconds,
        )
    except ValueError as error:
        return HTMLResponse(
            f'<div class="alert alert-danger">{escape(str(error))}</div>',
            status_code=400,
        )

    table_rows = "".join(
        "<tr><td>" + escape(str(result["url"]), quote=True) + "</td><td>"
        + escape(str(result["status_code"]), quote=True) + "</td></tr>"
        for result in results
    )
    table = (
        '<div class="table-responsive"><table class="table table-striped table-bordered mt-3">'
        "<thead><tr><th>url</th><th>status_code</th></tr></thead>"
        f"<tbody>{table_rows}</tbody></table></div>"
    )
    return HTMLResponse(table)


_URL_STATUS_JOB_ID = "url_status_checker"
_URL_STATUS_WORK_TYPE = "url_status_checker"
_URL_STATUS_TABLE_LIMIT = 300
_URL_STATUS_UPLOAD_LIMIT = 10 * 1024 * 1024
_url_status_result_lock = threading.Lock()
_url_status_result_id: str | None = None


def _run_url_status_job(
    result_id: str,
    urls: list[str],
    timeout_seconds: float,
    attempts: int,
    pause_seconds: float,
    *,
    stop_event: threading.Event,
    progress_callback,
) -> None:
    """Checks the list in a job worker and preserves partial results on stop."""
    temp_dir = manage_temp_dir(result_id, "create", _URL_STATUS_WORK_TYPE)
    if not temp_dir:
        raise RuntimeError("Не удалось подготовить временное хранилище результата.")

    try:
        results = check_urls_module(
            urls,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            pause_seconds=pause_seconds,
            stop_event=stop_event,
            progress_callback=progress_callback,
        )
        progress_callback(message="Формирую файл XLSX с результатами")
        print("[URL_STATUS_CHECKER][EXPORT][START] Формирование XLSX.", flush=True)
        write_results_xlsx(Path(temp_dir) / "result.xlsx", results)
        with (Path(temp_dir) / "result.json").open("w", encoding="utf-8") as result_file:
            json.dump({"input_count": len(urls), "results": results}, result_file, ensure_ascii=False)
        print(f"[URL_STATUS_CHECKER][EXPORT][SUCCESS] Сохранено результатов: {len(results)}.", flush=True)
    except Exception:
        manage_temp_dir(result_id, "delete", _URL_STATUS_WORK_TYPE)
        raise


@router.post("/api/site-tools/url-status/start")
async def start_url_status_check(
    request: Request,
    urls_text: str = Form(""),
    file: UploadFile | None = File(default=None),
    timeout_seconds: float = Form(10.0),
    attempts: int = Form(3),
    pause_seconds: float = Form(1.0),
    log_id: str = Form(""),
) -> dict[str, object]:
    """Validates input and starts an interruptible status-check job."""
    global _url_status_result_id
    has_text = bool(urls_text.strip())
    has_file = file is not None and bool(file.filename)
    if has_text == has_file:
        raise HTTPException(400, "Укажи список ссылок или XLSX-файл, но не оба источника.")

    if has_file:
        if not file.filename.lower().endswith(".xlsx"):
            raise HTTPException(400, "Требуется файл .xlsx")
        content = await file.read(_URL_STATUS_UPLOAD_LIMIT + 1)
        if len(content) > _URL_STATUS_UPLOAD_LIMIT:
            raise HTTPException(400, "Размер XLSX-файла не должен превышать 10 МБ.")
        try:
            urls = _extract_urls_from_xlsx(content)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
    else:
        urls = [line.strip() for line in urls_text.splitlines() if line.strip()]
    if not urls:
        raise HTTPException(400, "В выбранном источнике не найдено ссылок.")

    try:
        URLStatusChecker(
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            pause_seconds=pause_seconds,
        )
        normalized_log_id = str(uuid.UUID(log_id))
    except (ValueError, TypeError, AttributeError) as error:
        message = str(error) if isinstance(error, ValueError) else "Не удалось подготовить поток логов."
        raise HTTPException(400, message) from None

    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(503, "Менеджер фоновых задач недоступен.")
    result_id = str(uuid.uuid4())
    started = manager.start(
        _URL_STATUS_JOB_ID,
        run_with_log_capture,
        normalized_log_id,
        _run_url_status_job,
        result_id,
        urls,
        timeout_seconds,
        attempts,
        pause_seconds,
    )
    if not started:
        raise HTTPException(409, "Проверка ссылок уже выполняется или останавливается.")
    with _url_status_result_lock:
        _url_status_result_id = result_id
    return {"started": True, "result_id": result_id, **manager.get_status(_URL_STATUS_JOB_ID)}


@router.post("/api/site-tools/url-status/stop")
async def stop_url_status_check(request: Request) -> dict[str, object]:
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(503, "Менеджер фоновых задач недоступен.")
    return {"stop_requested": manager.stop(_URL_STATUS_JOB_ID), **manager.get_status(_URL_STATUS_JOB_ID)}


@router.get("/api/site-tools/url-status/status")
async def url_status_check_status(request: Request) -> dict[str, object]:
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(503, "Менеджер фоновых задач недоступен.")
    with _url_status_result_lock:
        result_id = _url_status_result_id
    return {**manager.get_status(_URL_STATUS_JOB_ID), "result_id": result_id}


@router.get("/api/site-tools/url-status/results/{result_id}", response_class=HTMLResponse)
async def url_status_check_results(result_id: str) -> HTMLResponse:
    try:
        normalized_id = str(uuid.UUID(result_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(404, "Результат не найден.") from None
    temp_dir = manage_temp_dir(normalized_id, "get", _URL_STATUS_WORK_TYPE)
    result_path = Path(temp_dir or "") / "result.json"
    if not temp_dir or not result_path.is_file():
        raise HTTPException(404, "Результат ещё не готов или уже удалён.")
    with result_path.open("r", encoding="utf-8") as result_file:
        result_document = json.load(result_file)
    results = result_document["results"]
    input_count = result_document["input_count"]

    download_link = f'<a class="btn btn-success btn-sm" href="/download/site-tools/url-status/{normalized_id}" download>Скачать XLSX</a>'
    if input_count > _URL_STATUS_TABLE_LIMIT:
        return HTMLResponse(
            f'<div class="alert alert-success">Обработано ссылок: {len(results)} из {input_count}. Таблица скрыта, доступно только скачивание XLSX. {download_link}</div>'
        )
    table_rows = "".join(
        "<tr><td>" + escape(str(result.get("url", "")), quote=True) + "</td><td>"
        + escape(str(result.get("status_code", "")), quote=True) + "</td></tr>"
        for result in results
    )
    return HTMLResponse(
        '<div class="alert alert-success d-flex gap-2 align-items-center">Проверка завершена. '
        + download_link
        + '</div><div class="table-responsive"><table class="table table-striped table-bordered mt-3">'
        + "<thead><tr><th>url</th><th>status_code</th></tr></thead>"
        + f"<tbody>{table_rows}</tbody></table></div>"
    )


@router.get("/download/site-tools/url-status/{result_id}")
async def download_url_status_result(
    result_id: str,
    background_tasks: BackgroundTasks,
) -> FileResponse:
    try:
        normalized_id = str(uuid.UUID(result_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(404, "Файл не найден.") from None
    temp_dir = manage_temp_dir(normalized_id, "get", _URL_STATUS_WORK_TYPE)
    result_path = Path(temp_dir or "") / "result.xlsx"
    if not temp_dir or not result_path.is_file():
        raise HTTPException(404, "Файл не найден или срок его хранения истёк.")
    background_tasks.add_task(manage_temp_dir, normalized_id, "delete", _URL_STATUS_WORK_TYPE)
    return FileResponse(
        result_path,
        filename="url_status_results.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=background_tasks,
    )
