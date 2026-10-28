from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from scripts.live_log_stream import run_with_log_capture, stream_session
from fastapi.staticfiles import StaticFiles
import os, shutil, uuid
from config.config import CONFIG_LINK_SELECTION_BAR_TAGS, HEADERS
from scripts.manage_temp_dir import manage_temp_dir
from scripts.check_links import check_link
from scripts.link_selection_bar_tags import link_selection_bar_tags
from scripts.update_cat_menu_vilmed import update_cat_menu_vilmed
from projects.vilmed.overspam_vilmed import overspam_vilmed
from html import escape
from scripts.keywords_search import keywords_search as run_keywords_search
from scripts.open_list_links import open_links_in_browser
import asyncio
from concurrent.futures import ThreadPoolExecutor

app = FastAPI()

# Подключаем шаблоны
templates = Jinja2Templates(directory="templates")

# Папка для файлов, которые нужно подключать локально
app.mount("/static", StaticFiles(directory="static"), name="static")

# 1. Главная страница с интерфейсом
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html")


@app.post("/cleanup_temp_files")
async def cleanup_temp_files():
    deleted_count = manage_temp_dir("all", "delete_all", "all")
    if deleted_count is None:
        raise HTTPException(500, "Не удалось очистить временные папки")
    return {"deleted": deleted_count}


@app.get("/logs/{log_id}")
async def live_logs(log_id: str):
    return StreamingResponse(
        stream_session(log_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ============ ЭНДПОИНТ 1: BAR TAGS ============
@app.post("/bar_tags", response_class=HTMLResponse)
async def bar_tags_htmx(
    file: UploadFile = File(...),
    category_url: str = Form(...),
    log_id: str = Form("")
):
    if not file.filename.endswith(".xlsx"):
        return HTMLResponse('<div class="alert alert-danger">Требуется файл .xlsx</div>', status_code=400)
    
    if not category_url.startswith("http") or not check_link(category_url, HEADERS):
        return HTMLResponse('<div class="alert alert-danger">Неверный или недоступный URL</div>', status_code=400)

    req_id = str(uuid.uuid4())
    temp_dir = manage_temp_dir(req_id, "create", "bar_tags")
    file_path = os.path.join(temp_dir, file.filename)
    
    try:
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Определяем домен из URL
        domain = next((d for d in CONFIG_LINK_SELECTION_BAR_TAGS if d in category_url), None)
        ws_url = os.path.join("worksheets", f"work_{domain}.xlsx")

        # Основная обработка
        res_df = await asyncio.to_thread(
            run_with_log_capture,
            log_id,
            link_selection_bar_tags,
            file_path,
            ws_url,
            category_url,
            CONFIG_LINK_SELECTION_BAR_TAGS
        )
        res_path = os.path.join(temp_dir, "result.xlsx")
        res_df.to_excel(res_path, index=False)
    except Exception as exc:
        manage_temp_dir(req_id, "delete", "bar_tags")
        return HTMLResponse(
            f'<div class="alert alert-danger">Ошибка при обработке: {escape(str(exc))}</div>',
            status_code=500
        )

    download_url = f"/download/bar_tags/{req_id}"

    html_response = f"""
    <div class="alert alert-success d-flex align-items-center" role="alert">
        <div>
            Обработка завершена!
            <a href="{download_url}" class="btn btn-sm btn-success ms-2" download>Скачать результат</a>
        </div>
    </div>
    """
    return HTMLResponse(content=html_response)

# Эндпоинт для скачивания bar_tags
@app.get("/download/bar_tags/{req_id}")
async def download_bar_tags(req_id: str, background_tasks: BackgroundTasks):
    temp_dir = manage_temp_dir(req_id, "get", "bar_tags")
    res_path = os.path.join(temp_dir, "result.xlsx")
    
    if not os.path.exists(res_path):
        raise HTTPException(404, "Файл не найден или срок его хранения истек")
    
    background_tasks.add_task(manage_temp_dir, req_id, "delete", "bar_tags")
    
    return FileResponse(
        res_path, 
        filename="result_bar_tags.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ============ ЭНДПОИНТ 3: OVERSPAM ============
@app.post("/overspam", response_class=HTMLResponse)
async def overspam_htmx(
    file: UploadFile = File(...),
    log_id: str = Form("")
):
    if not file.filename.endswith(".xlsx"):
        return HTMLResponse('<div class="alert alert-danger">Требуется файл .xlsx</div>', status_code=400)

    req_id = str(uuid.uuid4())
    temp_dir = manage_temp_dir(req_id, "create", "overspam_vilmed")
    file_path = os.path.join(temp_dir, file.filename)

    try:
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        res_df = await asyncio.to_thread(
            run_with_log_capture,
            log_id,
            overspam_vilmed,
            file_path,
            req_id
        )
        if res_df is None or res_df.empty:
            manage_temp_dir(req_id, "delete", "overspam_vilmed")
            return HTMLResponse(
                '<div class="alert alert-danger">Ошибка при обработке или результат пуст</div>',
                status_code=500
            )

        res_path = os.path.join(temp_dir, "result.xlsx")
        res_df.to_excel(res_path, index=False)
    except Exception as exc:
        manage_temp_dir(req_id, "delete", "overspam_vilmed")
        return HTMLResponse(
            f'<div class="alert alert-danger">Ошибка при обработке: {escape(str(exc))}</div>',
            status_code=500
        )

    download_url = f"/download/overspam/{req_id}"
    
    html_response = f"""
    <div class="alert alert-success d-flex align-items-center" role="alert">
        <div>
            Обработка завершена! 
            <a href="{download_url}" class="btn btn-sm btn-success ms-2" download>Скачать результат</a>
        </div>
    </div>
    """
    return HTMLResponse(content=html_response)

# ============ ЭНДПОИНТ 4: KEYWORDS SEARCH ============

@app.post("/keywords_search", response_class=HTMLResponse)
async def keywords_search_htmx(
    file: UploadFile = File(...),
    prompt_file: UploadFile = File(...),
    log_id: str = Form("")
):
    # Проверяем расширение файла с таблицей.
    if not str(file.filename or "").lower().endswith(".xlsx"):
        return HTMLResponse(
            '<div class="alert alert-danger">Требуется файл таблицы .xlsx</div>',
            status_code=400
        )

    # Проверяем расширение файла с шаблоном промпта.
    if not str(prompt_file.filename or "").lower().endswith((".txt", ".md")):
        return HTMLResponse(
            '<div class="alert alert-danger">Требуется файл шаблона .txt или .md</div>',
            status_code=400
        )

    # Создаём временную папку для запроса.
    req_id = str(uuid.uuid4())
    temp_dir = manage_temp_dir(req_id, "create", "keywords_search")

    try:
        # Сохраняем загруженные файлы во временную папку.
        file_path = os.path.join(temp_dir, file.filename)
        prompt_path = os.path.join(temp_dir, prompt_file.filename)

        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        with open(prompt_path, "wb") as f:
            shutil.copyfileobj(prompt_file.file, f)

        # Запускаем модуль подбора ключевых фраз.
        res_df = await asyncio.to_thread(
            run_with_log_capture,
            log_id,
            run_keywords_search,
            file_path,
            prompt_path
        )

        # Если результат пустой, отдаём ошибку.
        if res_df is None or res_df.empty:
            manage_temp_dir(req_id, "delete", "keywords_search")
            return HTMLResponse(
                '<div class="alert alert-danger">Ошибка при обработке или результат пуст</div>',
                status_code=500
            )

        # Сохраняем результат в Excel.
        res_path = os.path.join(temp_dir, "result.xlsx")
        res_df.to_excel(res_path, index=False)
    except Exception as exc:
        manage_temp_dir(req_id, "delete", "keywords_search")
        return HTMLResponse(
            f'<div class="alert alert-danger">{escape(str(exc))}</div>',
            status_code=400
        )

    download_url = f"/download/keywords_search/{req_id}"

    html_response = f"""
    <div class="alert alert-success d-flex align-items-center" role="alert">
        <div>
            Обработка завершена!
            <a href="{download_url}" class="btn btn-sm btn-success ms-2" download>
                Скачать результат
            </a>
        </div>
    </div>
    """

    return HTMLResponse(content=html_response)

# Эндпоинт для скачивания keywords_search
@app.get("/download/keywords_search/{req_id}")
async def download_keywords_search(req_id: str, background_tasks: BackgroundTasks):
    # Получаем временную папку запроса.
    temp_dir = manage_temp_dir(req_id, "get", "keywords_search")

    res_path = os.path.join(temp_dir, "result.xlsx")

    # Если файла нет, значит запрос старый или уже удалён.
    if not os.path.exists(res_path):
        raise HTTPException(404, "Файл не найден или срок его хранения истёк")

    # Удаляем временную папку после отдачи файла.
    background_tasks.add_task(
        manage_temp_dir,
        req_id,
        "delete",
        "keywords_search"
    )

    return FileResponse(
        res_path,
        filename="result_keywords_search.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# Эндпоинт для скачивания overspam
@app.get("/download/overspam/{req_id}")
async def download_overspam(req_id: str, background_tasks: BackgroundTasks):
    temp_dir = manage_temp_dir(req_id, "get", "overspam_vilmed")
    res_path = os.path.join(temp_dir, "result.xlsx")
    
    if not os.path.exists(res_path):
        raise HTTPException(404, "Файл не найден")
    
    background_tasks.add_task(manage_temp_dir, req_id, "delete", "overspam_vilmed")
    
    return FileResponse(
        res_path, 
        filename="result_overspam_vilmed.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ============ ЭНДПОИНТ 5: OPEN LIST LINKS ============
@app.post("/open_links", response_class=HTMLResponse)
async def open_links_htmx(
    request: Request,
    links_text: str = Form(...)
):
    if not links_text or not links_text.strip():
        return HTMLResponse(
            '<div class="alert alert-danger">Введите список ссылок</div>',
            status_code=400
        )

    # Запускаем открытие ссылок в отдельном потоке
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    count = await loop.run_in_executor(
        executor,
        open_links_in_browser,
        links_text,
        1  # Задержка 1 секунда
    )

    return HTMLResponse(
        f'<div class="alert alert-success">Процесс завершен!</div>'
    )


# ============ ЭНДПОИНТ 6: UPDATE CAT MENU VILMED ============
@app.post("/update_cat_menu", response_class=HTMLResponse)
async def update_cat_menu_htmx(
    file: UploadFile = File(...),
    log_id: str = Form("")
):
    # 1. Проверяем расширение загружаемого файла
    if not file.filename.lower().endswith((".xlsx", ".xls")):
        return HTMLResponse(
            '<div class="alert alert-danger">Требуется файл таблицы .xlsx или .xls</div>',
            status_code=400
        )

    # 2. Определяем путь к целевому файлу work_vilmed.xlsx
    # ВАЖНО: Убедитесь, что файл work_vilmed.xlsx лежит в корне проекта (рядом с main_test.py)
    target_file_path = os.path.join(os.getcwd(), "worksheets/work_vilmed.xlsx")
    
    if not os.path.exists(target_file_path):
        return HTMLResponse(
            '<div class="alert alert-danger">Целевой файл work_vilmed.xlsx не найден на сервере. Проверьте путь.</div>',
            status_code=500
        )

    # 3. Создаем временную папку и сохраняем туда загруженный файл
    req_id = str(uuid.uuid4())
    temp_dir = manage_temp_dir(req_id, "create", "update_cat_menu")

    # 4. Сохраняем файл и запускаем модуль обновления
    try:
        file_path = os.path.join(temp_dir, file.filename)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        # Функция ничего не возвращает, она просто модифицирует target_file_path
        await asyncio.to_thread(
            run_with_log_capture,
            log_id,
            update_cat_menu_vilmed,
            file_path,
            target_file_path
        )
    except Exception as exc:
        # При ошибке удаляем временную папку и возвращаем сообщение
        manage_temp_dir(req_id, "delete", "update_cat_menu")
        return HTMLResponse(
            f'<div class="alert alert-danger">Ошибка при обновлении файла: {escape(str(exc))}</div>',
            status_code=500
        )

    # 5. Удаляем временную папку после успешного выполнения
    manage_temp_dir(req_id, "delete", "update_cat_menu")

    # 6. Возвращаем успешный HTMX ответ
    html_response = """
    <div class="alert alert-success d-flex align-items-center" role="alert">
        <div>
            Обработка завершена! Лист 'menu_categories' в файле work_vilmed.xlsx успешно обновлен.
        </div>
    </div>
    """
    return HTMLResponse(html_response)



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)