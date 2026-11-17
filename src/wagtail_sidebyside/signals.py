from wagtail.signals import page_published

from .use_cases.sync_tree import SyncTree


def propagate_source_publish(sender, instance, revision, **kwargs):
    # A signal, not the after_publish_page hook, so scheduled publishing and
    # publishing from code are covered too.
    if SyncTree.is_source(instance):
        SyncTree.propagate(revision.as_object(), user=revision.user)


def connect():
    page_published.connect(
        propagate_source_publish, dispatch_uid="sidebyside_propagate"
    )
