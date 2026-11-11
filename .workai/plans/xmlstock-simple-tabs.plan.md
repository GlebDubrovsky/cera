<!-- workai:plan:update -->

## План: Четыре модуля для XMLRiver и XMLStock

XMLRiver и XMLStock останутся отдельными карточками, но получат одинаковую организацию модулей: **ТОП Яндекс, ТОП Google, частотность и сбор фраз**. Для одинаковых задач будут унифицированы входы, пользовательские параметры и структура итоговых таблиц, а различия API останутся внутри адаптеров каждого провайдера.

### Проблема

Сейчас XMLRiver устроен как три сценария — частотность, фразы и только Яндекс TOP — с общей диспетчеризацией в [registry.py](modules/xmlriver/registry.py#L21-L25). XMLStock пока представляет собой общий клиент произвольных запросов к четырём API, а не четыре пользовательских сценария; его интерфейс показывает ответ как динамически сформированную таблицу или текст ([service.py](modules/xmlstock/service.py#L25-L90), [dashboard.html](templates/dashboard.html#L314-L468) и [dashboard.html](templates/dashboard.html#L480-L625)).

### Связанные файлы

- [modules/xmlriver/registry.py](modules/xmlriver/registry.py#L1-L39), [modules/xmlriver/service.py](modules/xmlriver/service.py#L1-L53), [modules/xmlriver/export.py](modules/xmlriver/export.py#L36-L95) — реестр четырёх задач, общий запуск и фиксированные схемы экспорта.
- [modules/xmlriver/xmlriver_serp.py](modules/xmlriver/xmlriver_serp.py#L1-L183), [modules/xmlriver/xmlriver_frequency.py](modules/xmlriver/xmlriver_frequency.py#L1-L155), [modules/xmlriver/xmlriver_popular.py](modules/xmlriver/xmlriver_popular.py#L1-L157) — существующие модули, которые нужно привести к общей структуре; Google SERP добавить отдельным модулем.
- [modules/xmlstock/service.py](modules/xmlstock/service.py#L25-L90), [modules/xmlstock/validation.py](modules/xmlstock/validation.py#L10-L22), [modules/xmlstock/__init__.py](modules/xmlstock/__init__.py#L1-L16) — сохранить сетевой клиент и валидацию как внутренний слой, добавить запуск сценариев и адаптеры задач.
- [modules/xmlriver/yandex_serp.py](modules/xmlriver/yandex_serp.py), [modules/xmlriver/google_serp.py](modules/xmlriver/google_serp.py), [modules/xmlriver/frequency.py](modules/xmlriver/frequency.py), [modules/xmlriver/phrases.py](modules/xmlriver/phrases.py) — целевой набор файлов задач XMLRiver.
- [modules/xmlstock/yandex_serp.py](modules/xmlstock/yandex_serp.py), [modules/xmlstock/google_serp.py](modules/xmlstock/google_serp.py), [modules/xmlstock/frequency.py](modules/xmlstock/frequency.py), [modules/xmlstock/phrases.py](modules/xmlstock/phrases.py) — такой же набор файлов задач XMLStock.
- [api/routers/xmlriver.py](api/routers/xmlriver.py#L24-L170), [api/routers/xmlstock.py](api/routers/xmlstock.py#L20-L53) — привести HTTP-формы запуска и скачивания результатов к одинаковому контракту ввода.
- [templates/dashboard.html](templates/dashboard.html#L314-L468), [templates/dashboard.html](templates/dashboard.html#L650-L755) — оставить две карточки, но выровнять вкладки, поля и поведение форм.
- [tests/test_xmlriver.py](tests/test_xmlriver.py#L1-L261), [tests/test_xmlstock.py](tests/test_xmlstock.py#L1-L162) — проверить входы, соответствие параметров провайдерским API и единые таблицы.
- [docs/architecture.md](docs/architecture.md#L50-L59) — обновить описание модулей и публичных точек входа.

### Подход

Создать **параллельные наборы из четырёх задач** в каждом пакете, не объединяя разные API в один сетевой клиент. Оба набора будут принимать текстовый список или XLSX с колонкой `phrase`; параметры сценария — регион, период, а для TOP также размер выдачи. Внутри каждого провайдера общий регион и период преобразуются в его собственные параметры API.

Таблицы будут фиксированными и одинаковыми у двух провайдеров в рамках каждой задачи: сбор фраз и оба TOP — по схеме уже существующих таблиц XMLRiver; частотность — с фиксированными столбцами для исходной фразы и значений частоты. Необязательные данные оставлять пустыми, а не менять состав столбцов от ответа к ответу.

### Поток

```mermaid
flowchart LR
    Input[Текст или XLSX] --> Task[Один из четырех сценариев]
    Task --> Provider[XMLRiver или XMLStock]
    Provider --> Normalize[Нормализация ответа]
    Normalize --> Table[Общая таблица сценария]
```

**Шаги**
1. Привести пакеты к параллельной структуре: четыре файла задач и общий реестр в каждом сервисе; XMLStock-сетевой клиент выделить отдельно от диспетчеризации сценариев.
2. Зафиксировать общий контракт ввода: текст или XLSX с колонкой `phrase`, регион России, период и параметр TOP там, где он нужен.
3. Добавить Google TOP в XMLRiver и оформить Яндекс TOP и Google TOP XMLStock как пакетные задачи на том же входном контракте.
4. Реализовать преобразование общего региона России и периодов в параметры каждого API, включая значения по умолчанию.
5. Унифицировать нормализацию ответов и фиксированные столбцы таблиц для четырёх соответствующих задач.
6. Привести оба HTTP-адаптера к одинаковой обработке списка фраз, параметров запуска, ошибок и скачивания XLSX.
7. В `dashboard.html` сохранить две карточки XMLRiver и XMLStock, выровняв в них четыре вкладки и поля форм.
8. Добавить офлайн-тесты Google TOP, пакетного ввода, маппинга региона и периода, а также совпадения заголовков таблиц.
9. Обновить карту архитектуры и публичные точки входа в `docs/architecture.md`.

**Проверка**
1. Запустить `python -m unittest tests.test_xmlriver tests.test_xmlstock`.
2. Проверить вручную каждый из четырёх сценариев в обеих карточках: текстовый ввод, XLSX, регион и период, скачивание таблицы.
3. Для каждой соответствующей пары модулей сравнить заголовки и порядок столбцов в XLSX, включая ответ с пустыми данными и ошибку отдельной фразы.

**Решения**
- XMLRiver и XMLStock остаются раздельными провайдерами с одинаковыми пользовательскими задачами и параллельной организацией файлов.
- XMLStock Яндекс TOP планируется выполнять через `yandex_live` как основной режим с периодом; XML Proxy остаётся низкоуровневым вариантом, не отдельной пользовательской вкладкой.
- Совпадение схемы таблиц не гарантирует, что частотные показатели двух провайдеров полностью эквивалентны по смыслу; это нужно учитывать при нормализации и подписывании столбцов.
- Локальная реализация XMLRiver Google TOP пока отсутствует, но официальная документация описывает Google API и параметры `loc`, `tbs` и `page`; в Google нумерация страниц начинается с 1. Региональные идентификаторы XMLRiver и XMLStock следует сопоставлять отдельно, не передавая один и тот же ID вслепую.

**Источники**
- [Документация XMLRiver: параметры Google API](https://xmlriver.com/apidoc/api-about/)
- [Документация XMLRiver: структура органической выдачи Google](https://xmlriver.com/apidoc/api-organic/)