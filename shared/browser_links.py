import webbrowser
import time


def open_links_in_browser(links_text: str, delay: int = 1) -> int:
    """
    Открывает список ссылок в браузере.

    Args:
        links_text: Текст со списком ссылок (каждая с новой строки)
        delay: Задержка между открытиями в секундах

    Returns:
        Количество открытых ссылок
    """
    lines = [line.strip() for line in links_text.split('\n') if line.strip()]

    for i, link in enumerate(lines):
        webbrowser.open(link)
        if i < len(lines) - 1 and delay > 0:
            time.sleep(delay)

    return len(lines)