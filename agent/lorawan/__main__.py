from __future__ import annotations

import argparse
import logging
import signal
from pathlib import Path
from typing import Callable

from gateway_runtime.lte_power import (
    GatewayLtePowerController,
    GatewayPowerConfigError,
    GatewayPowerError,
    load_gateway_power_config,
)

from .chirpstack import ChirpStackError, ChirpStackUplink, MqttDependencyError
from .radio import RadioIngressError
from .service import GatewayService, GatewayServiceConfigError, load_gateway_service_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the EdgeWatch LoRaWAN gateway service")
    parser.add_argument("--config", type=Path, required=True, help="mode-0600 gateway YAML file")
    return parser


def gateway_power_callbacks(
    controller: GatewayLtePowerController,
    *,
    hold_ttl_s: int = 120,
) -> tuple[
    Callable[[ChirpStackUplink], None],
    Callable[[], bool],
    Callable[[], None],
    Callable[[], None],
]:
    """Adapt the shared LTE scheduler to LoRa ingest and outbox boundaries."""

    def observe_uplink(uplink: ChirpStackUplink) -> None:
        if not controller.config.enabled:
            return
        if (
            not uplink.requires_immediate_alert
            or controller.snapshot().get("active") is True
            or controller.config.trigger_path.exists()
        ):
            return
        controller.request_immediate("alert")
        logging.info(
            "LoRaWAN alert requested an immediate LTE window device_id=%s message_id=%s",
            uplink.device_id,
            uplink.message_id,
        )

    def delivery_ready() -> bool:
        if not controller.config.enabled:
            return True
        return controller.snapshot().get("active") is True

    def acquire_delivery_hold() -> None:
        controller.acquire_hold("lorawan-outbox", ttl_s=hold_ttl_s)

    def release_delivery_hold() -> None:
        controller.release_hold("lorawan-outbox")

    return observe_uplink, delivery_ready, acquire_delivery_hold, release_delivery_hold


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        config, registry = load_gateway_service_config(args.config)
        gateway_power = GatewayLtePowerController(load_gateway_power_config())
        uplink_observer, delivery_ready, hold_acquire, hold_release = gateway_power_callbacks(
            gateway_power,
            hold_ttl_s=max(120, config.outbox.lease_s),
        )
        service = GatewayService(
            config,
            registry,
            uplink_observer=uplink_observer,
            delivery_ready=delivery_ready,
            delivery_hold_acquire=hold_acquire,
            delivery_hold_release=hold_release,
        )
    except (
        GatewayPowerConfigError,
        GatewayPowerError,
        GatewayServiceConfigError,
        ChirpStackError,
        OSError,
    ) as exc:
        logging.error("LoRaWAN gateway configuration failed: %s", exc)
        return 2

    def _stop(_signum: int, _frame: object) -> None:
        service.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        service.run_forever()
    except MqttDependencyError as exc:
        logging.error("LoRaWAN gateway cannot start: %s", exc)
        return 2
    except RadioIngressError as exc:
        logging.error("LoRaWAN gateway radio ingress is not ready: %s", exc)
        return 2
    except KeyboardInterrupt:
        service.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
