"""Chạy agent ở chế độ console (không cài Windows Service) — dùng để test thủ công trên máy
pilot trước khi rải qua GPO, hoặc debug tại chỗ."""
import argparse
import logging
import threading

from .config import DEFAULT_CONFIG_PATH, load_config
from .poll_loop import PollLoop


def main():
    parser = argparse.ArgumentParser(description="RyanDeploy Agent (chế độ console)")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Đường dẫn agent.ini")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config(args.config)
    stop_event = threading.Event()
    loop = PollLoop(config, stop_event, config_path=args.config)
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        stop_event.set()


if __name__ == "__main__":
    main()
