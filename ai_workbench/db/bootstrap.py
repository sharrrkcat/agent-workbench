"""Short-lived schema migration entry point for application startup."""
import argparse

from ai_workbench.db.database import get_engine, init_db


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    engine = get_engine(args.database_url)
    try:
        init_db(engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
