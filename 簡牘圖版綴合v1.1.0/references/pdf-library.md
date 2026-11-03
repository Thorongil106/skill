# 從簡號到紅外線圖版

此流程由助手操作。使用者只須給簡號、面別（有則提供）和拼接次序。

## 來源與記憶

在工作目錄保存 `.slip-join-plate/library.json`；其旁 `index/` 存放來源頁與OCR。使用者的PDF路徑和定位記錄存於這個本地庫，不寫入可分享的技能包。書目庫是路徑與核對記錄；檔案存取仍遵從當前權限和既有授權。

先讀庫及對話中已知路徑。文件可讀即繼續，不反覆詢問是否允許讀取。首次沒有庫時由當前使用者提供的PDF建立，不假定作者設備上的書籍仍可取得。只在原位置不存在時，在已知來源目錄中查同書異名；比對SHA-256，不把另一掃描本沿用相同PDF頁碼。內容更新後重新登記，舊定位失效；相同內容僅時間戳不同則校驗後可保留定位。

新登記的PDF路徑相對於 `library.json` 所在目錄；頁圖快取路徑相對於其記錄JSON，裁圖來源記錄的圖像路徑相對於 `.source.json`。Windows不同磁碟無法表示相對路徑時保留絕對路徑。舊絕對路徑庫仍可讀。整個任務資料夾連同書籍搬遷可保留相對結構；書籍另存位置時使用 `relink`，它只接受與原登記SHA-256相同的PDF：

```sh
python scripts/pdf_library.py relink --pdf-id xuanquan-6-ir --pdf "books/volume-new-location.pdf"
```

若是不同掃描本，必須重新 `register` 並核頁，不能以改路徑繞過來源核對。舊裁圖記錄中失效的絕對路徑不會被猜測替換；可按已核頁碼與裁框重新提取，或核對圖像SHA後更新裁圖配置。

同一書可有分冊PDF、彩版／紅外分冊或合併本。以目錄、版面實見確認成像類型和頁段；檔名含「下」不等於已確認紅外線。合併本可登記兩個邏輯來源，分別填 `infrared`、`color` 與各自 `platePages`。尚未分類登記為 `mixed`，先查目錄再建立紅外入口。

## 定位策略

1. 預設 `infrared`。查已核對定位與OCR候選；將Ⅰ／Ⅱ、全半角冒號和空格規範化，但保留探方、層位②、S及A/B區別。未指面別時返回所有對應面；不把416B當416A，也不把②改成普通末位數字。
2. 有文字層可先全文定位，命中釋文或尺寸表仍須轉到紅外線圖版核對。純掃描本以印刷簡號作OCR；不依手寫正文猜簡號。簡號標籤常橫轉90度，OCR方向與簡面閱讀方向分開。
3. 大冊不用每次全書OCR。先看目錄、已核頁的首尾簡號與同批次錨點，按實際編排縮小頁段，再查相鄰頁。順序可能有跳號、補頁或已綴號，不能假設每頁固定簡數。OCR未命中時讀其原始文字，容許查候選相似標籤，但必須回原頁核全號。
4. 保存OCR原文、置信度與框，定位未核對只稱候選。完整簡號由多行或分開的前綴標出時，目視合讀；不把兩個相鄰標籤串成一號。正反面分別核對；並列縮印、放大圖及既綴圖選最完整、解析度合適者。
5. 記錄**PDF頁（從1開始）**和**書頁（逐頁核實）**。不使用固定偏移推算全書；上下冊、插頁和不同掃描本可不同。核實後寫回庫，下一次按同號直接重用。

## 提取與裁圖

掃描頁只有一張整頁點陣圖時，先提取嵌入影像，不用低解析預覽截圖。`pdf_library.py page` 自動識別常見單圖掃描頁；仍需目視核對整頁，若有另繪向量線條、標籤、局部覆蓋或版面旋轉造成不一致，改用PDF渲染。其他版式預設用跨平台 `portable_helper.py`：有PyMuPDF則用之，否則用Poppler的 `pdftoppm`；亦可明確指定macOS PDFKit助手。記錄實際渲染器、DPI及座標方向；不同渲染器的輸出不能不核對就沿用舊裁框。

提取影像的座標是**原始嵌入圖的左上像素座標**，可能不同於PDF閱讀器顯示方向。PDF的 `/Rotate` 保存在來源記錄，不自動套到嵌入圖片。OCR旋轉的是臨時副本；正式裁圖在原解析度影像上進行。需要正向工作圖可作90／180／270度整片旋轉，另記其變換；不得將OCR預覽當來源。

先寬鬆矩形裁出整片，包含完整茬口及少量邊白；同時輸出帶紅框的整頁定位圖，再以 `compose.cjs` 的獨立輪廓蒙版摳簡面。裁圖框不可混入鄰簡、印刷釋文或標籤。頁邊已截去的茬口如實保留。

每張裁圖附 `.source.json`：原PDF路徑與SHA-256、冊次、成像類型、PDF頁、書頁、可見標籤、來源頁圖尺寸與SHA-256、裁圖座標、輸出圖SHA-256。拼接參數每片填 `provenance` 指向此檔，來源資訊會一併納入拼接清單。

## 隨附工具

使用現有Python（pypdf、Pillow）、Node（sharp）；工具尋找與可選依賴見 [跨設備指南](portable-setup.md)。以下以技能內腳本的相對路徑示例；實際由助手定位技能目錄，在任務工作目錄執行，不把個人書目庫和裁圖存進技能分享包。

```sh
python scripts/pdf_library.py register --id xuanquan-6-ir --pdf "books/volume.pdf" --title '懸泉漢簡（陸下）' --kind infrared --pages 7-314
python scripts/pdf_library.py search --slip 'Ⅱ90DXT0215S:416A'
python scripts/pdf_library.py page --pdf-id xuanquan-6-ir --page 20
```

`--pages` 必須按實際文件核實；範例頁段不能套到其他掃描本。`--library` 可在子指令前指定另一工作目錄的庫。`search` 顯示已索引覆蓋度，局部無結果要繼續定位。

跨平台預設使用已安裝的Tesseract OCR；`--helper` 可省略。預設 `eng` 用於印刷簡號，圓圈層號等仍須目視核對；若安裝相應語言資料，可設 `SLIP_OCR_LANG`（例如 `eng+chi_tra`）。沒有OCR時改用已有文字層或原頁目視定位，不以缺少OCR判定簡號不存在。

```sh
python scripts/pdf_library.py index --pdf-id xuanquan-6-ir --pages 18-22 --rotations 270
```

macOS也可用本機Vision OCR，無需上傳頁圖；由助手先在任務目錄建立 `.slip-join-plate/tools/`：

```sh
swiftc -module-cache-path .slip-join-plate/tools/swift-cache scripts/plate_ocr.swift -o .slip-join-plate/tools/plate-ocr
python scripts/pdf_library.py index --pdf-id xuanquan-6-ir --pages 18-22 --helper .slip-join-plate/tools/plate-ocr --rotations 270
```

旋轉參數為逆時針角度；先以一頁測定。未檢出可試0、90、180、270，不默認低置信OCR即正確。若Vision在受限執行環境報權限錯誤，用工具既有的審批重試機制；仍無法使用則改讀整頁縮圖和原頁，不將OCR失敗說成無此簡。非macOS可用現有OCR工具，保留同等觀察記錄。

目視核號後裁圖：

```sh
python scripts/pdf_library.py crop --pdf-id xuanquan-6-ir --page 20 --slip 'Ⅱ90DXT0215S:416A' --printed-page 318 --label 'Ⅱ90DXT0215S:416A' --label-verified --box 1150 4370 290 545 --output output/416A.png
```

`--label-verified` 表示助手已查看原頁核過標籤，不能只因OCR命中就填。裁圖命令不描摳邊輪廓，不判斷綴合；接續主流程完成。
