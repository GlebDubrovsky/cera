"""HTTP-адаптер запуска анализа релевантности и скачивания отчётов."""

from __future__ import annotations

import asyncio
import uuid
import zipfile
from html import escape
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from modules.relevance_analyzer import RelevanceInputError, run_analysis
from modules.relevance_analyzer.export import export_xlsx
from shared.log_stream import run_with_log_capture
from shared.temp_storage import manage_temp_dir

router = APIRouter()
ZIP_MEDIA_TYPE = 'application/zip'
WORK_TYPE = 'relevance_analyzer'


def _run_job(config: dict[str, object]) -> str:
    """Запускает анализ в отдельном временном каталоге и пакует четыре отчёта."""
    print('[RELEVANCE_ANALYZER][INPUT][START] Проверка параметров запуска.', flush=True)
    result = run_analysis(config)
    request_id = str(uuid.uuid4())
    temp_dir = manage_temp_dir(request_id, 'create', WORK_TYPE)
    if not temp_dir:
        raise RuntimeError('Не удалось подготовить временное хранилище результата.')
    try:
        print('[RELEVANCE_ANALYZER][EXPORT][START] Формирование четырёх XLSX-отчётов.', flush=True)
        report_paths = export_xlsx(result, temp_dir)
        archive_path = Path(temp_dir) / 'result.zip'
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for report_path in report_paths:
                archive.write(report_path, arcname=report_path.name)
        print('[RELEVANCE_ANALYZER][EXPORT][SUCCESS] Архив с отчётами готов.', flush=True)
        return request_id
    except Exception:
        manage_temp_dir(request_id, 'delete', WORK_TYPE)
        print('[RELEVANCE_ANALYZER][ERROR][FAILURE] Экспорт не завершён; временный результат удалён.', flush=True)
        raise


def _error_response(error: Exception) -> HTMLResponse:
    if isinstance(error, RelevanceInputError):
        message = str(error)
        status_code = 400
    elif isinstance(error, ValueError) and str(error) == 'Не удалось получить целевую страницу.':
        message = 'Не удалось загрузить целевую страницу. Проверь URL и доступность сайта.'
        status_code = 400
    else:
        message = 'Не удалось выполнить анализ. Проверь журнал этапов и доступность сайтов.'
        status_code = 500
    return HTMLResponse(
        f'<div class="alert alert-danger" role="alert">{escape(message)}</div>',
        status_code=status_code,
    )


@router.post('/relevance-analyzer', response_class=HTMLResponse)
async def submit_analysis(
    link: str = Form(''),
    phrase: str = Form(''),
    sites_text: str = Form(''),
    separator: int = Form(3),
    conjunctions: bool = Form(False),
    list_words_text: str = Form(''),
    log_id: str = Form(''),
) -> HTMLResponse:
    """Запускает анализ сайтов с UI-контролируемым логированием."""
    config: dict[str, object] = {
        'link': link,
        'phrase': phrase,
        'sites': [line.strip() for line in sites_text.splitlines() if line.strip()],
        'separator': separator,
        'conjunctions': conjunctions,
        'list_words': [line.strip() for line in list_words_text.splitlines() if line.strip()],
    }
    try:
        request_id = await asyncio.to_thread(run_with_log_capture, log_id, _run_job, config)
    except Exception as error:
        return _error_response(error)
    return HTMLResponse(
        '<div class="alert alert-success d-flex align-items-center" role="alert">'
        '<span>Анализ завершён. </span>'
        f'<a href="/download/relevance-analyzer/{request_id}" class="btn btn-sm btn-success ms-2" download>'
        'Скачать архив XLSX</a></div>'
    )


@router.get('/download/relevance-analyzer/{request_id}')
async def download_result(request_id: str, background_tasks: BackgroundTasks) -> FileResponse:
    try:
        normalized_id = str(uuid.UUID(request_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail='Файл не найден.') from None
    temp_dir = manage_temp_dir(normalized_id, 'get', WORK_TYPE)
    if not temp_dir:
        raise HTTPException(status_code=404, detail='Файл не найден или срок его хранения истёк.')
    result_path = Path(temp_dir) / 'result.zip'
    if not result_path.is_file():
        raise HTTPException(status_code=404, detail='Файл не найден или срок его хранения истёк.')
    background_tasks.add_task(manage_temp_dir, normalized_id, 'delete', WORK_TYPE)
    return FileResponse(
        result_path,
        filename='relevance_analyzer_reports.zip',
        media_type=ZIP_MEDIA_TYPE,
        background=background_tasks,
    )
