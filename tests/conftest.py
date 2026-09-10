"""テストからCLIスクリプトを読めるようにする。

src/tracking_parking はeditable installで解決できるが、scripts/ 配下は
パッケージではないため import パスに載らない。個々のテストで sys.path を
いじる代わりに、ここ1箇所へ集約する。
"""
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
