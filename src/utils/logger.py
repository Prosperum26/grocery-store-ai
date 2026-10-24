"""Application logging: một logger chung, không ghi khóa API hay nội dung câu hỏi."""
import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format=_FORMAT)
    return logging.getLogger(name)
