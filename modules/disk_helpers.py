import os

from modules.logger import logger
from modules.metrics import MetricsHandler


def maybe_delete_file_from_disk(path, file_type="video"):
    logger.info(f"deleting {path} from disk")
    if os.path.exists(path):
        MetricsHandler.files_deleted.labels(type=file_type).inc()
        os.remove(path)
    else:
        logger.warning(f"the path {path} didnt exist! skipping deletion")
