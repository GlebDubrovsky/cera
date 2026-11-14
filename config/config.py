import os
from dotenv import load_dotenv

load_dotenv()

XMLRIVER_USER = os.getenv("XMLRIVER_USER", "").strip()
XMLRIVER_KEY = os.getenv("XMLRIVER_KEY", "").strip()
VILMED_LOGIN = os.getenv("VILMED_LOGIN", "").strip()
VILMED_PASSWORD = os.getenv("VILMED_PASSWORD", "")


def get_database_url() -> str | None:
    """Читает адрес базы из окружения, не выводя его в журналы."""
    return os.getenv("DATABASE_URL", "").strip() or None


HEADERS = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.8,en-US;q=0.5,en;q=0.3',
            'Connection': 'keep-alive',
        }

CONFIG_LINK_SELECTION_BAR_TAGS = {
            'almamed' : {
                            'domain_full_name' : 'https://almamed.su',
                            'path_cat' : '/category/',
                            'breadcrumbs_item' : '.breadcrumbs-plugin__item__label',
                            'h1' : '.title_h1.category-name',
                            'left_bar_tags' : '.tags-params-sidebar a',
                            'up_bar_tags' : '.tag-slider a',
                            'search_link_pattern' : '/search/',
                            'product_item' : 'ul.product-list a',    
                        },
            'vilmed' :  {
                            'domain_full_name' : 'https://vilmed.ru',
                            'path_cat' : '/catalog/',
                            'breadcrumbs_item' : '.breadcrumb__title',
                            'h1' : '#pagetitle',
                            'left_bar_tags' : '.tag_menu a',
                            'up_bar_tags' : '.tag-slider a',
                            'search_link_pattern' : r'/catalog/\?q=',
                            'product_item' : '#catalog a',
                            'submit_param' : '&submit=Найти'
                        },
            'gnkmed' :  {
                            'domain_full_name' : 'https://gnkmed.ru',
                            'path_cat' : '/catalog/',
                            'breadcrumbs_item' : 'li.breadcrumb__item:not(:first-child) span',
                            'h1' : 'h1.title',
                            'up_bar_tags' : '.tag-slider a',
                            'search_link_pattern' : r'/search/\?q=',
                            'product_item' : '.goods__list a.goods__name',
                            'links_type' : 'nested'
                        },
            'lorshop' : {
                            'domain_full_name' : 'https://lorshop.ru',
                            'path_cat' : '/catalog/',
                            'breadcrumbs_item' : 'li.breadcrumb__item:not(:first-child) span',
                            'h1' : 'h1.title',
                            'up_bar_tags' : '.tag-slider a',
                            'search_link_pattern' : r'/search/\?q=',
                            'product_item' : '.goods__list a.goods__name',
                            'links_type' : 'nested'
                        },
            'riester' : {
                            'domain_full_name' : 'https://riester.su',
                            'path_cat' : '/catalog/',
                            'breadcrumbs_item' : 'li.breadcrumb__item:not(:first-child) span',
                            'h1' : 'h1.title',
                            'up_bar_tags' : '.tag-slider a',
                            'search_link_pattern' : r'/search/\?q=',
                            'product_item' : '.goods__list a.goods__name',
                            'links_type' : 'nested'
                        }
}

CONFIG_YANDEX_LOUD_API = {
    'folder' : os.getenv('YANDEX_CLOUD_FOLDER_ID', ''),
    'api_key' : os.getenv('YANDEX_CLOUD_API_KEY', ''),
    'model' : os.getenv('YANDEX_CLOUD_MODEL', 'deepseek-v4-flash/latest')
}

RELEVANCE_AGGREGATOR_DOMAINS = [
    'megamarket.ru', '2gis.ru', 'aliexpress.com', 'AliExpress.ru', 'auto.ru',
    'avito.ru', 'm.avito.ru', 'banki.ru', 'beru.ru', 'blizko.ru', 'cataloxy.ru',
    'deal.by', 'domclick.ru', 'dzen.ru', 'ebay.com', 'edadeal.ru', 'e-katalog.ru',
    'hh.ru', 'instagram.com', 'irecommend.ru', 'irr.ru', 'leroymerlin.ru',
    'market.yandex.ru', 'translate.yandex.ru', 'mvideo.ru', 'onliner.by',
    'otzovik.com', 'ozon.ru', 'pandao.ru', 'price.ru', 'prodoctorov.ru', 'profi.ru',
    'pulscen.ru', 'quto.ru', 'rambler.ru', 'regmarkets.ru', 'satom.ru', 'shop.by',
    'sravni.ru', 'tiu.ru', 'toshop.ru', 'wikipedia.org', 'ru.wikipedia.org',
    'wildberries.ru', 'yandex.ru', 'yell.ru', 'zoon.ru', 'uslugi.yandex.ru',
    'www.youtube.com', 'youtube.com',
]

RELEVANCE_EXCLUDED_WORDS = [
    'руб', 'арт', 'еще', 'ооо', 'так', 'я', 'мы', 'ты', 'вы', 'он', 'она', 'оно',
    'они', 'себя', 'мой', 'твой', 'ваш', 'наш', 'свой', 'его', 'ее', 'их', 'это',
    'тот', 'этот', 'такой', 'таков', 'столько', 'весь', 'всякий', 'сам', 'самый', 'к',
]

VILMED_INSERT_PRODUCT_DESCRIPTION = {
    'login_url': 'https://vilmed.ru/bitrix/admin/index.php#authorize',
    'edit_url_template': (
        'https://vilmed.ru/bitrix/admin/iblock_element_edit.php?'
        'IBLOCK_ID=24&type=catalog&lang=ru&ID={product_id}&find_section_section=-1&WF=Y'
    ),
    'selectors': {
        'login': 'input[name="USER_LOGIN"]',
        'password': 'input[name="USER_PASSWORD"]',
        'login_submit': 'input[name="Login"]',
        'detail_tab': 'span[title="Детальная информация ( Ctrl+Alt+Q ) "]',
        'html_mode': '#bxed_DETAIL_TEXT_html',
        'html_textarea': 'textarea#bxed_DETAIL_TEXT',
        'save': 'input#save',
        'save_success': 'div.adm-info-message',
        'save_error': 'div.adm-info-message-red, .adm-input-error',
    },
    'wait_timeout_seconds': 60,
    'between_products_delay_seconds': 1.5,
    'after_text_entry_delay_seconds': 3.0,
}
