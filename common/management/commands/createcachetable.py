from django.core.management.commands.createcachetable import Command as DjangoCommand

from common.management.guard import RefusedCommandMixin


class Command(RefusedCommandMixin, DjangoCommand):
    refused_name = "createcachetable"
