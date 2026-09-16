"""入出庫イベントをtracking-parking-apiへ送信する機能。

API_ENABLED=false（既定）の間はどのモジュールもrequestsをimportせず、
既存の検知処理の挙動に一切影響しない。有効化は runtime.ApiRuntime.create()
の送信ガード（カメラ入力 かつ API_ENABLED=true）を経由する。
"""
