try:
    # Python 2.x.
    import ConfigParser as configparser
    from urllib import unquote
    from urlparse import urlparse
except ImportError:
    # Python 3.x.
    import configparser
    from urllib.parse import unquote
    from urllib.parse import urlparse
