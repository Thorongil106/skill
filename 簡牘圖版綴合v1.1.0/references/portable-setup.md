# 跨設備使用與來源綁定

技能包保存判讀流程和通用工具；書籍、書目庫、OCR快取、裁圖及每台設備的工具路徑屬於使用者的任務資料，分開存放。首次使用不要求與作者相同的帳號、目錄、聊天記錄或設備。

## 首次接手

1. **定位當前來源。** 使用本輪圖像附件即可直接綴合；提供PDF則由助手登記並按簡號查圖。只給簡號時先查當前工作目錄的庫與已知附件，沒有原書才請提供PDF或圖像。不能由簡號推定能取得原書，也不掃描整台設備找作者曾用的文件。
2. **定位當前工具。** 如有 `load_workspace_dependencies` 則使用；否則查當前PATH、環境已提供的執行檔或使用者指定路徑，選用實際可用的Python與Node，不寫死他人主目錄。可執行 `python scripts/check_environment.py`，非PATH中的現有Node或sharp可用 `--node`、`--sharp-module` 明確提供。
3. **按任務需要補足能力。** 圖像綴合只需Node＋sharp；從PDF提取圖像才需Python＋pypdf＋Pillow。渲染與OCR為按需能力，不因可選OCR缺失阻塞已有圖像的綴合。缺少必要依賴時先檢查現成工具，確需安裝時清楚說明缺項並依當前使用者授權處理；技能腳本不自行安裝或下載任何內容。

| 工作 | 可用工具 | 缺少時 |
| --- | --- | --- |
| PNG／SVG拼接 | Node 20.9以上、sharp | 查環境依賴或安裝本技能 `package.json` 所列依賴。 |
| 掃描PDF原圖提取 | Python 3.10以上、pypdf、Pillow | 查環境依賴或依 `requirements.txt` 安裝。 |
| 含向量／文字的PDF頁渲染 | PyMuPDF，或Poppler `pdftoppm` | 可用現有外部渲染工具並記錄來源；macOS另有PDFKit助手。 |
| 印刷簡號OCR | Tesseract與語言資料；macOS可選Vision | 用文字層、相鄰頁錨點和目視核號繼續，或另裝OCR。 |

依賴安裝命令由助手在技能目錄或隔離的任務環境執行，依現場平台選對Python命令：

```sh
python -m pip install -r requirements.txt
npm install --omit=dev
```

這些命令需網路下載依賴，不是離線分享包的必要自動步驟。可選PyMuPDF可另裝 `pymupdf`；Poppler、Tesseract及其語言資料由當前設備的系統套件工具或管理者提供。不要把Mac的 `node_modules`、Python虛擬環境或Swift編譯檔打包給Windows使用者。已有依賴可直接重用。

`portable_helper.py` 以參數列表呼叫工具，支援空格與中文路徑。Tesseract、Poppler不在PATH時可分別設 `SLIP_TESSERACT`、`SLIP_PDFTOPPM` 為當前設備的可執行檔路徑；OCR語言以 `SLIP_OCR_LANG` 指定。這些設定只屬於本機，不寫進可分享的技能文件。

## 任務目錄與搬遷

```text
my-join-project/
  books/volume.pdf              使用者自行提供
  .slip-join-plate/library.json  本任務的來源登記
  .slip-join-plate/index/        本任務的頁圖與OCR快取
  sources/upper.png
  sources/upper.source.json
  sources/lower.png
  job.json                      image/provenance使用相對路徑
  join-review.md
  output/
```

這是建議結構，不是強制使用者改動現有書庫。新書目登記、頁圖快取與裁圖來源記錄會盡可能使用相對路徑；拼接配置亦優先相對於配置檔。整個目錄一起移動，原始圖像與來源校驗仍可沿用。書籍不在任務內、跨Windows磁碟或舊庫用絕對路徑時，以 `pdf_library.py relink` 綁定新位置；只有相同SHA-256才保留原定位。

只搬移裁圖與配置即可重新拼接，不需要為渲染PNG／SVG再次讀整本PDF；但回查原頁、重新裁圖仍需要來源PDF。舊來源記錄的絕對 `image` 路徑須核對同圖SHA後遷移；不能刪掉來源校驗來繞過路徑問題。輸出的manifest和parameters可能含本機路徑；它們是運行紀錄，不是公開分發清單。

## 分享邊界與環境限制

- 分享技能資料夾中的指令、references、scripts和依賴清單。不要附 `.slip-join-plate/`、原書、裁圖、任務配置、運行記錄或包含原圖的SVG。
- 分享包不自帶書籍，同學首次須提供自己的PDF或圖片；此後自己的庫可以記住定位。
- 需要支援文件讀寫與Python／Node執行的助手環境。僅能聊天、沒有執行工具的環境，可以參考判讀流程，但不能承諾自動提取或生成完整檔案。
- 工具按macOS、Windows、Linux的通用路徑與子程序方式設計；實際能否運行仍取決於已安裝依賴。本次測試涵蓋macOS上的目錄搬遷、相對來源、中文／空格路徑、Poppler渲染和拼接；未冒稱已在Windows／Linux實機測試，也未將OCR解析測試稱作識別準確率驗證。
