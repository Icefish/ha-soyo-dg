# SOYO DG Inverter — Home Assistant 整合

把 [web.soyo-dg.com](https://web.soyo-dg.com)(並網逆變器遠端管理平台)的即時資料
與設備參數帶進 Home Assistant。

這個平台就是 SOYO / SOYOSOURCE 併網逆變器(2KW、PV:55-90V / BAT:48V / AC:220V 這類)
的雲端後台。整合直接走平台的 REST API,不需要拆機、不需要 MQTT,
所有資料都是從雲端讀回來的。

---

## 功能

| 類型 | 實體 |
|---|---|
| **sensor** | 即時功率、DC 電壓、DC 電流、AC 電壓、AC 頻率、溫度、負載功率、峰值功率、今日／累計／本月／昨日發電量、資料年齡、運行模式、運行狀態、故障提示、提示訊息、型號 |
| **binary_sensor** | 在線、採集器已連接、資料新鮮、故障 |
| **select** | 工作模式(光伏模式／光伏防逆流／電池恆功率／電池防反流) |
| **number** | 延時啟動、電池輸出功率、啟動電壓、欠壓保護值 |
| **button** | 重啟設備 |

累計發電量是 `total_increasing`,可以直接加進 **Energy Dashboard**。
今日 / 本月 / 昨日發電量是 `total`(會隨日、月重置,所以值會下降)。

---

## 安裝

### 方式 A:HACS(推薦)

1. HACS → 三點選單 → **Custom repositories**
2. 加上 `https://github.com/Icefish/ha-soyo-dg`(類別選 **Integration**)
3. 搜尋 **SOYO DG Inverter** → 下載 → 重啟 Home Assistant

### 方式 B:手動

把 `custom_components/soyo_dg/` 整個資料夾複製到 HA 的
`config/custom_components/` 底下,然後重啟 Home Assistant。

---

## 設定

**設定 → 附加元件與服務 → 新增整合 → 搜尋「SOYO DG Inverter」**

### 方式 A:Refresh Token(推薦,不用交出帳號密碼)

1. 在已登入 [web.soyo-dg.com](https://web.soyo-dg.com) 的瀏覽器按 `F12` → **Console**
2. 執行:

   ```js
   copy(localStorage.getItem('nbq_refresh_token'))
   ```

3. 把複製到的內容貼進 Home Assistant 的輸入框

整合會用這顆 token 換取 access token,平台輪替 token 時也會自動更新並存回設定項。
**Home Assistant 不會存你的帳號密碼。**

### 方式 B:帳號 + 密碼

直接輸入你在 web.soyo-dg.com 的帳號與密碼,整合自己登入並續期。

> 兩種方式都會把憑證存在 HA 的 `.storage/core.config_entries` 裡(這是 HA 的一般做法)。

設定完成後可以調整 **輪詢間隔**(預設 30 秒)。

---

## 實體

### sensor

| 名稱 | 單位 | 說明 |
|---|---|---|
| 即時功率 | W | 逆變器目前輸出功率 |
| DC 電壓 | V | 直流側電壓 |
| DC 電流 | A | 直流側電流 |
| AC 電壓 | V | 交流側電壓 |
| AC 頻率 | Hz | 交流頻率 |
| 溫度 | °C | 設備溫度 |
| 負載功率 | W | 採集器用掉的功率 |
| 峰值功率 | W | 峰值輸出功率 |
| 今日發電量 | kWh | 今日累積 |
| 累計發電量 | kWh | 總累積(`total_increasing`) |
| 本月發電量 | kWh | 本月累積 |
| 昨日發電量 | kWh | 從每日歷史記錄取 |
| 資料年齡 | s | 距離設備最後回報幾秒(附屬性 `last_reported` = 最後回報的時間點) |
| 運行模式 | — | 光伏模式／光伏防逆流／電池恆功率／電池防反流 |
| 運行狀態 | — | 發電中／待機中／故障 |
| 故障提示 | — | 平台的 `error_msg` |
| 提示訊息 | — | 平台的 `notice_msg` |
| 型號 | — | 例如 `2.0KW/PV:55-90V(BAT:48V)/AC:220V` |

### binary_sensor

| 名稱 | 說明 |
|---|---|
| 在線 | 平台回報的裝置狀態(`status` 1=在線、2=故障、其他=離線) |
| 採集器已連接 | 採集器與設備的連線狀態 |
| 資料新鮮 | `reported_at` 距今還在 180 秒內 |
| 故障 | 有故障訊息或 `power_status` 異常 |

### select / number / button

| 名稱 | 型態 | 說明 |
|---|---|---|
| 工作模式 | select | 四種模式,對應 `work_mode` 1–4 |
| 延時啟動 | number | 1–180 秒 |
| 電池輸出功率 | number | 0–10000 W,步進 10 |
| 啟動電壓 | number | 依電池標稱電壓動態決定範圍(48V 電池 → 40–65 V) |
| 欠壓保護值 | number | 同上 |
| 重啟設備 | button | 送 `POST /devices/{sn}/reboot` |

---

## 注意事項

- **讀寫參數需要設備本身在線。** 平台的採集器如果連不到設備,
  `GET/PUT /devices/{sn}/params` 會回 `502 / code 50000`(設備目前離線),
  這時 select / number 會變成 unavailable,並在寫入時丟出明確的錯誤訊息。
  讀取遙測則不受影響。
- **參數是整組覆蓋。** `PUT /params` 少帶一個欄位就會被清成 0,
  整合每次寫入都會帶上完整參數集合。
- **啟動電壓必須比欠壓保護值高 2V 以上**,整合在寫入前會先擋掉不合法的值。
- 資料是否為最新請看 **資料新鮮** 這個 binary_sensor;平台有時會回傳最後一次
  已知數值,但設備其實已經離線了一段時間。
- **不會洗版活動列表。** 設備「最後回報時間」放在 **資料年齡** 的附屬性
  `last_reported` 裡,而不是獨立的 TIMESTAMP sensor。TIMESTAMP 屬於非數值型,
  HA 的 logbook 每次輪詢都會寫一筆紀錄,讓活動列表一直跳。從 v2 開始,
  舊的 `sensor.*_last_reported` 會在升級時自動從 entity registry 移除。

---

## 平台 API

整合用到的端點(全部在 `https://web.soyo-dg.com/api/v1`):

| Method | Path | 用途 |
|---|---|---|
| POST | `/auth/login` | 帳號密碼登入 |
| POST | `/auth/refresh` | 用 refresh token 換 access token |
| GET | `/devices?page=1&page_size=200` | 裝置清單 |
| GET | `/devices/{sn}/realtime` | 即時遙測 |
| GET | `/devices/{sn}/stats` | 發電量統計 |
| GET | `/devices/{sn}/stat-history` | 每日／每月發電量 |
| GET | `/devices/{sn}/params` | 讀取設備參數 |
| PUT | `/devices/{sn}/params` | 寫入設備參數 |
| POST | `/devices/{sn}/reboot` | 重啟 |

認證:`Authorization: Bearer <access_token>`
回應封裝:`{"code": 0, "message": "success", "data": {...}}`(`code != 0` 即失敗)

> 平台另外有一套官方的 **Open API**(`https://api.soyo-dg.com/v1`,需要申請
> `soyo_live_xxx` key)。本整合走的是網頁版 API,不需要申請、馬上就能用。

---

## 開發

```bash
# 單元測試(API 客戶端,mock server)
cd /tmp && python3 tools/test_api.py

# 端對端測試(真的把 Home Assistant 開起來載入整合)
python3 -m venv .venv && .venv/bin/pip install homeassistant
cd /tmp && ../.venv/bin/python tools/test_e2e.py
```

`tools/mock_soyo.py` 裡的 mock server 回放的是 2026-10-25 從線上平台抓到的真實回應。

---

## 相關

- 同一個 GitHub 帳號的 [ha-uwant-vacuum](https://github.com/Icefish/ha-uwant-vacuum)
  (UWANT U300 掃地機器人整合)

## 授權

MIT
