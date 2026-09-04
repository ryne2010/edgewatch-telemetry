#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import threading
import time
import uuid
from pathlib import Path

from gateway_runtime.artifact_cache import ArtifactCache, ArtifactCacheServer
from gateway_runtime.lte_power import GatewayLtePowerController, load_gateway_power_config
from telegram_controller.config import load_config
from telegram_controller.heartbeat import DeadManHeartbeat, load_heartbeat_config
from telegram_controller.service import ControllerService
from telegram_controller.ssh_dispatch import DeviceDispatcher
from telegram_controller.store import ControllerStore
from telegram_controller.telegram import TelegramClient, TelegramError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the EdgeWatch Telegram fleet controller")
    parser.add_argument("--config", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(args.config)
    token = config.telegram.token_file.read_text(encoding="utf-8").strip()
    client = TelegramClient(token, timeout_s=config.telegram.request_timeout_s)
    store = ControllerStore(config.database_path)
    heartbeat_config = load_heartbeat_config()
    deadman = DeadManHeartbeat(heartbeat_config) if heartbeat_config is not None else None
    gateway_power = GatewayLtePowerController(load_gateway_power_config())
    if gateway_power.config.enabled:
        gateway_power.recover_interrupted_window()
    artifact_cache = None
    artifact_server = None
    if config.artifact_cache is not None:
        hold_ttl_s = min(14_400, max(120, config.artifact_cache.download_timeout_s * 4))
        artifact_cache = ArtifactCache(
            config.artifact_cache,
            hold_acquire=lambda name: gateway_power.acquire_hold(name, ttl_s=hold_ttl_s),
            hold_release=gateway_power.release_hold,
        )
        artifact_server = ArtifactCacheServer(artifact_cache)
        artifact_server.start()
    dispatcher = DeviceDispatcher(config, artifact_cache=artifact_cache)
    service = ControllerService(config, store, dispatcher)
    stop_worker = threading.Event()
    worker_id = f"controller-{uuid.uuid4()}"

    def dispatch_loop() -> None:
        while not stop_worker.is_set():
            if gateway_power.config.enabled and gateway_power.snapshot().get("active") is not True:
                stop_worker.wait(0.25)
                continue
            try:
                worked = service.dispatch_once(worker_id)
            except Exception:
                logging.exception("durable dispatch worker failed; lease recovery will retry")
                worked = False
            stop_worker.wait(0.05 if worked else 0.25)

    worker = threading.Thread(
        target=dispatch_loop,
        name="edgewatch-durable-dispatch",
        daemon=True,
    )
    worker.start()
    try:
        while True:
            if gateway_power.config.enabled and gateway_power.snapshot().get("active") is not True:
                reason = gateway_power.next_reason()
                if reason is None:
                    stop_worker.wait(min(1.0, gateway_power.seconds_until_due()))
                    continue
                gateway_power.open_window(reason)
                logging.info(
                    "LTE control window opened (%s; electrical_switching=%s)",
                    reason,
                    gateway_power.config.electrically_switched,
                )
            try:
                for update in client.get_updates(
                    offset=store.next_update_offset(), poll_timeout_s=config.telegram.poll_timeout_s
                ):
                    service.handle_update(update)
                if deadman is not None:
                    deadman.poll()
                for reply in store.pending_replies():
                    try:
                        message_id = client.send_message(reply["chat_id"], reply["text"], reply["topic_id"])
                        store.mark_reply_sent(reply["id"], message_id)
                    except TelegramError:
                        store.mark_reply_attempt(reply["id"])
            except TelegramError as exc:
                logging.warning("%s", exc)
                time.sleep(2)

            if gateway_power.config.enabled:
                busy = bool(
                    store.pending_command_ids()
                    or store.pending_replies()
                    or (deadman is not None and deadman.in_flight)
                    or gateway_power.has_active_holds()
                )
                if gateway_power.should_close(busy=busy):
                    gateway_power.close_window()
                    logging.info("LTE control window closed")
    except KeyboardInterrupt:
        return 0
    finally:
        stop_worker.set()
        worker.join(timeout=2)
        if artifact_server is not None:
            artifact_server.stop()
        if gateway_power.config.enabled and gateway_power.snapshot().get("active") is True:
            try:
                gateway_power.close_window()
            except Exception:
                logging.exception("LTE power-off failed during controller shutdown")


if __name__ == "__main__":
    raise SystemExit(main())
