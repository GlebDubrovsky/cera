"""FastAPI-маршруты для веб-запуска модулей XMLRiver."""

from __future__ import annotations

import asyncio
import uuid
from html import escape
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from scripts.live_log_stream import run_with_log_capture
from scripts.manage_temp_dir import manage_temp_dir
from xmlriver.export import append_phrasal_values_xlsx, write_results_xlsx
from xmlriver.input import PhraseInputError, parse_phrases
from xmlriver.registry import MODULES
from xmlriver.service import XMLRiverConfigurationError, run_module

router = APIRouter()
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _run_job(
    module_id: str,
    phrases_text: str,
    filename: str,
    content: bytes,
    top_n: int,
    phrasal_only: bool = False,
) -> str:
    """Обрабатывает запрос, сохраняя результат в отдельной временной папке."""
    print(f"[XMLRIVER][{module_id.upper()}][INPUT][START] Проверка входных данных.", flush=True)
    phrases = parse_phrases(phrases_text, filename or None, content or None)
    print(f"[XMLRIVER][{module_id.upper()}][INPUT][SUCCESS] Подготовлено фраз: {len(phrases)}.", flush=True)

    request_id = str(uuid.uuid4())
    work_type = f"xmlriver_{module_id}"
    temp_dir = manage_temp_dir(request_id, "create", work_type)
    if not temp_dir:
        raise RuntimeError("Не удалось подготовить временное хранилище результата.")

    frequency_mode = "base"
    if module_id == "frequency":
        frequency_mode = "phrasal" if filename and phrasal_only else "both"

    try:
        if frequency_mode == "base":
            results = run_module(module_id, phrases, top_n=top_n)
        else:
            results = run_module(module_id, phrases, top_n=top_n, frequency_mode=frequency_mode)
        print(f"[XMLRIVER][{module_id.upper()}][EXPORT][START] Формирование таблицы XLSX.", flush=True)
        output_path = Path(temp_dir) / "result.xlsx"
        if module_id == "frequency" and filename and phrasal_only:
            append_phrasal_values_xlsx(output_path, content, results)
        else:
            write_results_xlsx(output_path, module_id, results)
        print(f"[XMLRIVER][{module_id.upper()}][EXPORT][SUCCESS] Файл XLSX готов.", flush=True)
        return request_id
    except Exception:
        manage_temp_dir(request_id, "delete", work_type)
        print(f"[XMLRIVER][{module_id.upper()}][ERROR] Задача прервана; временный результат удалён.", flush=True)
        raise


def _error_response(error: Exception) -> HTMLResponse:
    """Показывает безопасные ошибки ввода и настройки, не детали API."""
    if isinstance(error, (PhraseInputError, XMLRiverConfigurationError)):
        message = str(error)
    elif isinstance(error, ValueError):
        message = "Некорректные параметры запуска. Проверь ввод и выбери допустимое число результатов."
    else:
        message = "Не удалось выполнить обработку. Проверь настройки и журнал этапов."
    return HTMLResponse(
        f'<div class="alert alert-danger" role="alert">{escape(message)}</div>',
        status_code=400 if isinstance(error, (PhraseInputError, ValueError)) else 500,
    )


async def _submit(
    module_id: str,
    phrases_text: str,
    phrases_file: UploadFile | None,
    log_id: str,
    top_n: int = 10,
    phrasal_only: bool = False,
) -> HTMLResponse:
    filename = phrases_file.filename or "" if phrases_file else ""
    content = await phrases_file.read(MAX_UPLOAD_BYTES + 1) if phrases_file and filename else b""
    if len(content) > MAX_UPLOAD_BYTES:
        return HTMLResponse('<div class="alert alert-danger">Размер XLSX-файла не должен превышать 10 МБ.</div>', status_code=400)

    try:
        request_id = await asyncio.to_thread(
            run_with_log_capture,
            log_id,
            _run_job,
            module_id,
            phrases_text,
            filename,
            content,
            top_n,
            phrasal_only,
        )
    except Exception as error:
        return _error_response(error)

    download_url = f"/download/xmlriver/{module_id}/{request_id}"
    return HTMLResponse(
        '<div class="alert alert-success d-flex align-items-center" role="alert">'
        '<span>Обработка завершена. </span>'
        f'<a href="{download_url}" class="btn btn-sm btn-success ms-2" download>Скачать XLSX</a>'
        '</div>'
    )


@router.post("/xmlriver/frequency", response_class=HTMLResponse)
async def run_frequency(
    phrases_text: str = Form(""),
    phrases_file: UploadFile | None = File(None),
    log_id: str = Form(""),
    phrasal_only: bool = Form(False),
) -> HTMLResponse:
    return await _submit("frequency", phrases_text, phrases_file, log_id, phrasal_only=phrasal_only)


@router.post("/xmlriver/popular", response_class=HTMLResponse)
async def run_popular(
    phrases_text: str = Form(""),
    phrases_file: UploadFile | None = File(None),
    log_id: str = Form(""),
) -> HTMLResponse:
    return await _submit("popular", phrases_text, phrases_file, log_id)


@router.post("/xmlriver/serp", response_class=HTMLResponse)
async def run_serp(
    phrases_text: str = Form(""),
    phrases_file: UploadFile | None = File(None),
    top_n: int = Form(10),
    log_id: str = Form(""),
) -> HTMLResponse:
    return await _submit("serp", phrases_text, phrases_file, log_id, top_n)


@router.get("/download/xmlriver/{module_id}/{request_id}")
async def download_result(module_id: str, request_id: str, background_tasks: BackgroundTasks) -> FileResponse:
    if module_id not in MODULES:
        raise HTTPException(status_code=404, detail="Файл не найден.")
    try:
        normalized_id = str(uuid.UUID(request_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail="Файл не найден.") from None

    work_type = f"xmlriver_{module_id}"
    temp_dir = manage_temp_dir(normalized_id, "get", work_type)
    if not temp_dir:
        raise HTTPException(status_code=404, detail="Файл не найден или срок его хранения истёк.")
    result_path = Path(temp_dir) / "result.xlsx"
    if not result_path.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден или срок его хранения истёк.")
    background_tasks.add_task(manage_temp_dir, normalized_id, "delete", work_type)
    return FileResponse(
        result_path,
        filename=f"xmlriver_{module_id}.xlsx",
        media_type=XLSX_MEDIA_TYPE,
        background=background_tasks,
    )
