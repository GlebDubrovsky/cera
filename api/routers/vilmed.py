"""HTTP-маршруты для операций сервиса Vilmed."""

import asyncio
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from html import escape

from modules.vilmed.category_menu import update_cat_menu_vilmed
from modules.vilmed.overspam import overspam_vilmed
from scenarios.vilmed_product_desc.vilmed_product_desc_relevance import run_product_description_relevance
from scenarios.vilmed_product_desc.vilmed_product_desc_select_words import run_vilmed_product_desc_select_words
from scenarios.vilmed_product_desc.vilmed_product_desc_get_html import run_vilmed_product_desc_get_html
from scenarios.vilmed_product_desc.vilmed_product_desc_insert_html import run_vilmed_product_desc_insert_html
from scenarios.vilmed_product_desc.vilmed_product_desc_mark_in_table import run_vilmed_product_desc_mark_in_table
from scenarios.vilmed_product_desc.vilmed_product_desc_relevance_after import run_product_description_relevance_after
from scenarios.vilmed_product_desc.vilmed_product_desc_serp import run_product_descriptions
from shared.log_stream import run_with_log_capture
from shared.temp_storage import manage_temp_dir

router = APIRouter()
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/overspam", response_class=HTMLResponse)
async def overspam_htmx(
    request: Request,
    file: UploadFile = File(...),
    log_id: str = Form(""),
) -> HTMLResponse:
    if not file.filename or not file.filename.endswith(".xlsx"):
        return HTMLResponse('<div class="alert alert-danger">Требуется файл .xlsx</div>', status_code=400)

    engine = getattr(request.app.state, "database_engine", None)
    if engine is None:
        return HTMLResponse(
            '<div class="alert alert-danger">PostgreSQL не настроен: задайте DATABASE_URL.</div>',
            status_code=503,
        )

    request_id = str(uuid.uuid4())
    temp_dir = manage_temp_dir(request_id, "create", "overspam_vilmed")
    file_path = os.path.join(temp_dir, file.filename)

    try:
        with open(file_path, "wb") as uploaded_file:
            shutil.copyfileobj(file.file, uploaded_file)

        result_df = await asyncio.to_thread(
            run_with_log_capture,
            log_id,
            overspam_vilmed,
            file_path,
            request_id,
            engine,
        )
        if result_df is None or result_df.empty:
            manage_temp_dir(request_id, "delete", "overspam_vilmed")
            return HTMLResponse(
                '<div class="alert alert-danger">Ошибка при обработке или результат пуст</div>',
                status_code=500,
            )

        result_path = os.path.join(temp_dir, "result.xlsx")
        result_df.to_excel(result_path, index=False)
    except Exception:
        manage_temp_dir(request_id, "delete", "overspam_vilmed")
        return HTMLResponse(
            '<div class="alert alert-danger">Ошибка при обработке результата.</div>',
            status_code=500,
        )

    download_url = f"/download/overspam/{request_id}"
    return HTMLResponse(
        '<div class="alert alert-success d-flex align-items-center" role="alert">'
        '<div>Обработка завершена! '
        f'<a href="{download_url}" class="btn btn-sm btn-success ms-2" download>Скачать результат</a>'
        "</div></div>"
    )


@router.get("/download/overspam/{req_id}")
async def download_overspam(req_id: str, background_tasks: BackgroundTasks) -> FileResponse:
    temp_dir = manage_temp_dir(req_id, "get", "overspam_vilmed")
    result_path = os.path.join(temp_dir, "result.xlsx")
    if not os.path.exists(result_path):
        from fastapi import HTTPException

        raise HTTPException(404, "Файл не найден")

    background_tasks.add_task(manage_temp_dir, req_id, "delete", "overspam_vilmed")
    return FileResponse(
        result_path,
        filename="result_overspam_vilmed.xlsx",
        media_type=XLSX_MEDIA_TYPE,
    )


@router.post("/update_cat_menu", response_class=HTMLResponse)
async def update_cat_menu_htmx(
    file: UploadFile = File(...),
    log_id: str = Form(""),
) -> HTMLResponse:
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        return HTMLResponse(
            '<div class="alert alert-danger">Требуется файл таблицы .xlsx или .xls</div>',
            status_code=400,
        )

    target_file_path = _PROJECT_ROOT / "worksheets" / "work_vilmed.xlsx"
    if not target_file_path.is_file():
        return HTMLResponse(
            '<div class="alert alert-danger">Целевой файл work_vilmed.xlsx не найден на сервере. Проверьте путь.</div>',
            status_code=500,
        )

    request_id = str(uuid.uuid4())
    temp_dir = manage_temp_dir(request_id, "create", "update_cat_menu")
    try:
        file_path = os.path.join(temp_dir, file.filename)
        with open(file_path, "wb") as uploaded_file:
            shutil.copyfileobj(file.file, uploaded_file)
        await asyncio.to_thread(
            run_with_log_capture,
            log_id,
            update_cat_menu_vilmed,
            file_path,
            str(target_file_path),
        )
    except Exception:
        manage_temp_dir(request_id, "delete", "update_cat_menu")
        return HTMLResponse(
            '<div class="alert alert-danger">Ошибка при обновлении файла.</div>',
            status_code=500,
        )

    manage_temp_dir(request_id, "delete", "update_cat_menu")
    return HTMLResponse(
        '<div class="alert alert-success d-flex align-items-center" role="alert">'
        '<div>Обработка завершена! Лист \'menu_categories\' в файле work_vilmed.xlsx успешно обновлен.</div>'
        "</div>"
    )


_PRODUCT_DESCRIPTIONS_JOB_ID = "vilmed_product_descriptions"


@router.post("/api/vilmed/product-descriptions/start")
async def start_vilmed_product_descriptions(
    request: Request, log_id: str = ""
) -> dict[str, object]:
    """Запускает сценарий и направляет его stdout в SSE-сессию окна модулей."""
    engine = getattr(request.app.state, "database_engine", None)
    manager = getattr(request.app.state, "job_manager", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="База данных не настроена на сервере.")
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    if not manager.start(
        _PRODUCT_DESCRIPTIONS_JOB_ID,
        run_with_log_capture,
        log_id,
        run_product_descriptions,
        engine,
    ):
        raise HTTPException(status_code=409, detail="Сценарий уже выполняется или останавливается.")
    return {"started": True, **manager.get_status(_PRODUCT_DESCRIPTIONS_JOB_ID)}


@router.post("/api/vilmed/product-descriptions/stop")
async def stop_vilmed_product_descriptions(request: Request) -> dict[str, object]:
    """Запрашивает остановку после завершения текущего поиска товара."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    stop_requested = manager.stop(_PRODUCT_DESCRIPTIONS_JOB_ID)
    return {"stop_requested": stop_requested, **manager.get_status(_PRODUCT_DESCRIPTIONS_JOB_ID)}


@router.get("/api/vilmed/product-descriptions/status")
async def vilmed_product_descriptions_status(request: Request) -> dict[str, object]:
    """Возвращает текущий статус, счётчики и последнее сообщение сценария."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    return manager.get_status(_PRODUCT_DESCRIPTIONS_JOB_ID)


_PRODUCT_DESCRIPTION_RELEVANCE_JOB_ID = "vilmed_product_desc_relevance"


@router.post("/api/vilmed/product-description-relevance/start")
async def start_vilmed_product_description_relevance(
    request: Request, log_id: str = ""
) -> dict[str, object]:
    """Запускает пакетный анализ релевантности товаров Vilmed."""
    engine = getattr(request.app.state, "database_engine", None)
    manager = getattr(request.app.state, "job_manager", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="База данных не настроена на сервере.")
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    if not manager.start(
        _PRODUCT_DESCRIPTION_RELEVANCE_JOB_ID,
        run_with_log_capture,
        log_id,
        run_product_description_relevance,
        engine,
    ):
        raise HTTPException(status_code=409, detail="Сценарий уже выполняется или останавливается.")
    return {"started": True, **manager.get_status(_PRODUCT_DESCRIPTION_RELEVANCE_JOB_ID)}


@router.post("/api/vilmed/product-description-relevance/stop")
async def stop_vilmed_product_description_relevance(request: Request) -> dict[str, object]:
    """Запрашивает остановку после завершения анализа текущего товара."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    stop_requested = manager.stop(_PRODUCT_DESCRIPTION_RELEVANCE_JOB_ID)
    return {"stop_requested": stop_requested, **manager.get_status(_PRODUCT_DESCRIPTION_RELEVANCE_JOB_ID)}


@router.get("/api/vilmed/product-description-relevance/status")
async def vilmed_product_description_relevance_status(request: Request) -> dict[str, object]:
    """Возвращает статус, прогресс и счётчик ошибок сценария."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    return manager.get_status(_PRODUCT_DESCRIPTION_RELEVANCE_JOB_ID)


_PRODUCT_DESCRIPTION_SELECT_WORDS_JOB_ID = "vilmed_product_desc_select_words"


@router.post("/api/vilmed/product-description-select-words/start")
async def start_vilmed_product_description_select_words(
    request: Request, log_id: str = ""
) -> dict[str, object]:
    """Запускает отбор важных слов для товаров Vilmed."""
    engine = getattr(request.app.state, "database_engine", None)
    manager = getattr(request.app.state, "job_manager", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="База данных не настроена на сервере.")
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    if not manager.start(
        _PRODUCT_DESCRIPTION_SELECT_WORDS_JOB_ID,
        run_with_log_capture,
        log_id,
        run_vilmed_product_desc_select_words,
        engine,
    ):
        raise HTTPException(status_code=409, detail="Сценарий уже выполняется или останавливается.")
    return {"started": True, **manager.get_status(_PRODUCT_DESCRIPTION_SELECT_WORDS_JOB_ID)}


@router.post("/api/vilmed/product-description-select-words/stop")
async def stop_vilmed_product_description_select_words(request: Request) -> dict[str, object]:
    """Запрашивает остановку после завершения текущего запроса к модели."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    stop_requested = manager.stop(_PRODUCT_DESCRIPTION_SELECT_WORDS_JOB_ID)
    return {"stop_requested": stop_requested, **manager.get_status(_PRODUCT_DESCRIPTION_SELECT_WORDS_JOB_ID)}


@router.get("/api/vilmed/product-description-select-words/status")
async def vilmed_product_description_select_words_status(request: Request) -> dict[str, object]:
    """Возвращает статус, прогресс и счётчик ошибок отбора слов."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    return manager.get_status(_PRODUCT_DESCRIPTION_SELECT_WORDS_JOB_ID)


_PRODUCT_DESCRIPTION_GET_HTML_JOB_ID = "vilmed_product_desc_get_html"


@router.post("/api/vilmed/product-description-get-html/start")
async def start_vilmed_product_description_get_html(
    request: Request, log_id: str = ""
) -> dict[str, object]:
    """Запускает генерацию HTML-описаний товаров Vilmed."""
    engine = getattr(request.app.state, "database_engine", None)
    manager = getattr(request.app.state, "job_manager", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="База данных не настроена на сервере.")
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    if not manager.start(
        _PRODUCT_DESCRIPTION_GET_HTML_JOB_ID,
        run_with_log_capture,
        log_id,
        run_vilmed_product_desc_get_html,
        engine,
    ):
        raise HTTPException(status_code=409, detail="Сценарий уже выполняется или останавливается.")
    return {"started": True, **manager.get_status(_PRODUCT_DESCRIPTION_GET_HTML_JOB_ID)}


@router.post("/api/vilmed/product-description-get-html/stop")
async def stop_vilmed_product_description_get_html(request: Request) -> dict[str, object]:
    """Запрашивает остановку после завершения текущего запроса к модели."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    stop_requested = manager.stop(_PRODUCT_DESCRIPTION_GET_HTML_JOB_ID)
    return {"stop_requested": stop_requested, **manager.get_status(_PRODUCT_DESCRIPTION_GET_HTML_JOB_ID)}


@router.get("/api/vilmed/product-description-get-html/status")
async def vilmed_product_description_get_html_status(request: Request) -> dict[str, object]:
    """Возвращает статус генерации HTML-описаний."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    return manager.get_status(_PRODUCT_DESCRIPTION_GET_HTML_JOB_ID)


_PRODUCT_DESCRIPTION_INSERT_HTML_JOB_ID = "vilmed_product_desc_insert_html"


@router.post("/api/vilmed/product-description-insert-html/start")
async def start_vilmed_product_description_insert_html(
    request: Request, log_id: str = ""
) -> dict[str, object]:
    """Запускает вставку HTML в карточки товаров Vilmed."""
    engine = getattr(request.app.state, "database_engine", None)
    manager = getattr(request.app.state, "job_manager", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="База данных не настроена на сервере.")
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    if not manager.start(
        _PRODUCT_DESCRIPTION_INSERT_HTML_JOB_ID,
        run_with_log_capture,
        log_id,
        run_vilmed_product_desc_insert_html,
        engine,
    ):
        raise HTTPException(status_code=409, detail="Сценарий уже выполняется или останавливается.")
    return {"started": True, **manager.get_status(_PRODUCT_DESCRIPTION_INSERT_HTML_JOB_ID)}


@router.post("/api/vilmed/product-description-insert-html/stop")
async def stop_vilmed_product_description_insert_html(request: Request) -> dict[str, object]:
    """Просит Selenium остановиться после текущей страницы товара."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    stop_requested = manager.stop(_PRODUCT_DESCRIPTION_INSERT_HTML_JOB_ID)
    return {"stop_requested": stop_requested, **manager.get_status(_PRODUCT_DESCRIPTION_INSERT_HTML_JOB_ID)}


@router.get("/api/vilmed/product-description-insert-html/status")
async def vilmed_product_description_insert_html_status(request: Request) -> dict[str, object]:
    """Возвращает состояние и прогресс вставки HTML."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    return manager.get_status(_PRODUCT_DESCRIPTION_INSERT_HTML_JOB_ID)


_PRODUCT_DESCRIPTION_RELEVANCE_AFTER_JOB_ID = "vilmed_product_desc_relevance_after"


@router.post("/api/vilmed/product-description-relevance-after/start")
async def start_vilmed_product_description_relevance_after(
    request: Request, log_id: str = ""
) -> dict[str, object]:
    """Запускает повторный анализ релевантности после вставки описаний."""
    engine = getattr(request.app.state, "database_engine", None)
    manager = getattr(request.app.state, "job_manager", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="База данных не настроена на сервере.")
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    if not manager.start(
        _PRODUCT_DESCRIPTION_RELEVANCE_AFTER_JOB_ID,
        run_with_log_capture,
        log_id,
        run_product_description_relevance_after,
        engine,
    ):
        raise HTTPException(status_code=409, detail="Сценарий уже выполняется или останавливается.")
    return {"started": True, **manager.get_status(_PRODUCT_DESCRIPTION_RELEVANCE_AFTER_JOB_ID)}


@router.post("/api/vilmed/product-description-relevance-after/stop")
async def stop_vilmed_product_description_relevance_after(request: Request) -> dict[str, object]:
    """Запрашивает остановку после завершения анализа текущего товара."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    stop_requested = manager.stop(_PRODUCT_DESCRIPTION_RELEVANCE_AFTER_JOB_ID)
    return {
        "stop_requested": stop_requested,
        **manager.get_status(_PRODUCT_DESCRIPTION_RELEVANCE_AFTER_JOB_ID),
    }


@router.get("/api/vilmed/product-description-relevance-after/status")
async def vilmed_product_description_relevance_after_status(request: Request) -> dict[str, object]:
    """Возвращает статус и прогресс повторного анализа релевантности."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    return manager.get_status(_PRODUCT_DESCRIPTION_RELEVANCE_AFTER_JOB_ID)


_PRODUCT_DESCRIPTION_MARK_IN_TABLE_JOB_ID = "vilmed_product_desc_mark_in_table"


@router.post("/api/vilmed/product-description-mark-in-table/start")
async def start_vilmed_product_description_mark_in_table(
    request: Request, log_id: str = ""
) -> dict[str, object]:
    """Запускает отметку товаров в административной таблице Vilmed."""
    engine = getattr(request.app.state, "database_engine", None)
    manager = getattr(request.app.state, "job_manager", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="База данных не настроена на сервере.")
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    if not manager.start(
        _PRODUCT_DESCRIPTION_MARK_IN_TABLE_JOB_ID,
        run_with_log_capture,
        log_id,
        run_vilmed_product_desc_mark_in_table,
        engine,
    ):
        raise HTTPException(status_code=409, detail="Сценарий уже выполняется или останавливается.")
    return {"started": True, **manager.get_status(_PRODUCT_DESCRIPTION_MARK_IN_TABLE_JOB_ID)}


@router.post("/api/vilmed/product-description-mark-in-table/stop")
async def stop_vilmed_product_description_mark_in_table(request: Request) -> dict[str, object]:
    """Запрашивает остановку после завершения обработки текущего товара."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    stop_requested = manager.stop(_PRODUCT_DESCRIPTION_MARK_IN_TABLE_JOB_ID)
    return {
        "stop_requested": stop_requested,
        **manager.get_status(_PRODUCT_DESCRIPTION_MARK_IN_TABLE_JOB_ID),
    }


@router.get("/api/vilmed/product-description-mark-in-table/status")
async def vilmed_product_description_mark_in_table_status(request: Request) -> dict[str, object]:
    """Возвращает состояние и прогресс отметки товаров."""
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Менеджер фоновых задач недоступен.")
    return manager.get_status(_PRODUCT_DESCRIPTION_MARK_IN_TABLE_JOB_ID)
