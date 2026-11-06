#!/usr/bin/env python3
"""
ota_push.py — push a firmware .bin to a running ESP32-S3 CAM over WiFi.

Author : Daniel Dyringer
Date   : 2026-08-13

PC-side tooling (not firmware). A command-line front end for client.py (the
protocol the ESP OTA subapp uses): uploads the raw image body to
POST /ota/upload, then (unless --no-reboot) triggers a reboot via the /ota/ws
WebSocket action and polls GET / a few times to confirm the device comes back.

Stdlib only — no Qt, no third-party deps.

Usage (from the repo root):
    python -m app.subapps.esp_ota.ota_push --ip 192.168.1.42 --file build/cam.bin
    python -m app.subapps.esp_ota.ota_push --ip 192.168.1.42 --file build/cam.bin --no-reboot
"""

import argparse
import os
import sys
import time

from app.subapps.esp_ota.client import (
    DEFAULT_PORT,
    POLL_ATTEMPTS,
    POLL_DELAY_S,
    UPLOAD_PATH,
    OtaUpload,
    probe,
    send_reboot,
)


def upload(ip, port, path):
    size = os.path.getsize(path)
    print("Uploading %s (%d bytes) to %s:%d%s ..." % (path, size, ip, port, UPLOAD_PATH))

    last_pct = -1
    t_start = time.monotonic()

    def on_progress(sent, total):
        nonlocal last_pct
        pct = int(100 * sent / total)
        if pct != last_pct:
            elapsed = max(time.monotonic() - t_start, 1e-6)
            sys.stdout.write("\r  %3d%% (%d / %d bytes)  %7.1f KB/s"
                             % (pct, sent, total, sent / elapsed / 1024))
            sys.stdout.flush()
            last_pct = pct

    result = OtaUpload(ip, port, path).run(on_progress)
    print()
    # sent_s only covers handing bytes to the OS socket buffer; total_s also
    # includes draining it to the device and ota_finish() image validation.
    print("  Sent in %.2f s, response after %.2f s — effective %.1f KB/s"
          % (result.sent_s, result.total_s, size / result.total_s / 1024))

    if not result.ok:
        print("Upload failed: HTTP %d — %s" % (result.status, result.body))
        return False

    print("Upload OK: %s" % result.body)
    return True


def trigger_reboot(ip, port):
    print("Triggering reboot ...")
    try:
        send_reboot(ip, port)
    except OSError as e:
        # The device may drop the connection immediately as it reboots —
        # that's the expected outcome, not a failure of this step.
        print("  (connection dropped during reboot trigger: %s — expected)" % e)


def poll_alive(ip, port):
    print("Waiting for device to come back up ...")
    for attempt in range(1, POLL_ATTEMPTS + 1):
        time.sleep(POLL_DELAY_S)
        if probe(ip, port, timeout=3.0):
            print("  Device is back up (attempt %d/%d)." % (attempt, POLL_ATTEMPTS))
            return True
        sys.stdout.write(".")
        sys.stdout.flush()

    print()
    print("  Device did not respond after %d attempts." % POLL_ATTEMPTS)
    return False


def main():
    parser = argparse.ArgumentParser(description="Push a firmware .bin to ESP32-S3 CAM over WiFi.")
    parser.add_argument("--ip", required=True, help="Device IP address")
    parser.add_argument("--file", required=True, help="Path to the firmware .bin")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTP port (default 80)")
    parser.add_argument("--no-reboot", action="store_true",
                        help="Skip the post-upload reboot trigger; leave the update staged")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        print("File not found: %s" % args.file)
        return 1

    if not upload(args.ip, args.port, args.file):
        return 1

    if args.no_reboot:
        print("Update staged — reboot manually via the web page or console when ready.")
        return 0

    trigger_reboot(args.ip, args.port)

    if not poll_alive(args.ip, args.port):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
