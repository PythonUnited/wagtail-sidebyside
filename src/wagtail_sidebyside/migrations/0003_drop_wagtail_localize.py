from django.db import migrations


class Migration(migrations.Migration):
    """No operations. Before the first release this was a data migration of
    the project the package was built in; kept so installations from that
    time keep a consistent migration history."""

    dependencies = [("sidebyside", "0002_translationsettings")]

    operations = []
