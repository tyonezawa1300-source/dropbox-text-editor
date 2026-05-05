"""
Dropbox 認証セットアップスクリプト
-----------------------------------
このスクリプトを一度だけ実行すると、.streamlit/secrets.toml が自動作成されます。
実行方法:  python setup_dropbox.py
"""

import os
import webbrowser
from dropbox import DropboxOAuth2FlowNoRedirect

print("=" * 50)
print("  Dropbox テキストエディタ  セットアップ")
print("=" * 50)
print()
print("【事前準備】")
print("  1. https://www.dropbox.com/developers/apps にアクセス")
print("  2. 「Create app」をクリック")
print("  3. 「Scoped access」→「Full Dropbox」を選択")
print("  4. 任意の名前を付けて作成")
print("  5. 「App key」と「App secret」をメモしておく")
print("  6. Permissions タブ で files.content.read と files.content.write にチェック")
print()

app_key    = input("App key    を貼り付けてください: ").strip()
app_secret = input("App secret を貼り付けてください: ").strip()

auth_flow = DropboxOAuth2FlowNoRedirect(
    app_key,
    app_secret,
    token_access_type="offline",   # リフレッシュトークン（長期有効）を取得
)

authorize_url = auth_flow.start()
print()
print("【認証】")
print("  以下のURLをブラウザで開き、「許可」をクリックしてください:")
print(f"\n  {authorize_url}\n")

try:
    webbrowser.open(authorize_url)
except Exception:
    pass  # ブラウザが開けなくても手動でOK

auth_code = input("  ページに表示された「認証コード」を貼り付けてください: ").strip()

try:
    oauth_result = auth_flow.finish(auth_code)
    refresh_token = oauth_result.refresh_token
except Exception as e:
    print(f"\n❌ 認証に失敗しました: {e}")
    raise SystemExit(1)

# .streamlit/secrets.toml に保存
os.makedirs(".streamlit", exist_ok=True)
secrets_path = os.path.join(".streamlit", "secrets.toml")

with open(secrets_path, "w", encoding="utf-8") as f:
    f.write(f'DROPBOX_APP_KEY      = "{app_key}"\n')
    f.write(f'DROPBOX_APP_SECRET   = "{app_secret}"\n')
    f.write(f'DROPBOX_REFRESH_TOKEN = "{refresh_token}"\n')

print()
print(f"✅  認証成功！{secrets_path} を保存しました。")
print()
print("次のコマンドでアプリを起動してください:")
print("  streamlit run app.py")
