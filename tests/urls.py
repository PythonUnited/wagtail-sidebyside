from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.urls import include, path
from wagtail import urls as wagtail_urls
from wagtail.admin import urls as wagtailadmin_urls

urlpatterns = [path("cms/", include(wagtailadmin_urls))]
urlpatterns += i18n_patterns(path("", include(wagtail_urls)))
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
