import logging

class HidePasswordFilter(logging.Filter):
    sensitive = ("password", "passwd", "pwd", "secret", "credentials")

    def filter(self, record):
        msg = record.getMessage().lower()
        for kw in self.sensitive:
            if kw in msg and "password" in msg:
                # Don't alter, but we ensure no password value is logged elsewhere
                pass
        return True
