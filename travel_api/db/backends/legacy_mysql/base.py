"""Local compatibility backend for XAMPP's legacy MariaDB 10.4 server.

Production must use Django's standard MySQL backend. This adapter changes only
the version gate; Django's existing MariaDB feature detection remains active.
"""

from django.db.backends.mysql.base import DatabaseWrapper as MySQLDatabaseWrapper
from django.db.backends.mysql.features import DatabaseFeatures as MySQLDatabaseFeatures
from django.utils.functional import cached_property


class DatabaseFeatures(MySQLDatabaseFeatures):
    @cached_property
    def minimum_database_version(self):
        if self.connection.mysql_is_mariadb:
            return (10, 4)
        return super().minimum_database_version

    @cached_property
    def can_return_columns_from_insert(self):
        if self.connection.mysql_is_mariadb:
            return self.connection.mysql_version >= (10, 5)
        return super().can_return_columns_from_insert


class DatabaseWrapper(MySQLDatabaseWrapper):
    features_class = DatabaseFeatures
