"""PyInstaller 진입 스크립트 (swea-fetch-gui 콘솔 스크립트와 동일)."""
import sys

from swea_fetcher.gui.app import main

if __name__ == "__main__":
    sys.exit(main())
