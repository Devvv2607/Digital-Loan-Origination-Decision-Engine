"""Logging setup with a global safety net that masks PANs and phone numbers."""

import logging

from app.core.masking import mask_text

_installed = False


def _install_masking_record_factory() -> None:
    global _installed
    if _installed:
        return
    base_factory = logging.getLogRecordFactory()

    def factory(*args, **kwargs) -> logging.LogRecord:
        record = base_factory(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # malformed format args: leave the record alone
            return record
        record.msg = mask_text(message)
        record.args = ()
        return record

    logging.setLogRecordFactory(factory)
    _installed = True


def configure_logging(level: str = "INFO") -> None:
    _install_masking_record_factory()
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
