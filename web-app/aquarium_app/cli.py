from __future__ import annotations

import argparse
import logging

import uvicorn

from .config import Settings
from .demo import seed_demo
from .store import Store


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart Aquarium Dashboard")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="run the web server")
    user_parser = subparsers.add_parser("create-user", help="create a dashboard user")
    user_parser.add_argument("username")
    user_parser.add_argument("--role", choices=["viewer", "operator", "admin"], default="admin")
    user_parser.add_argument("--password", required=True)
    cleanup_parser = subparsers.add_parser("cleanup", help="apply the configured retention policy")
    cleanup_parser.add_argument("--days", type=int)
    cleanup_parser.add_argument("--vacuum", action="store_true")
    subparsers.add_parser("seed-demo", help="insert deterministic data for a review environment")
    args = parser.parse_args()

    settings = Settings.from_env()
    store = Store(settings)
    if args.command == "create-user":
        store.initialize()
        user = store.create_user(args.username, args.password, args.role)
        print(f"Created {user['username']} ({user['role']})")
        return
    if args.command == "cleanup":
        store.initialize()
        print(store.cleanup(args.days, vacuum=args.vacuum))
        return
    if args.command == "seed-demo":
        print(seed_demo(store))
        return

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        "aquarium_app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )


if __name__ == "__main__":
    main()
