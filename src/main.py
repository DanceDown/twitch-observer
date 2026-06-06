"""Application entry point wiring gateways, entrypoints, services and persistence together."""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from src.bootstrap import build_core, build_entrypoints, build_gateways, build_runtime, build_services, start_runtime, stop_runtime
from src.config import AppConfig


async def _run() -> None:
    """Boot the application and keep it running until shutdown is requested."""
    config = AppConfig()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("discord.client")
    core = await build_core(config)
    gateways = build_gateways(core)
    services = build_services(core, gateways)
    entrypoints = build_entrypoints(core, services, gateways)
    runtime = build_runtime(core, services, gateways)

    stop_event = asyncio.Event()

    def _request_stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signum, _request_stop)

    await start_runtime(runtime, entrypoints, task_failure_callback=_log_background_task_failure)

    try:
        await stop_event.wait()
    finally:
        await stop_runtime(core, entrypoints, runtime)


def main() -> None:
    """Start the async application runtime."""
    asyncio.run(_run())


def _log_background_task_failure(task: asyncio.Task[object]) -> None:
    """Log unexpected background task failures immediately."""
    if task.cancelled():
        return
    try:
        error = task.exception()
    except asyncio.CancelledError:
        return
    if error is not None:
        logging.getLogger(__name__).error(
            "Background task %s stopped unexpectedly.",
            task.get_name(),
            exc_info=(type(error), error, error.__traceback__),
        )


if __name__ == "__main__":
    main()
