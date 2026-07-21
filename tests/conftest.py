import pytest

from app import main
from app.services.competitions import clear_competition_cache
from app.services.faq import clear_faq_cache
from app.site_content import clear_site_content_cache


@pytest.fixture(autouse=True)
def clear_process_caches():
    clear_competition_cache()
    clear_faq_cache()
    clear_site_content_cache()
    main.clear_health_cache()
    yield
    clear_competition_cache()
    clear_faq_cache()
    clear_site_content_cache()
    main.clear_health_cache()
