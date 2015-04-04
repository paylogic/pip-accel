try:
    # Python 2.x.
    import ConfigParser as configparser
    from urlparse import urlparse
except ImportError:
    # Python 3.x.
    import configparser
    from urllib.parse import urlparse
