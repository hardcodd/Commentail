"""Create the example home once; preserve existing site/page settings on reruns."""

from django.core.management.base import BaseCommand
from django.db import transaction
from wagtail.models import Page, Site

from demo_home.models import HomePage, Product


class Command(BaseCommand):
    help = "Create the local Commentail example home without creating users."

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        page = HomePage.objects.filter(slug="commentail-demo").first()
        if page is None:
            root = Page.get_first_root_node()
            page = HomePage(title="Commentail demo", slug="commentail-demo")
            root.add_child(instance=page)
            page.save_revision().publish()
            site = Site.objects.filter(is_default_site=True).first()
            if site is None:
                Site.objects.create(
                    hostname="127.0.0.1",
                    port=8000,
                    root_page=page,
                    is_default_site=True,
                )
            else:
                site.hostname, site.port, site.root_page = "127.0.0.1", 8000, page
                site.save()
        site = Site.objects.get(is_default_site=True)
        product, _ = Product.objects.get_or_create(
            site=site, title="Adapter demo product"
        )
        self.stdout.write(f"Object adapter demo: /products/{product.pk}/")
        self.stdout.write("Commentail example home is ready.")
