import os
from dotenv import load_dotenv

load_dotenv()

XMLRIVER_USER = os.getenv("XMLRIVER_USER", "").strip()
XMLRIVER_KEY = os.getenv("XMLRIVER_KEY", "").strip()


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