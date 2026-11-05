"""HTTP routes for Vilmed-specific processing."""

import asyncio
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from html import escape

from modules.vilmed.category_menu import update_cat_menu_vilmed
from shared.log_stream import run_with_log_capture
from shared.temp_storage import manage_temp_dir
from modules.vilmed.overspam import overspam_vilmed

router = APIRouter()
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post("/overspam", response_class=HTMLResponse)
async def overspam_htmx(
    file: UploadFile = File(...),
    log_id: str = Form(""),
) -> HTMLResponse:
    if not file.filename or not file.filename.endswith(".xlsx"):
        return HTMLResponse('<div class="alert alert-danger">Требуется файл .xlsx</div>', status_code=400)

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
        )
        if result_df is None or result_df.empty:
            manage_temp_dir(request_id, "delete", "overspam_vilmed")
            return HTMLResponse(
                '<div class="alert alert-danger">Ошибка при обработке или результат пуст</div>',
                status_code=500,
            )

        result_path = os.path.join(temp_dir, "result.xlsx")
        result_df.to_excel(result_path, index=False)
    except Exception as error:
        manage_temp_dir(request_id, "delete", "overspam_vilmed")
        return HTMLResponse(
            f'<div class="alert alert-danger">Ошибка при обработке: {escape(str(error))}</div>',
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
    except Exception as error:
        manage_temp_dir(request_id, "delete", "update_cat_menu")
        return HTMLResponse(
            f'<div class="alert alert-danger">Ошибка при обновлении файла: {escape(str(error))}</div>',
            status_code=500,
        )

    manage_temp_dir(request_id, "delete", "update_cat_menu")
    return HTMLResponse(
        '<div class="alert alert-success d-flex align-items-center" role="alert">'
        '<div>Обработка завершена! Лист \'menu_categories\' в файле work_vilmed.xlsx успешно обновлен.</div>'
        "</div>"
    )
