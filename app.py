import streamlit as st
import streamlit.components.v1 as components
import dropbox
import datetime

st.set_page_config(
    page_title="Dropbox テキストエディタ",
    page_icon="📝",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── スタイル ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* iPhoneでの文字ズーム防止（16px以上でズームしない） */
input, textarea, select { font-size: 16px !important; }

.stTextArea textarea {
    font-size: 16px !important;
    line-height: 1.8 !important;
    font-family: 'Hiragino Kaku Gothic ProN', 'Hiragino Sans',
                 'Yu Gothic', Meiryo, sans-serif;
}
.stButton button {
    min-height: 44px;
    text-align: left !important;
    font-family: 'Menlo', 'Courier New', monospace !important;
    font-size: 14px !important;
    letter-spacing: 0;
    white-space: pre;
}
h1 { font-size: 1.4rem !important; }
h2, h3 { font-size: 1.1rem !important; }
</style>
""", unsafe_allow_html=True)

# ── セッション初期化 ──────────────────────────────────────────────────────────
for key, default in {
    "expanded_folders": set(),
    "open_file":        None,
    "content":          "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ── Dropboxクライアント ───────────────────────────────────────────────────────
@st.cache_resource
def get_dbx():
    try:
        return dropbox.Dropbox(
            app_key=st.secrets["DROPBOX_APP_KEY"],
            app_secret=st.secrets["DROPBOX_APP_SECRET"],
            oauth2_refresh_token=st.secrets["DROPBOX_REFRESH_TOKEN"],
        )
    except Exception as e:
        st.error(f"Dropbox接続エラー: {e}")
        st.stop()


@st.cache_data(ttl=60)
def list_folder(path: str) -> list:
    try:
        dbx = get_dbx()
        res = dbx.files_list_folder(path)
        entries = list(res.entries)
        while res.has_more:
            res = dbx.files_list_folder_continue(res.cursor)
            entries.extend(res.entries)
        return entries
    except Exception as e:
        st.error(f"フォルダ読み込みエラー: {e}")
        return []


def fmt_date(dt_utc):
    ts = dt_utc.timestamp() + 9 * 3600  # JST
    return datetime.datetime.utcfromtimestamp(ts).strftime("%Y/%m/%d %H:%M")


def render_tree(path: str, prefix: str = ""):
    """Explorerスタイルのツリーを再帰的に描画する"""
    items = list_folder(path)
    if not items:
        return

    ascending = st.session_state.get("sort_order", "降順（新しい順）") == "昇順（古い順）"
    keyword   = st.session_state.get("search_query", "").strip().lower()

    folders = sorted(
        [e for e in items if isinstance(e, dropbox.files.FolderMetadata)],
        key=lambda e: e.name.lower(),
    )
    files = sorted(
        [e for e in items if isinstance(e, dropbox.files.FileMetadata)
         and e.name.lower().endswith(EDITABLE_EXTS)
         and (not keyword or keyword in e.name.lower())],
        key=lambda e: e.server_modified,
        reverse=not ascending,
    )

    all_items = folders + files
    total     = len(all_items)
    is_root   = (prefix == "")

    for i, item in enumerate(all_items):
        is_last   = (i == total - 1)
        # ルート直下はコネクタなし・左端揃え、サブ以降はExplorerスタイル
        connector = "" if is_root else ("└─ " if is_last else "├─ ")
        child_pfx = prefix + ("   " if is_root else ("      " if is_last else "│    "))

        if isinstance(item, dropbox.files.FolderMetadata):
            is_open = item.path_display in st.session_state.expanded_folders
            icon    = "📂" if is_open else "📁"
            label   = f"{prefix}{connector}{icon} {item.name}"
            if st.button(label, key=f"d_{item.path_display}",
                         use_container_width=True):
                if is_open:
                    st.session_state.expanded_folders.discard(item.path_display)
                else:
                    st.session_state.expanded_folders.add(item.path_display)
                st.rerun()
            if is_open:
                render_tree(item.path_display, child_pfx)

        else:
            label = f"{prefix}{connector}📄 {item.name}  🕐 {fmt_date(item.server_modified)}"
            if st.button(label, key=f"f_{item.path_display}",
                         use_container_width=True):
                content = read_file(item.path_display)
                if content is not None:
                    st.session_state.open_file = item.path_display
                    st.session_state.content   = content
                    wk = f"editor_{hash(item.path_display)}"
                    if wk in st.session_state:
                        del st.session_state[wk]
                    st.rerun()


EDITABLE_EXTS = (".txt", ".md", ".text", ".log", ".csv", ".tsv")

def read_file(path: str):
    try:
        _, res = get_dbx().files_download(path)
        return res.content.decode("utf-8")
    except Exception as e:
        st.error(f"ファイル読み込みエラー: {e}")
        return None


def save_file(path: str, content: str) -> bool:
    try:
        get_dbx().files_upload(
            content.encode("utf-8"),
            path,
            mode=dropbox.files.WriteMode.overwrite,
        )
        return True
    except Exception as e:
        st.error(f"保存エラー: {e}")
        return False


# ── カーソル / Undo-Redo ツールバー（iframeで親のtextareaを操作）────────────
TOOLBAR_HTML = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: transparent; padding: 4px 0; }
.bar {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: nowrap;
  overflow-x: auto;
  padding: 2px 4px;
}
button {
  flex-shrink: 0;
  min-width: 50px;
  min-height: 46px;
  font-size: 22px;
  border: 1.5px solid #bbb;
  border-radius: 10px;
  background: #f6f6f6;
  color: #333;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  user-select: none;
  -webkit-user-select: none;
  display: flex;
  align-items: center;
  justify-content: center;
  touch-action: manipulation;
}
button:active { background: #ddd; border-color: #999; }
.sep { flex-shrink: 0; width: 1.5px; height: 36px; background: #ccc; }
.btn-text { font-size: 14px; padding: 0 10px; }
</style>
</head>
<body>
<div class="bar">
  <button id="bu"    title="上へ">↑</button>
  <button id="bd"    title="下へ">↓</button>
  <button id="bl"    title="左へ">←</button>
  <button id="br"    title="右へ">→</button>
  <div class="sep"></div>
  <button id="bundo" class="btn-text" title="取り消し">↩ 取消</button>
  <button id="bredo" class="btn-text" title="やり直し">↪ 復元</button>
</div>

<script>
(function () {
  'use strict';

  // 親フレームの textarea を取得
  function getTA() {
    try { return window.parent.document.querySelector('textarea'); }
    catch (e) { return null; }
  }

  // ── カスタム Undo / Redo スタック ────────────────────────────────────────
  var hist = [];
  var hi   = -1;
  var MAX_HIST = 200;
  var registeredTA = null;

  function pushHist(ta) {
    // hi より後の履歴を削除
    if (hi < hist.length - 1) hist.splice(hi + 1);
    hist.push({ v: ta.value, s: ta.selectionStart });
    if (hist.length > MAX_HIST) { hist.shift(); } else { hi++; }
  }

  function setupListener() {
    var ta = getTA();
    if (!ta) { setTimeout(setupListener, 200); return; }
    if (ta === registeredTA) return;
    registeredTA = ta;
    hist = [{ v: ta.value, s: ta.selectionStart || 0 }];
    hi   = 0;
    ta.addEventListener('input', function () { pushHist(ta); });
  }

  // React の controlled input を書き換えるトリック
  function setReactValue(ta, value, pos) {
    var setter = Object.getOwnPropertyDescriptor(
      window.parent.HTMLTextAreaElement.prototype, 'value'
    ).set;
    setter.call(ta, value);
    ta.dispatchEvent(new window.parent.Event('input', { bubbles: true }));
    ta.focus();
    try { ta.setSelectionRange(pos, pos); } catch (e) {}
  }

  function doUndo() {
    var ta = getTA();
    if (!ta || hi <= 0) return;
    hi--;
    setReactValue(ta, hist[hi].v, hist[hi].s);
  }

  function doRedo() {
    var ta = getTA();
    if (!ta || hi >= hist.length - 1) return;
    hi++;
    setReactValue(ta, hist[hi].v, hist[hi].s);
  }

  // ── カーソル移動 ─────────────────────────────────────────────────────────
  function moveCursor(dir) {
    var ta   = getTA();
    if (!ta) return;
    var pos  = ta.selectionStart;
    var text = ta.value;
    var np   = pos;

    if (dir === 'l') {
      np = Math.max(0, pos - 1);
    } else if (dir === 'r') {
      np = Math.min(text.length, pos + 1);
    } else if (dir === 'u') {
      var ls  = text.lastIndexOf('\\n', pos - 1) + 1;
      var col = pos - ls;
      if (ls > 0) {
        var pe = ls - 1;
        var ps = text.lastIndexOf('\\n', pe - 1) + 1;
        np = ps + Math.min(col, pe - ps);
      } else {
        np = 0;
      }
    } else if (dir === 'd') {
      var le = text.indexOf('\\n', pos);
      if (le !== -1) {
        var ls2  = text.lastIndexOf('\\n', pos - 1) + 1;
        var col2 = pos - ls2;
        var nls  = le + 1;
        var nle  = text.indexOf('\\n', nls);
        var nll  = nle !== -1 ? nle - nls : text.length - nls;
        np = nls + Math.min(col2, nll);
      }
    }

    ta.focus();
    try { ta.setSelectionRange(np, np); } catch (e) {}
  }

  // ── ボタンバインド ───────────────────────────────────────────────────────
  function bind(id, fn) {
    var btn = document.getElementById(id);
    // mousedown で preventDefault → PC・タッチパッドでフォーカスを奪わない
    btn.addEventListener('mousedown', function (e) { e.preventDefault(); });
    // touchstart + preventDefault → iOS でフォーカスを奪わずに実行
    btn.addEventListener('touchstart', function (e) {
      e.preventDefault();
      fn();
    }, { passive: false });
    // click はフォールバック
    btn.addEventListener('click', fn);
  }

  bind('bu',    function () { moveCursor('u'); });
  bind('bd',    function () { moveCursor('d'); });
  bind('bl',    function () { moveCursor('l'); });
  bind('br',    function () { moveCursor('r'); });
  bind('bundo', doUndo);
  bind('bredo', doRedo);

  setupListener();
})();
</script>
</body>
</html>"""


# ── メイン UI ────────────────────────────────────────────────────────────────
st.title("📝 Dropbox テキストエディタ")

# ─ ファイルブラウザ ──────────────────────────────────────────────────────────
if st.session_state.open_file is None:

    # 新規ファイル作成
    with st.expander("➕ 新規テキストファイルを作成"):
        st.caption("パス例: memo.txt　または　フォルダ名/memo.txt")
        new_name = st.text_input("ファイル名", key="new_file_name",
                                 placeholder="memo.txt")
        if st.button("作成する", key="create_file_btn"):
            if not new_name.strip():
                st.warning("ファイル名を入力してください。")
            elif not new_name.lower().endswith(EDITABLE_EXTS):
                st.warning("拡張子は .txt / .md などにしてください。")
            else:
                new_path = "/" + new_name.strip().lstrip("/")
                if save_file(new_path, ""):
                    list_folder.clear()  # キャッシュをクリアして一覧を更新
                    st.session_state.open_file = new_path
                    st.session_state.content   = ""
                    wk = f"editor_{hash(new_path)}"
                    if wk in st.session_state:
                        del st.session_state[wk]
                    st.rerun()

    # 検索・並び順
    search = st.text_input("🔍 ファイル名を検索", placeholder="キーワードを入力...",
                           key="search_query")
    st.radio("並び順（更新日）",
             options=["降順（新しい順）", "昇順（古い順）"],
             horizontal=True, key="sort_order")

    st.divider()

    # ツリー表示（ルートから再帰展開）
    render_tree("")

# ─ エディタ ─────────────────────────────────────────────────────────────────
else:
    file_path = st.session_state.open_file
    file_name = file_path.rsplit("/", 1)[-1]

    col_title, col_back = st.columns([3, 1])
    with col_title:
        st.subheader(f"✏️  {file_name}")
    with col_back:
        if st.button("← 一覧へ", use_container_width=True):
            st.session_state.open_file = None
            st.rerun()

    # カーソル / Undo-Redo ツールバー（テキストエリアの上に配置）
    components.html(TOOLBAR_HTML, height=58)

    # ウィジェットキーにファイルパスを含めることで別ファイルを開いたとき確実にリセット
    widget_key = f"editor_{hash(file_path)}"

    # 初回だけ session_state にセット（以降はユーザー入力が優先される）
    if widget_key not in st.session_state:
        st.session_state[widget_key] = st.session_state.content

    edited = st.text_area(
        label="編集エリア",
        height=400,
        label_visibility="collapsed",
        key=widget_key,
    )

    st.markdown("---")

    save_btn_col, _ = st.columns([1, 2])
    with save_btn_col:
        if st.button("💾  保存する", type="primary", use_container_width=True):
            if save_file(file_path, edited):
                st.session_state.content = edited
                st.success("✅  保存しました！")
