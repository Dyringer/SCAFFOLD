def main() -> None:
    import multiprocessing

    # Required for frozen (PyInstaller) builds that spawn worker processes
    # (the asteroids genetic trainer uses a ProcessPoolExecutor). Without this,
    # each child re-runs the bootloader instead of the worker and can flash a
    # console window. Must run before any pool is created.
    multiprocessing.freeze_support()

    from app.application import run
    run()


if __name__ == "__main__":
    main()
