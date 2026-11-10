"""HTTP-адаптер запуска сценария генерации NEWS-метатегов и выдачи ZIP."""

from __future__ import annotations

import asyncio
import uuid
import zipfile
from html import escape
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from modules.openai_api import OpenAIConfigurationError
from scenarios.auto_news_meta_tags import AutoNewsInputError, run_auto_news_meta_tags
from shared.log_stream import run_with_log_capture
from shared.prompt_templates import PromptTemplateError
from shared.temp_storage import manage_temp_dir

router = APIRouter()
WORK_TYPE = 'auto_news_meta_tags'
MAX_FILENAME_LENGTH = 120


def _safe_filename(title: str, index: int, used_names: set[str]) -> str:
    """Нормализует заголовок в безопасное имя и устраняет совпадения."""
    safe_title = ''.join(char if char.isalnum() or char in ' -_.' else '_' for char in title)
    safe_title = ' '.join(safe_title.split()).strip(' ._')[:MAX_FILENAME_LENGTH].rstrip(' .')
    base_name = safe_title or f'page_{index}'
    candidate = f'{base_name}.txt'
    suffix = 2
    while candidate.casefold() in used_names:
        candidate = f'{base_name} ({suffix}).txt'
        suffix += 1
    used_names.add(candidate.casefold())
    return candidate


def _run_job(urls: list[str]) -> tuple[str | None, int, int]:
    """Запускает сценарий и сохраняет успешные ответы как отдельные TXT в ZIP."""
    results = run_auto_news_meta_tags(urls)
    successful_results = [result for result in results if result.answer]
    failed_count = len(results) - len(successful_results)
    if not successful_results:
        return None, 0, failed_count

    request_id = str(uuid.uuid4())
    temp_dir = manage_temp_dir(request_id, 'create', WORK_TYPE)
    if not temp_dir:
        raise RuntimeError('Не удалось подготовить временное хранилище результата.')
    try:
        output_dir = Path(temp_dir)
        used_names: set[str] = set()
        text_files: list[Path] = []
        for index, result in enumerate(successful_results, start=1):
            file_path = output_dir / _safe_filename(result.title, index, used_names)
            file_path.write_text(result.answer, encoding='utf-8')
            text_files.append(file_path)
        archive_path = output_dir / 'result.zip'
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in text_files:
                archive.write(file_path, arcname=file_path.name)
        print(f'[AUTO_NEWS][EXPORT][SUCCESS] Подготовлено текстовых файлов: {len(text_files)}.', flush=True)
        return request_id, len(successful_results), failed_count
    except Exception:
        manage_temp_dir(request_id, 'delete', WORK_TYPE)
        print('[AUTO_NEWS][EXPORT][FAILURE] Не удалось подготовить архив результатов.', flush=True)
        raise


def _error_response(error: Exception) -> HTMLResponse:
    if isinstance(error, AutoNewsInputError):
        message, status_code = str(error), 400
    elif isinstance(error, OpenAIConfigurationError):
        message, status_code = 'OpenAI API не настроен на сервере.', 503
    elif isinstance(error, PromptTemplateError):
        message, status_code = 'Не удалось загрузить или заполнить шаблон промпта.', 500
    else:
        message, status_code = 'Не удалось выполнить сценарий. Проверь журнал этапов.', 500
    return HTMLResponse(f'<div class="alert alert-danger" role="alert">{escape(message)}</div>', status_code=status_code)


@router.post('/auto-landings/meta-tags-news', response_class=HTMLResponse)
async def submit_auto_news_meta_tags(
    links_text: str = Form(''),
    log_id: str = Form(''),
) -> HTMLResponse:
    """Принимает URL из формы и вызывает независимый от HTTP код сценария."""
    urls = [line.strip() for line in links_text.splitlines() if line.strip()]
    try:
        request_id, successful_count, failed_count = await asyncio.to_thread(
            run_with_log_capture,
            log_id,
            _run_job,
            urls,
        )
    except Exception as error:
        return _error_response(error)

    if not request_id:
        return HTMLResponse(
            '<div class="alert alert-danger" role="alert">Не удалось обработать ни одной страницы. Проверь журнал этапов.</div>',
            status_code=502,
        )
    partial_message = f' Ошибок: {failed_count}.' if failed_count else ''
    return HTMLResponse(
        '<div class="alert alert-success d-flex align-items-center flex-wrap gap-2" role="alert">'
        f'<span>Готово: {successful_count} файлов.{escape(partial_message)}</span>'
        f'<a href="/download/auto-landings/meta-tags-news/{request_id}" class="btn btn-sm btn-success" download>'
        'Скачать TXT-файлы (ZIP)</a></div>'
    )


@router.get('/download/auto-landings/meta-tags-news/{request_id}')
async def download_auto_news_result(request_id: str, background_tasks: BackgroundTasks) -> FileResponse:
    try:
        normalized_id = str(uuid.UUID(request_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=404, detail='Файл не найден.') from None
    temp_dir = manage_temp_dir(normalized_id, 'get', WORK_TYPE)
    if not temp_dir:
        raise HTTPException(status_code=404, detail='Файл не найден или срок его хранения истёк.')
    archive_path = Path(temp_dir) / 'result.zip'
    if not archive_path.is_file():
        raise HTTPException(status_code=404, detail='Файл не найден или срок его хранения истёк.')
    background_tasks.add_task(manage_temp_dir, normalized_id, 'delete', WORK_TYPE)
    return FileResponse(
        archive_path,
        filename='auto_news_meta_tags.zip',
        media_type='application/zip',
        background=background_tasks,
    )
