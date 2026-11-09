from django.core.management.commands.loaddata import Command as DjangoCommand

from common.management.guard import RefusedCommandMixin


class Command(RefusedCommandMixin, DjangoCommand):
    refused_name = "loaddata"
