try:
    # Python 2.x.
    from StringIO import StringIO
    from urlparse import urlparse
    import ConfigParser as configparser
except ImportError:
    # Python 3.x.
    from io import StringIO
    from urllib.parse import urlparse
    import configparser
