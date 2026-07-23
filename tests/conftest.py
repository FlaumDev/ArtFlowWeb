import pytest

from app import main
from app.site_content import clear_site_content_cache


@pytest.fixture(autouse=True)
def clear_process_caches():
    main.clear_application_caches(main.app)
    clear_site_content_cache()
    yield
    main.clear_application_caches(main.app)
    clear_site_content_cache()
