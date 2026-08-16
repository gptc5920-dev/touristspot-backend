import pymysql


# Django's MySQL backend imports the MySQLdb interface. PyMySQL implements that
# interface without compiling or bundling a native MySQL client library.
pymysql.install_as_MySQLdb()
