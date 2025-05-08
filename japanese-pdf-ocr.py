#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日本語PDF OCR GUI アプリケーション
Google Cloud Vision APIを使用して日本語PDFファイルからテキストを抽出するGUIプログラム
"""

import os
import io
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from tkinter.font import Font
import configparser
from pathlib import Path
import pdf2image
from google.cloud import vision
from google.cloud import storage
from PIL import Image, ImageTk

class JapanesePdfOcrApp:
    """
    日本語PDF OCR GUIアプリケーションのメインクラス
    """
    def __init__(self, root):
        """
        アプリケーションの初期化
        
        Args:
            root: tkinterのルートウィンドウ
        """
        self.root = root
        self.root.title("日本語PDF OCR")
        self.root.geometry("900x700")
        self.root.minsize(800, 600)
        
        # 設定の読み込み
        self.config = configparser.ConfigParser()
        self.config_file = os.path.expanduser("~/.japanese_pdf_ocr_config.ini")
        self.load_config()
        
        # 変数の初期化
        self.pdf_path = tk.StringVar()
        self.output_path = tk.StringVar(value=self.config.get('paths', 'default_output_path', fallback=''))
        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value="待機中")
        self.use_async = tk.BooleanVar(value=self.config.getboolean('processing', 'use_async', fallback=False))
        self.current_page = 0
        self.total_pages = 0
        self.thumbnail_images = []
        self.page_images = []
        self.extracted_text = ""
        
        # GUIの構築
        self.setup_ui()
        
    def load_config(self):
        """設定ファイルを読み込む"""
        # デフォルト設定
        self.config['paths'] = {
            'default_output_path': os.path.expanduser("~/ocr_output.txt")
        }
        self.config['processing'] = {
            'use_async': 'False',
            'bucket_name': '',
            'output_prefix': 'vision_output'
        }
        self.config['google_cloud'] = {
            'credentials_path': '',
        }
        
        # 設定ファイルがあれば読み込む
        if os.path.exists(self.config_file):
            self.config.read(self.config_file, encoding='utf-8')
    
    def save_config(self):
        """設定ファイルを保存する"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            self.config.write(f)
    
    def setup_ui(self):
        """GUIの各コンポーネントを設定する"""
        # メニューバー
        self.create_menu()
        
        # メインフレーム
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 上部フレーム (ファイル選択など)
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 10))
        
        # PDFファイル選択
        ttk.Label(top_frame, text="PDFファイル:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        ttk.Entry(top_frame, textvariable=self.pdf_path, width=50).grid(row=0, column=1, sticky=tk.EW, padx=5, pady=5)
        ttk.Button(top_frame, text="参照...", command=self.browse_pdf_file).grid(row=0, column=2, padx=5, pady=5)
        
        # 非同期処理チェックボックス
        async_check = ttk.Checkbutton(top_frame, text="非同期処理を使用", variable=self.use_async)
        async_check.grid(row=0, column=3, padx=5, pady=5)
        
        # 開始ボタン
        ttk.Button(top_frame, text="OCR開始", command=self.start_ocr).grid(row=0, column=4, padx=5, pady=5)
        
        # コンテンツフレーム (分割ペイン)
        content_frame = ttk.Frame(main_frame)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 左右のペインを作成
        paned_window = ttk.PanedWindow(content_frame, orient=tk.HORIZONTAL)
        paned_window.pack(fill=tk.BOTH, expand=True)
        
        # 左側ペイン (プレビュー)
        left_frame = ttk.Frame(paned_window, width=400)
        paned_window.add(left_frame, weight=1)
        
        # ページプレビュー
        preview_frame = ttk.LabelFrame(left_frame, text="プレビュー", padding="5")
        preview_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # プレビューキャンバス
        self.preview_canvas = tk.Canvas(preview_frame, bg="white")
        self.preview_canvas.pack(fill=tk.BOTH, expand=True)
        
        # ページナビゲーション
        nav_frame = ttk.Frame(left_frame)
        nav_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Button(nav_frame, text="前へ", command=self.prev_page).pack(side=tk.LEFT, padx=5)
        ttk.Label(nav_frame, textvariable=self.status_var).pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        ttk.Button(nav_frame, text="次へ", command=self.next_page).pack(side=tk.RIGHT, padx=5)
        
        # 右側ペイン (抽出テキスト)
        right_frame = ttk.Frame(paned_window, width=400)
        paned_window.add(right_frame, weight=1)
        
        # テキスト表示エリア
        text_frame = ttk.LabelFrame(right_frame, text="抽出テキスト", padding="5")
        text_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # 日本語フォントの設定
        jp_font = Font(family="MS Gothic", size=10)
        
        # スクロール可能なテキストエリア
        self.text_area = scrolledtext.ScrolledText(text_frame, wrap=tk.WORD, font=jp_font)
        self.text_area.pack(fill=tk.BOTH, expand=True)
        
        # テキスト操作ボタン
        text_btn_frame = ttk.Frame(right_frame)
        text_btn_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Button(text_btn_frame, text="コピー", command=self.copy_text).pack(side=tk.LEFT, padx=5)
        ttk.Button(text_btn_frame, text="保存", command=self.save_text).pack(side=tk.LEFT, padx=5)
        ttk.Button(text_btn_frame, text="クリア", command=self.clear_text).pack(side=tk.LEFT, padx=5)
        
        # 下部フレーム (プログレスバー)
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.X, pady=(10, 0))
        
        # プログレスバー
        self.progress_bar = ttk.Progressbar(
            bottom_frame, 
            variable=self.progress_var, 
            mode='determinate',
            length=100
        )
        self.progress_bar.pack(fill=tk.X)
        
        # ウィンドウ列の構成
        top_frame.columnconfigure(1, weight=1)
    
    def create_menu(self):
        """メニューバーを作成する"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # ファイルメニュー
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="ファイル", menu=file_menu)
        file_menu.add_command(label="PDFを開く", command=self.browse_pdf_file)
        file_menu.add_command(label="テキストを保存", command=self.save_text)
        file_menu.add_separator()
        file_menu.add_command(label="終了", command=self.root.quit)
        
        # 設定メニュー
        settings_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="設定", menu=settings_menu)
        settings_menu.add_command(label="出力設定", command=self.open_output_settings)
        settings_menu.add_command(label="Google Cloud設定", command=self.open_gcloud_settings)
        
        # ヘルプメニュー
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="ヘルプ", menu=help_menu)
        help_menu.add_command(label="使い方", command=self.show_help)
        help_menu.add_command(label="情報", command=self.show_about)
    
    def browse_pdf_file(self):
        """PDFファイルを選択するダイアログを開く"""
        file_path = filedialog.askopenfilename(
            title="PDFファイルを選択",
            filetypes=[("PDFファイル", "*.pdf"), ("すべてのファイル", "*.*")]
        )
        
        if file_path:
            self.pdf_path.set(file_path)
            self.load_pdf_preview(file_path)
    
    def load_pdf_preview(self, pdf_path):
        """PDFファイルをプレビュー用に読み込む"""
        try:
            # PDFをイメージに変換
            images = pdf2image.convert_from_path(pdf_path, dpi=100)
            
            self.page_images = images
            self.thumbnail_images = []
            self.total_pages = len(images)
            self.current_page = 0
            
            # サムネイル作成
            for img in images:
                # プレビューサイズに調整
                img.thumbnail((400, 600), Image.LANCZOS)
                self.thumbnail_images.append(ImageTk.PhotoImage(img))
            
            # 最初のページを表示
            self.update_preview()
            self.status_var.set(f"ページ 1 / {self.total_pages}")
            
        except Exception as e:
            messagebox.showerror("エラー", f"PDFの読み込み中にエラーが発生しました: {str(e)}")
    
    def update_preview(self):
        """プレビューウィンドウを更新する"""
        if not self.thumbnail_images:
            return
        
        # キャンバスをクリア
        self.preview_canvas.delete("all")
        
        # 現在のページを表示
        if 0 <= self.current_page < len(self.thumbnail_images):
            img = self.thumbnail_images[self.current_page]
            
            # キャンバスの中央に配置
            canvas_width = self.preview_canvas.winfo_width()
            canvas_height = self.preview_canvas.winfo_height()
            
            x = max(0, (canvas_width - img.width()) // 2)
            y = max(0, (canvas_height - img.height()) // 2)
            
            self.preview_canvas.create_image(x, y, anchor=tk.NW, image=img)
            
            # ページ番号表示を更新
            self.status_var.set(f"ページ {self.current_page + 1} / {self.total_pages}")
    
    def prev_page(self):
        """前のページに移動"""
        if self.current_page > 0:
            self.current_page -= 1
            self.update_preview()
    
    def next_page(self):
        """次のページに移動"""
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.update_preview()
    
    def open_output_settings(self):
        """出力設定ダイアログを開く"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("出力設定")
        settings_window.geometry("500x300")
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        # 設定フレーム
        frame = ttk.Frame(settings_window, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        
        # 出力パス
        ttk.Label(frame, text="デフォルト出力パス:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        output_entry = ttk.Entry(frame, width=50)
        output_entry.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=5)
        output_entry.insert(0, self.config.get('paths', 'default_output_path', fallback=''))
        ttk.Button(frame, text="参照...", 
                   command=lambda: self.browse_output_file(output_entry)
                  ).grid(row=0, column=2, padx=5, pady=5)
        
        # 非同期処理設定
        ttk.Label(frame, text="非同期処理:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        use_async_var = tk.BooleanVar(value=self.config.getboolean('processing', 'use_async', fallback=False))
        ttk.Checkbutton(frame, text="非同期処理を使用", variable=use_async_var).grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        
        # バケット名（非同期処理用）
        ttk.Label(frame, text="GCSバケット名:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
        bucket_entry = ttk.Entry(frame, width=50)
        bucket_entry.grid(row=2, column=1, sticky=tk.EW, padx=5, pady=5)
        bucket_entry.insert(0, self.config.get('processing', 'bucket_name', fallback=''))
        
        # 出力プレフィックス
        ttk.Label(frame, text="出力プレフィックス:").grid(row=3, column=0, sticky=tk.W, padx=5, pady=5)
        prefix_entry = ttk.Entry(frame, width=50)
        prefix_entry.grid(row=3, column=1, sticky=tk.EW, padx=5, pady=5)
        prefix_entry.insert(0, self.config.get('processing', 'output_prefix', fallback='vision_output'))
        
        # ボタン
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=4, column=0, columnspan=3, pady=10)
        
        ttk.Button(button_frame, text="キャンセル", 
                  command=settings_window.destroy
                 ).pack(side=tk.RIGHT, padx=5)
        
        ttk.Button(button_frame, text="保存", 
                  command=lambda: self.save_output_settings(
                      settings_window, output_entry.get(), use_async_var.get(),
                      bucket_entry.get(), prefix_entry.get()
                  )
                 ).pack(side=tk.RIGHT, padx=5)
        
        # ウィンドウ列の構成
        frame.columnconfigure(1, weight=1)
    
    def browse_output_file(self, entry_widget):
        """出力ファイルを選択するダイアログを開く"""
        file_path = filedialog.asksaveasfilename(
            title="出力ファイルを選択",
            filetypes=[("テキストファイル", "*.txt"), ("すべてのファイル", "*.*")],
            defaultextension=".txt"
        )
        
        if file_path:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, file_path)
    
    def save_output_settings(self, window, output_path, use_async, bucket_name, output_prefix):
        """出力設定を保存する"""
        self.config.set('paths', 'default_output_path', output_path)
        self.config.set('processing', 'use_async', str(use_async))
        self.config.set('processing', 'bucket_name', bucket_name)
        self.config.set('processing', 'output_prefix', output_prefix)
        
        self.save_config()
        self.output_path.set(output_path)
        self.use_async.set(use_async)
        
        window.destroy()
        messagebox.showinfo("設定", "設定が保存されました。")
    
    def open_gcloud_settings(self):
        """Google Cloud設定ダイアログを開く"""
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Google Cloud設定")
        settings_window.geometry("500x200")
        settings_window.transient(self.root)
        settings_window.grab_set()
        
        # 設定フレーム
        frame = ttk.Frame(settings_window, padding="10")
        frame.pack(fill=tk.BOTH, expand=True)
        
        # 認証情報ファイルパス
        ttk.Label(frame, text="認証情報JSONファイル:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        cred_entry = ttk.Entry(frame, width=50)
        cred_entry.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=5)
        cred_entry.insert(0, self.config.get('google_cloud', 'credentials_path', fallback=''))
        ttk.Button(frame, text="参照...", 
                   command=lambda: self.browse_credentials_file(cred_entry)
                  ).grid(row=0, column=2, padx=5, pady=5)
        
        # 説明ラベル
        desc_text = """
        Google Cloud Vision APIを使用するには、サービスアカウントキーが必要です。
        
        JSONキーファイルをダウンロードするか、環境変数GOOGLE_APPLICATION_CREDENTIALSを設定してください。
        """
        ttk.Label(frame, text=desc_text, wraplength=400, justify=tk.LEFT).grid(
            row=1, column=0, columnspan=3, sticky=tk.W, padx=5, pady=10
        )
        
        # ボタン
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=2, column=0, columnspan=3, pady=10)
        
        ttk.Button(button_frame, text="キャンセル", 
                  command=settings_window.destroy
                 ).pack(side=tk.RIGHT, padx=5)
        
        ttk.Button(button_frame, text="保存", 
                  command=lambda: self.save_gcloud_settings(
                      settings_window, cred_entry.get()
                  )
                 ).pack(side=tk.RIGHT, padx=5)
        
        # ウィンドウ列の構成
        frame.columnconfigure(1, weight=1)
    
    def browse_credentials_file(self, entry_widget):
        """認証情報ファイルを選択するダイアログを開く"""
        file_path = filedialog.askopenfilename(
            title="認証情報JSONファイルを選択",
            filetypes=[("JSONファイル", "*.json"), ("すべてのファイル", "*.*")]
        )
        
        if file_path:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, file_path)
    
    def save_gcloud_settings(self, window, credentials_path):
        """Google Cloud設定を保存する"""
        self.config.set('google_cloud', 'credentials_path', credentials_path)
        
        # 環境変数として設定
        if credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
        
        self.save_config()
        window.destroy()
        messagebox.showinfo("設定", "設定が保存されました。")
    
    def start_ocr(self):
        """OCR処理を開始する"""
        pdf_path = self.pdf_path.get()
        if not pdf_path:
            messagebox.showerror("エラー", "PDFファイルを選択してください。")
            return
        
        if not os.path.exists(pdf_path):
            messagebox.showerror("エラー", "選択されたPDFファイルが見つかりません。")
            return
        
        # 非同期処理の場合、バケット名が必要
        if self.use_async.get():
            bucket_name = self.config.get('processing', 'bucket_name', fallback='')
            if not bucket_name:
                messagebox.showerror("エラー", "非同期処理を使用するにはGCSバケット名を設定してください。")
                return
        
        # 出力先の設定
        output_path = self.output_path.get()
        if not output_path:
            # 設定から取得
            output_path = self.config.get('paths', 'default_output_path', fallback='')
            self.output_path.set(output_path)
        
        # プログレスバーと状態をリセット
        self.progress_var.set(0)
        self.status_var.set("処理中...")
        
        # テキストエリアをクリア
        self.clear_text()
        
        # 別スレッドでOCR処理を実行
        threading.Thread(target=self.run_ocr_process, daemon=True).start()
    
    def run_ocr_process(self):
        """OCR処理を実行する（別スレッドで実行）"""
        try:
            pdf_path = self.pdf_path.get()
            output_path = self.output_path.get()
            
            # Google Cloud認証情報の設定
            credentials_path = self.config.get('google_cloud', 'credentials_path', fallback='')
            if credentials_path:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
            
            # 進捗状況の更新
            self.update_status("Google Cloud Visionに接続中...")
            
            if self.use_async.get():
                # 非同期処理
                bucket_name = self.config.get('processing', 'bucket_name', fallback='')
                output_prefix = self.config.get('processing', 'output_prefix', fallback='vision_output')
                
                self.update_status("PDFをGoogle Cloud Storageにアップロード中...")
                
                # PDFをGCSにアップロード
                storage_client = storage.Client()
                bucket = storage_client.bucket(bucket_name)
                
                pdf_filename = os.path.basename(pdf_path)
                blob = bucket.blob(f"input/{pdf_filename}")
                blob.upload_from_filename(pdf_path)
                
                self.update_status("アップロード完了。OCR処理中...")
                self.progress_var.set(20)
                
                # 入力と出力のURIを設定
                gcs_pdf_uri = f"gs://{bucket_name}/input/{pdf_filename}"
                output_uri = f"gs://{bucket_name}/{output_prefix}/"
                
                # 非同期OCR処理
                client = vision.ImageAnnotatorClient()
                
                # 入力設定
                gcs_source = vision.GcsSource(uri=gcs_pdf_uri)
                input_config = vision.InputConfig(
                    gcs_source=gcs_source,
                    mime_type="application/pdf"
                )
                
                # 出力設定
                gcs_destination = vision.GcsDestination(uri=output_uri)
                output_config = vision.OutputConfig(
                    gcs_destination=gcs_destination,
                    batch_size=1
                )
                
                # 日本語OCRの設定
                features = [
                    vision.Feature(
                        type_=vision.Feature.Type.DOCUMENT_TEXT_DETECTION
                    )
                ]
                
                # リクエスト作成
                request = vision.AsyncAnnotateFileRequest(
                    input_config=input_config,
                    features=features,
                    output_config=output_config
                )
                
                # 日本語のヒントを追加
                image_context = vision.ImageContext(
                    language_hints=["ja"]
                )
                request.image_context = image_context
                
                # リクエスト送信
                operation = client.async_batch_annotate_files(requests=[request])
                
                self.update_status("処理中... (これには数分かかることがあります)")
                self.progress_var.set(40)
                
                # 完了を待機
                response = operation.result(timeout=300)
                
                self.update_status("処理完了。結果を取得中...")
                self.progress_var.set(70)
                
                # 結果を取得
                output_files = list(bucket.list_blobs(prefix=output_prefix))
                
                full_text = ""
                
                for blob in output_files:
                    if blob.name.endswith(".json"):
                        # JSONコンテンツをダウンロード
                        json_content = blob.download_as_text()
                        
                        # JSONを解析
                        response_dict = json.loads(json_content)
                        
                        # テキストを抽出
                        for i, response in enumerate(response_dict.get("responses", [])):
                            if "fullTextAnnotation" in response:
                                text = response["fullTextAnnotation"].get("text", "")
                                full_text += f"--- ページ {i+1} ---\n{text}\n\n"
                
                self.extracted_text = full_text
                
            else:
                # 同期処理
                client = vision.ImageAnnotatorClient()
                
                # PDFを画像に変換
                self.update_status("PDFを画像に変換中...")
                
                # ページ数を取得
                images = pdf2image.convert_from_path(pdf_path, dpi=300)
                self.total_pages = len(images)
                
                full_text = ""
                
                # 各ページを処理
                for i, image in enumerate(images):
                    page_num = i + 1
                    self.update_status(f"ページ {page_num}/{self.total_pages} を処理中...")
                    
                    # プログレスバーを更新
                    progress = (i / self.total_pages) * 100
                    self.progress_var.set(progress)
                    
                    # 画像をバイトに変換
                    img_byte_arr = io.BytesIO()
                    image.save(img_byte_arr, format='PNG')
                    image_bytes = img_byte_arr.getvalue()
                    
                    # Cloud Visionリクエストを作成
                    image = vision.Image(content=image_bytes)
                    
                    # 日本語のヒントを設定
                    image_context = vision.ImageContext(
                        language_hints=["ja"]
                    )
                    
                    # テキスト検出を実行
                    response = client.document_text_detection(
                        image=image,
                        image_context=image_context
                    )
                    
                    # 結果を取得
                    page_text = response.full_text_annotation.text
                    
                    # 全テキストに追加
                    full_text += f"--- ページ {page_num} ---\n{page_text}\n\n"
                
                self.extracted_text = full_text
            
            # 進捗状況の更新
            self.progress_var.set(90)
            self.update_status("テキストを保存中...")
            
            # 結果をファイルに保存
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(self.extracted_text)
            
            # GUIを更新
            self.update_text_area()
            
            # 処理完了
            self.progress_var.set(100)
            self.update_status(f"完了! テキストを {output_path} に保存しました。")
            
        except Exception as e:
            # エラーが発生した場合
            self.update_status(f"エラーが発生しました: {str(e)}")
            messagebox.showerror("エラー", f"OCR処理中にエラーが発生しました: {str(e)}")
    
    def update_status(self, message):
        """ステータスメッセージを更新する（スレッドセーフ）"""
        self.root.after(0, lambda: self.status_var.set(message))
    
    def update_text_area(self):
        """テキストエリアを更新する（スレッドセーフ）"""
        self.root.after(0, lambda: self.set_text_area(self.extracted_text))
    
    def set_text_area(self, text):
        """テキストエリアにテキストを設定する"""
        self.text_area.delete(1.0, tk.END)
        self.text_area.insert(tk.END, text)
    
    def copy_text(self):
        """抽出したテキストをクリップボードにコピーする"""
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text_area.get(1.0, tk.END))
        messagebox.showinfo("コピー", "テキストがクリップボードにコピーされました。")
    
    def save_text(self):
        """抽出したテキストを指定したファイルに保存する"""
        if not self.text_area.get(1.0, tk.END).strip():
            messagebox.showwarning("警告", "保存するテキストがありません。")
            return
        
        file_path = filedialog.asksaveasfilename(
            title="テキストを保存",
            filetypes=[("テキストファイル", "*.txt"), ("すべてのファイル", "*.*")],
            defaultextension=".txt",
            initialfile=os.path.basename(self.output_path.get())
        )
        
        if file_path:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(self.text_area.get(1.0, tk.END))
            messagebox.showinfo("保存", f"テキストが {file_path} に保存されました。")
    
    def clear_text(self):
        """テキストエリアをクリアする"""
        self.text_area.delete(1.0, tk.END)
    
    def show_help(self):
        """ヘルプダイアログを表示する"""
        help_text = """
日本語PDF OCR - 使い方

1. PDFファイルを選択する:
   「ファイル」メニューから「PDFを開く」をクリックするか、「参照...」ボタンを使用して
   OCRしたい日本語PDFファイルを選択します。

2. 処理方法を選択する:
   小さいPDFファイルでは「非同期処理を使用」のチェックを外した状態で処理できます。
   大きなファイル（10ページ以上）では非同期処理をお勧めします。非同期処理を使用する
   場合は、設定メニューからGoogle Cloud Storageのバケット名を設定してください。

3. OCRを開始する:
   「OCR開始」ボタンをクリックします。処理状況がプログレスバーとステータスメッセージに
   表示されます。

4. 結果の確認と保存:
   OCR処理が完了すると、抽出されたテキストが右側のパネルに表示されます。
   「コピー」ボタンでテキストをクリップボードにコピーするか、「保存」ボタンで
   別のファイルに保存できます。

5. 設定:
   「設定」メニューから出力先やGoogle Cloudの設定を変更できます。

注意: 
このアプリケーションを使用するには、Google Cloud Visionの認証情報が必要です。
「設定」メニューの「Google Cloud設定」から認証情報ファイルを指定してください。
        """
        
        help_window = tk.Toplevel(self.root)
        help_window.title("使い方")
        help_window.geometry("600x500")
        help_window.transient(self.root)
        
        text_area = scrolledtext.ScrolledText(help_window, wrap=tk.WORD)
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text_area.insert(tk.END, help_text)
        text_area.config(state=tk.DISABLED)
    
    def show_about(self):
        """情報ダイアログを表示する"""
        about_text = """
日本語PDF OCR

バージョン: 1.0

このアプリケーションはGoogle Cloud Vision APIを使用して
日本語のPDFファイルからテキストを抽出します。

© 2025 日本語PDF OCR チーム
        """
        
        messagebox.showinfo("情報", about_text)


def main():
    """アプリケーションのメインエントリーポイント"""
    root = tk.Tk()
    app = JapanesePdfOcrApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()