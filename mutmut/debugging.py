from .setup_logging import configure_logger


logger = configure_logger(__name__)


def inspect_stack() -> None:
    import inspect

    logger.info("\n\n---start---")

    stack = inspect.stack()

    logger.info("Traceback:")
    for level in stack[:]:
        frame = level.frame
        info = inspect.getframeinfo(frame)

        logger.info(f"Function {level.function} in {info.filename}, line {info.lineno}")

    logger.info("---end---\n\n")
