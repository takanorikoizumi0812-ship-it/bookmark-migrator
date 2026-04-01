import os
import json
import uuid
import time
import plistlib
import shutil
import tkinter as tk
from tkinter import messagebox

# 環境変数でTkinterの警告を非表示にする
os.environ['TK_SILENCE_DEPRECATION'] = '1'

# ブラウザごとのブックマークファイルのパス
PATHS = {
    "Safari": os.path.expanduser('~/Library/Safari/Bookmarks.plist'),
    "Chrome": os.path.expanduser('~/Library/Application Support/Google/Chrome/Default/Bookmarks'),
    "Vivaldi": os.path.expanduser('~/Library/Application Support/Vivaldi/Default/Bookmarks'),
    "Brave": os.path.expanduser('~/Library/Application Support/BraveSoftware/Brave-Browser/Default/Bookmarks')
}

# --- データ処理のロジック ---
def parse_safari_node(node):
    parsed_nodes = []
    if 'Children' in node:
        for child in node['Children']:
            b_type = child.get('WebBookmarkType')
            if b_type == 'WebBookmarkTypeList':
                title = child.get('Title', '無名フォルダ')
                parsed_nodes.append({
                    "type": "folder",
                    "name": title,
                    "children": parse_safari_node(child)
                })
            elif b_type == 'WebBookmarkTypeLeaf':
                uri_dict = child.get('URIDictionary', {})
                url = child.get('URLString')
                if url:
                    parsed_nodes.append({
                        "type": "url",
                        "name": uri_dict.get('title', '無題'),
                        "url": url
                    })
    return parsed_nodes

def parse_chromium_node(nodes):
    parsed_nodes = []
    for node in nodes:
        if node.get("type") == "folder":
            parsed_nodes.append({
                "type": "folder",
                "name": node.get("name", "無名フォルダ"),
                "children": parse_chromium_node(node.get("children", []))
            })
        elif node.get("type") == "url":
            parsed_nodes.append({
                "type": "url",
                "name": node.get("name", "無題"),
                "url": node.get("url", "")
            })
    return parsed_nodes

def convert_to_chromium_format(extracted_nodes):
    chromium_children = []
    for node in extracted_nodes:
        chromium_node = {
            "id": str(uuid.uuid4()),
            "name": node["name"],
            "type": node["type"],
            "date_added": str(int(time.time() * 1000000))
        }
        if node["type"] == "folder":
            chromium_node["children"] = convert_to_chromium_format(node.get("children", []))
            chromium_node["date_modified"] = chromium_node["date_added"]
        elif node["type"] == "url":
            chromium_node["url"] = node["url"]
        chromium_children.append(chromium_node)
    return chromium_children

def inject_shortcuts(dest_path, extracted_nodes):
    """移行先のPreferencesファイルを書き換え、トップページにショートカットを追加する"""
    def get_all_urls(nodes):
        urls = []
        for n in nodes:
            if n["type"] == "url":
                urls.append(n)
            elif n["type"] == "folder":
                urls.extend(get_all_urls(n.get("children", [])))
        return urls
    
    all_urls = get_all_urls(extracted_nodes)
    top_urls = all_urls[:10] # タイルとして表示できる最初の10件を抽出
    
    # BookmarksのパスからPreferencesのパスを動的に生成
    prefs_path = os.path.join(os.path.dirname(dest_path), 'Preferences')
    if not os.path.exists(prefs_path):
        return
        
    shutil.copyfile(prefs_path, prefs_path + '.bak_prefs')
    
    with open(prefs_path, 'r', encoding='utf-8') as f:
        prefs = json.load(f)
        
    custom_links_list = []
    for item in top_urls:
        custom_links_list.append({
            "isMostVisited": False,
            "title": item["name"],
            "url": item["url"]
        })
        
    prefs["custom_links"] = {
        "initialized": True,
        "list": custom_links_list
    }
    
    with open(prefs_path, 'w', encoding='utf-8') as f:
        json.dump(prefs, f, indent=3, ensure_ascii=False)


# --- UI画面の構築 ---
root = tk.Tk()
root.title("Bookmark Migrator")
root.geometry("380x300") # チェックボックスが入るように少し縦幅を拡大

source_var = tk.StringVar(root)
source_var.set("Safari")
dest_var = tk.StringVar(root)
dest_var.set("Brave")
shortcut_var = tk.BooleanVar(root) # チェックボックスの状態を保存する変数
shortcut_var.set(False)            # デフォルトはチェックなし

def execute_migration():
    source = source_var.get()
    dest = dest_var.get()

    if source == dest:
        messagebox.showwarning("エラー", "同じブラウザが選択されています。")
        return
    if dest == "Safari":
        messagebox.showerror("エラー", "Safariへの書き込みはサポートされていません。")
        return
    if not os.path.exists(PATHS[source]):
        messagebox.showerror("エラー", f"{source}のブックマークが見つかりません。")
        return

    try:
        extracted_data = []
        if source == "Safari":
            with open(PATHS[source], 'rb') as f:
                plist_data = plistlib.load(f)
            extracted_data = parse_safari_node(plist_data)
        else:
            with open(PATHS[source], 'r', encoding='utf-8') as f:
                chromium_data = json.load(f)
            roots = chromium_data.get("roots", {})
            all_nodes = (roots.get("bookmark_bar", {}).get("children", []) +
                         roots.get("other", {}).get("children", []) +
                         roots.get("synced", {}).get("children", []))
            extracted_data = parse_chromium_node(all_nodes)

        chromium_formatted = convert_to_chromium_format(extracted_data)

        chromium_bookmarks = {
            "checksum": "",
            "roots": {
                "bookmark_bar": {
                    "children": chromium_formatted,
                    "id": "1",
                    "name": "Bookmarks bar",
                    "type": "folder"
                },
                "other": { "children": [], "id": "2", "name": "Other bookmarks", "type": "folder" },
                "synced": { "children": [], "id": "3", "name": "Mobile bookmarks", "type": "folder" }
            },
            "version": 1
        }

        dest_path = PATHS[dest]
        if os.path.exists(dest_path):
            os.replace(dest_path, dest_path + '.bak')
        
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, 'w', encoding='utf-8') as f:
            json.dump(chromium_bookmarks, f, indent=3, ensure_ascii=False)
            
        # --- チェックボックスがONならショートカットも追加 ---
        if shortcut_var.get():
            inject_shortcuts(dest_path, extracted_data)
            shortcut_msg = "\n(トップページのショートカットも追加しました)"
        else:
            shortcut_msg = ""
            
        messagebox.showinfo("成功", f"{source} から {dest} への移行が完了しました！{shortcut_msg}\n{dest}を完全に終了してから再起動して確認してください。")

    except Exception as e:
        messagebox.showerror("致命的なエラー", f"処理中にエラーが発生しました:\n{str(e)}")


tk.Label(root, text="移行元 (A) を選択:").pack(pady=5)
source_menu = tk.OptionMenu(root, source_var, "Safari", "Chrome", "Vivaldi", "Brave")
source_menu.pack(pady=5)

tk.Label(root, text="移行先 (B) を選択:").pack(pady=5)
dest_menu = tk.OptionMenu(root, dest_var, "Chrome", "Vivaldi", "Brave")
dest_menu.pack(pady=5)

# ショートカット追加のチェックボックス
tk.Checkbutton(root, text="トップページ（お気に入り）にも追加する", variable=shortcut_var).pack(pady=10)

btn = tk.Button(root, text="移行開始！", command=execute_migration, font=("Arial", 14))
btn.pack(pady=10)

root.mainloop()