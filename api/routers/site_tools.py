"""Endpoints for domain-neutral website analysis tools."""

import asyncio
import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from html import escape

from config.config import CONFIG_LINK_SELECTION_BAR_TAGS, HEADERS
from modules.site_tools.bar_tags import link_selection_bar_tags
from modules.site_tools.open_links import open_links_in_browser
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
