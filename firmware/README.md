# Prism TV 固件（方案二）— ESP-IDF v5.5+

ESP32-PICO-D4 + ST7789 240×240 + MPU6050 + BH1750 的棱镜小电视固件，
使用官方 **ESP-IDF** 工程形式（CMake + 组件管理器）。

> 本工程按 `../DESIGN.md` 方案二「软件」章节实现：
> LVGL 多页面 UI、NTP 时间 + 今日天气 + 自绘天气图标、内置分帧动画、
> FreeRTOS 多任务、AP 网页配网 + mDNS、HTTP 图片上传、OTA。

> ⚠️ **当前默认是「调试模式」**（`Prism TV → 调试/Debug`）：
> - `display.c` 里棱镜光路（镜像/旋转）校正被**注释**，用面板默认朝向；
> - 翻页改用**按键**（默认 **D13 = 下一页**、**D15 = 上一页**，长按 D13 切换 LCD 方向），
>   不依赖触摸条与 MPU6050，也**不用 BOOT(GPIO0)**；
> - 关闭倒置自动旋转 / 自动亮度 / 自动熄屏；
> - **NTP 时间与今日天气默认仍然工作**（需要联网）。
>
> 只想点屏、不要联网：把 `调试 / Debug → 调试模式：纯点屏，不启动 WiFi/网络` 打开。
> 关闭「调试模式」即恢复方案二完整功能。详见「10. 调试模式」。

> ✅ **本板实测配置**（已烧录验证）：
> | 项 | 值 |
> |---|---|
> | LCD Y 偏移 | **0** |
> | 实际显示区 | **230×230 居中**（面板 240×240，四周 5px 黑边） |
> | LCD 方向 | **MIRROR_Y（棱镜为上下镜像）** |
> | LCD SPI | **20 MHz** |
> | 按键 | **D13 下一页 / D15 上一页**，长按 D13 切换方向 |
> | 天气 | **Open-Meteo + 公网 IP 自动定位**（本机定位到北京，失败回退北京坐标） |

---

## 1. 目录结构

```
firmware/
├── CMakeLists.txt              # 工程入口
├── sdkconfig.defaults          # 默认配置（LVGL/Flash/RTOS/Touch 等）
├── partitions.csv              # 双 App 分区，支持 OTA
├── tools/
│   ├── make_assets.py          # 生成内置资源（动画 + 天气图标）
│   └── frames/*.jpg            # 分帧动画素材（128x64 x 20 帧）
└── main/
    ├── CMakeLists.txt
    ├── idf_component.yml       # 依赖 lvgl / esp_lvgl_port / mdns
    ├── Kconfig.projbuild       # 可配置项（SPI、天气、调试、按键…）
    ├── assets_gen.h            # 自动生成：资源尺寸/数量宏
    ├── anim_frames.bin         # 自动生成：分帧动画（ALPHA_2BIT 240x120）
    ├── weather_icons.bin       # 自动生成：天气图标（ALPHA_4BIT 48x48 x 8）
    ├── board_config.h          # 引脚 / 地址 / 阈值
    ├── display.[ch]            # ST7789 经 esp_lcd + esp_lvgl_port
    ├── sensors.[ch]            # MPU6050 + BH1750（新版 i2c_master）
    ├── input.[ch]              # 输入：触摸条 或 调试按键（D13/D15）
    ├── ui.[ch]                 # LVGL 界面（时钟/动画/系统/图片）
    ├── weather_icons.[ch]      # 天气图标描述符
    ├── wifi_prov.[ch]          # NVS 凭据 + AP 网页配网
    ├── web_server.[ch]         # 内置 HTTP：状态页 / 图片上传 / OTA
    ├── net_task.[ch]           # mDNS + SNTP 对时 + 天气 + 状态
    └── main.c                  # 启动流程 + 传感器/交互/电源任务
```

---

## 2. 环境准备

ESP-IDF 已克隆并安装在 `/home/ming/source/esp-idf`（v5.5.6），工具链在 `~/.espressif`。

```bash
# 加载 IDF 环境（每个新终端都要执行一次）
. /home/ming/source/esp-idf/export.sh
```

从零安装：

```bash
git clone -b v5.5.6 --depth 1 --recurse-submodules --shallow-submodules \
    https://github.com/espressif/esp-idf.git
cd esp-idf && ./install.sh esp32 && . ./export.sh
```

然后进入工程配置：

```bash
cd firmware
idf.py set-target esp32      # 首次会自动下载 lvgl / esp_lvgl_port / mdns
idf.py menuconfig
```

### menuconfig 要点

```
Prism TV (棱镜小电视)
  ├── ST7789 面板 Y 方向偏移 (gap)      # 默认 80，画面偏移就调 0/80
  ├── LCD SPI 时钟频率 (Hz)             # 默认 40MHz，花屏就降到 26MHz
  ├── 自动亮度下限/上限 (%)             # 默认 5 / 100
  ├── 心知天气 API Key / 城市 / 刷新间隔 / 时区 / NTP
  ├── mDNS 主机名                       # 默认 prismtv
  └── 调试 / Debug
        ├── [*] 调试模式：按键翻页、关闭光路校正与传感器手势
        ├── [ ] 调试模式：纯点屏，不启动 WiFi/网络
        ├── 调试按键 GPIO-下一页（默认 13 = D13）
        ├── 调试按键 GPIO-上一页（默认 15 = D15，-1 关闭）
        └── 调试模式固定背光 (%)       # 默认 80
```

> LVGL 选项在 `Component config → LVGL`，本工程已在 `sdkconfig.defaults` 打开
> 16bit 色深、**SPI 字节交换（`LV_COLOR_16_SWAP`）**、Montserrat 14/16/20/28/48 字体。

---

## 3. 编译 / 烧录

```bash
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

> 如果卡在 `Connecting...`，按住 BOOT 键再上电（板上有 SW2）；退出监视用 `Ctrl + ]`。

### 常用调试

```bash
idf.py -p /dev/ttyUSB0 monitor     # 串口监视
idf.py size                        # 固件体积
idf.py erase-flash                 # 清空（含 NVS 凭据）
python3 tools/make_assets.py       # 重新生成动画/图标资源
```

---

## 4. 首次联网（配网流程）

1. 上电后若 NVS 里没有凭据（或连接失败），自动进入 **AP 配网模式**。
2. 手机连上 WiFi：`PrismTV-Setup`（开放网络）。
3. 浏览器打开 `http://192.168.4.1`，填写家里 WiFi 的 SSID / 密码，点“保存并重启”。
4. 重启后自动连接，屏幕状态栏显示 IP，mDNS 生效：`http://prismtv.local/`。
5. 重新配网：擦除 NVS（`idf.py erase-flash`），或在设备网页点“清除 WiFi 并重启”。

---

## 5. 运行界面与交互

### 5.1 五个页面

| 页面 | 内容 |
|---|---|
| 0 **时钟** | 大号时间 + 秒 + 日期 + 天气图标 / 温度区间 / 湿度 |
| 1 **HOME** | **太空人 + 双色时间 + 日期/星期 + 天气 + 温度/湿度进度条**（同屏） |
| 2 **动画** | 全屏太空人动画（20 帧循环，光晕缓慢变色） |
| 3 **系统** | MPU6050 温度、三轴加速度、环境光 lux、IP / RSSI |
| 4 **图片** | 通过 HTTP 上传的图片（BMP 自动缩放 / 原始 RGB565） |

时钟页布局（参考 HoloCubic 桌面钟）：

```
        10/19 Mon              <- 日期（灰）
                                
          17:53  48             <- 大号时间 + 小号秒（琥珀色）
        ─────────────           <- 分隔线
                                
        [☀]  12~20 C            <- 自绘天气图标 + 温度区间
             humidity 46%       <- 湿度（取自天气 API）
```

HOME 页（方案 A：太空人 + 时钟 + 温湿度条，参考 HoloCubic 布局）：

```
  10/19        ╭─ 太空人 ─╮        ☁      <- 左：日期/星期  右：天气图标
  Mon          ╰──────────╯      Cloudy     <- 天气文字
                                 13°/8°     <- 今日最高/最低
              17:53  48                     <- 双色时间（时白/分橙）+ 秒
  ───────────────────────────────────────   <- 1px 分隔线
  🌡  (████████░░░░░░░░)  10°C              <- 当前温度 + 进度条
  💧  (███████████░░░░░)  65%               <- 湿度 + 进度条
```

> 温湿度没有板载传感器，数值来自天气 API 的**当前值**；
> 温度条映射 `-10～40°C → 0～100%`，湿度条 `0～100%`；更新时带 500ms 动画。

### 5.2 交互

| 动作 | 调试模式（默认） | 完整模式 |
|---|---|---|
| 下一页 | **D13** 短按 | 触摸条短按 / 摇一摇 |
| 上一页 | **D15** 短按 | 触摸条短按 |
| 切换 LCD 显示方向 | **长按 D13** | — |
| 背光 | 固定 80%（menuconfig） | 触摸长按 / 自动亮度 |
| 倒置自动旋转 | 关闭 | 开启 |
| 自动亮度 / 熄屏 | 关闭 | 开启 |

### 5.3 内置网页（联网后）

浏览器打开 `http://<设备IP>/` 或 `http://prismtv.local/`：

- 实时状态：IP / WiFi RSSI / 环境光 / 温度 / 可用内存 / 运行时长；
- **上传图片**：选择本地图片上传即显示；
- **OTA 升级**：填固件 URL 开始在线升级；
- **清除 WiFi 并重启**。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET  | `/`        | 状态页（含上传/OTA） |
| GET  | `/status`  | 运行状态 JSON |
| POST | `/upload`  | 图片上传 |
| POST | `/ota`     | 表单 `url=`，触发 OTA |
| POST | `/reset`   | 清除 wifi 凭据并重启 |

---

## 6. 内置资源与自绘图标

所有内置图形都**没有用现成素材库**，由 `tools/make_assets.py` 生成。

### 6.1 分帧动画

- 素材：`tools/frames/1.jpg … 20.jpg`（128×64 白线稿，2:1）
- 处理：灰度 → 提对比 → LANCZOS 放大到 **230×115**（匹配 230 宽可视区）
- **双层打包**（每帧 10005 B）：
  - `glow`：**ALPHA_2BIT**（6670 B）平滑边缘，显示为发光色；
  - `core`：**ALPHA_1BIT**（3335 B）高亮部分，显示为白色核心；
- 产物：`main/anim_frames.bin`（20 帧 ≈ 195 KB，嵌入 flash）
- 播放：`ui.c` 里 83ms/帧（≈12fps）循环；发光层色相每帧 +1°，
  约 30 秒在青/蓝/紫之间循环一圈。只在 HOME / 动画页播放，切走自动暂停。

### 6.2 天气图标（自绘、分色）

- `make_assets.py` 用 PIL 画形状（4 倍超采样后缩小以抗锯齿）：
  晴 / 多云 / 阴 / 雨 / 雷 / 雪 / 雾 / 霾 共 **8 个 48×48** 图标；
- 每个图标 **两层 alpha 蒙版**：
  - `warm`：太阳 / 闪电 → **黄色**（`0xFFC107`）；
  - `cool`：云 / 雨 / 雪 / 雾 / 霾条 → **蓝色**（`0x4FC3F7`）；
- 产物：`main/weather_icons.bin`（ALPHA_4BIT 双层，共约 18 KB）
- 显示：`ui.c` 把 cool 层垫在下面、warm 层叠在上面，用 `img_recolor` 上色。

### 6.3 关于颜色（可随意改）

两种资源都是 LVGL 的 **alpha 蒙版**（白=不透明，黑=透明），
显示时用 `lv_obj_set_style_img_recolor(obj, 颜色, 0)` **任意上色**，例如：

```c
/* ui.c：主题色 */
#define UI_COLOR_ACCENT 0x00E5FF   /* 青色：秒/系统页强调色 */
#define UI_COLOR_SEC    0xFFD54F   /* 琥珀：秒 */
#define UI_COLOR_TIME   0xFFFFFF   /* 时间白 */
#define UI_COLOR_SUN    0xFFC107   /* 天气图标-太阳/闪电：黄 */
#define UI_COLOR_CLOUD  0x4FC3F7   /* 天气图标-云/雨/雪/雾：蓝 */
```
动画发光色由 `anim_glow_color()` 用 HSV 动态生成（色相缓慢变化），
核心层固定白色。

改完重新编译即可；换帧素材后跑一次 `python3 tools/make_assets.py` 重新生成 `.bin`。

---

## 7. 软件架构

```
app_main
  ├── display_init()      SPI + esp_lcd(ST7789) + esp_lvgl_port + LEDC 背光
  ├── ui_init()           四个页面 + 顶层状态栏
  ├── sensors_init()      新 I2C 总线 + MPU6050(0x68) + BH1750(0x23)
  ├── input_init()        触摸条 / 调试按键
  ├── wifi_prov_start()   连不上就 AP 配网
  ├── web_server_start()  联网后开内置 HTTP 服务
  ├── net_start()         net 任务：mDNS + SNTP + 天气 + 状态
  └── sensor_task         传感器 + 交互 + 电源（50Hz）
```

| 任务 | 核心 | 优先级 | 说明 |
|---|---|---|---|
| LVGL 刷屏任务 | 由 esp_lvgl_port 创建 | — | 独占 SPI 刷屏 |
| `net` | Core0 | 4 | mDNS / SNTP 对时（每秒刷新秒）/ 天气 / OTA |
| `sensors`(调试下叫 `keys`) | Core0 | 5 | 50Hz 采样 + 按键/手势 + 背光电源管理 |

**所有 LVGL API 必须在 `lvgl_port_lock()/unlock()` 之间调用**，`ui.c` 已封装；
`ui.h` 暴露的都是线程安全接口，可从任意任务调用。

---

## 8. 关键实现说明

### 8.1 ST7789 分辨率与偏移
面板物理分辨率 **240×240**，控制器帧存 **240×320**。
- 可见区 Y 偏移本板实测为 **0**（部分 1.3" 模块为 80）；
- 为适配棱镜宽度，实际显示区缩到 **230×230 居中**（四周 5px 黑边）：
  `BOARD_LCD_H_RES/V_RES = 230`、`BOARD_LCD_VIEW_LEFT/TOP = 5`；
- 开机会先把整块 240×240 面板清黑，避免边框露出旧内容；
- 开启 MY 时按 `y_gap = 320 - top - 230` 自动补偿帧存偏移（本板 `top=5` → `y_gap=85`）。

### 8.2 SPI 频率与字节序
上板先用 **20MHz** 验证（本板稳定）；确认无误后可再提到 40MHz。
花屏/噪点则继续降到 10MHz，或在屏幕板 SCLK/MOSI 串 22~33Ω。
SPI 屏需交换 RGB565 高低字节，本工程用 `LV_COLOR_16_SWAP=y` 由 LVGL 完成。

### 8.3 图像朝向（补偿分光棱镜）
分光棱镜成的是**反序/镜像像**，所以 LCD 必须反向显示，棱镜里看才是正的。
用 `PRISM_LCD_ORIENT` 选择方向：

| 值 | 含义 | MADCTL |
|---|---|---|
| 0 | 正常 | — |
| 1 | 左右镜像 | MX |
| 2 | **上下镜像（默认，本板实测）** | MY |
| 3 | 180° 反序 | MX+MY |

调试模式下**长按 D13 可实时循环这 4 种方向**，屏幕 toast + 串口会显示
当前序号；对着棱镜选到正确的一组后，在 menuconfig 里固定即可。

> ⚠️ ST7789 帧存是 240×320，开启 **MY** 后可见窗口会整体偏移 80 行。
> 固件在 `apply_orientation()` 里自动把 Y gap 补偿为 `80 - gap`
> （基础 gap=0 时即 80），否则顶部 80 行会残留旧画面（看起来像彩条）。

### 8.4 时间与天气
- SNTP 对时（`CONFIG_PRISM_TZ` 默认 `CST-8`），net 任务每秒刷新“秒”；
- 天气有两条路：
  - **填了心知天气 Key** → `now.json` 取当前 `temperature/humidity/code`，
    `daily.json` 取 `high/low`；
  - **Key 为空** → 自动改走 **Open-Meteo**（免注册、免 Key），
    一次请求同时取 `current`（当前温度/湿度/天气代码）和
    `daily`（`weather_code / temperature_2m_max/min / relative_humidity_2m_max`）；
    坐标优先用**公网 IP 自动定位**（`ipwho.is`，失败再试 `ip-api.com`），
    定位失败则用 `PRISM_WEATHER_LAT/LON`（默认北京 39.90 / 116.40）；
- 结果统一交给 `ui_set_weather(icon, text, cur_c, low, high, humidity)`：
  时钟页显示温度区间/湿度，HOME 页显示天气文字、最高/最低、
  **当前温度进度条**（-10～40°C → 0～100%）和**湿度进度条**（0～100%）；
- 两套代码都用同一组 **自绘天气图标**（`code_to_icon()` / `wmo_to_icon()`）。

### 8.5 触摸条 / 按键
同一套接口（`input.h`），调试模式内部读 GPIO 按键（D13/D15，硬件去抖），
完整模式读 ESP32 Touch（T0 = GPIO4，基线自校准 + 温漂跟踪）。

注意：上电时若某个按键脚已经是低电平（例如开发板 D2 上的板载 LED 把它拉低），
固件会把它视为“启动前就按着”，**先抑制事件、等松开后**才正常响应，
避免开机误触发长按关背光。串口会打印 `KEYx GPIOx 上电电平=LOW/HIGH`；
若某脚始终为 LOW，请在 menuconfig 换一个空闲 IO（避开 GPIO6~11/16/17/12）。

### 8.6 OTA
分区表双 OTA 槽（`ota_0` + `ota_1`，无 factory），可反复升级；
启动失败 bootloader 自动回滚。

### 8.7 图片内存
图片页缓冲由 `PRISM_IMAGE_RES` 决定：无 PSRAM 的 D4 默认 120×120（约 28KB），
带 PSRAM 的 V3-02 可选 240×240（约 113KB）。优先 PSRAM，失败则退回内部 RAM。

### 8.8 资源格式（供二次开发）
- 动画每帧 = `glow`（`LV_IMG_CF_ALPHA_2BIT`，230 宽 → 58 B/行 ×115 = 6670 B）
  \+ `core`（`LV_IMG_CF_ALPHA_1BIT`，29 B/行 ×115 = 3335 B）
- 天气图标每个 = `warm`（`LV_IMG_CF_ALPHA_4BIT`，48×48 → 24 B/行 ×48 = 1152 B）
  \+ `cool`（同尺寸）

### 8.9 I2C 传感器初始化（防卡死）
先用 `i2c_master_probe()` 探测，只有应答的设备才 `i2c_master_bus_add_device()`；
所有 I2C 事务使用 **50ms 有限超时**（绝不使用 `-1` 永久等待），并打开内部上拉。
这样即使没接传感器、没有外部上拉，启动也不会卡死。
调试模式默认 `PRISM_DEBUG_NO_SENSORS=y`，完全跳过 I2C。

---

## 9. 二次开发入口

| 想改什么 | 改哪里 |
|---|---|
| 引脚定义 | `main/board_config.h` |
| 时钟页布局 | `main/ui.c` 的 `build_clock_page()` |
| 动画播放速度 / 上色 | `main/ui.c`（`build_anim_page()`、`UI_COLOR_*`） |
| 换动画素材 | `firmware/tools/frames/` + 跑 `make_assets.py` |
| 天气图标 | `tools/make_assets.py` 里的 `icon_*()` |
| 天气代码→图标映射 | `main/net_task.c` 的 `code_to_icon()` |
| 触摸算法 | `main/input.c` |
| 手势逻辑 | `main/main.c` 的 `sensor_task()` |
| 天气 API | `main/net_task.c` 的 `weather_fetch()` |
| 网页/上传/OTA | `main/web_server.c` |
| 新增传感器 | 参照 `sensors.c`，在同一 `s_bus` 上 `i2c_master_bus_add_device()` |

---

## 10. 调试模式

开关在 `menuconfig → Prism TV → 调试 / Debug`。

| 项 | 调试模式 | 完整模式 |
|---|---|---|
| 棱镜光路校正（镜像/旋转） | 在 `display.c` 中**注释** | 启用（上板实测后写死） |
| 翻页 | 按键 D13 / D15 短按 | 触摸条短按 / 摇一摇 |
| 背光开关 | 按键长按 | 触摸条长按 |
| 倒置自动旋转 | 关闭 | 启用 |
| 自动亮度 / 自动熄屏 | 关闭（固定背光） | 启用（BH1750） |
| WiFi / NTP / 天气 / HTTP | **默认启用**（可关） | 启用 |
| 传感器 / I2C | **默认关闭**（不初始化 I2C） | 启用（probe + 有限超时） |

**纯点屏**（反复复位调 SPI，不联网）：
打开 `调试 / Debug → 调试模式：纯点屏，不启动 WiFi/网络`（`CONFIG_PRISM_DEBUG_NO_NET`），
此时固件不含 WiFi，体积回到 ~0.7MB，但时间/天气不会更新。

**引脚选择注意（ESP32-PICO-D4）**：
- **不可用**：`GPIO6~11 / 16 / 17`（内部 Flash）、`GPIO12`（Flash 电压，禁止拉高）；
- `D15` 是 strapping 脚（MTDO），**上电/复位时不要按住**；
- `D2`(GPIO2) 在很多开发板上被板载 LED 拉低（实测上电电平 = LOW），**不适合做按键**，本项目已改用 `D13`；
- `D13`(GPIO13) 是空闲 IO、无板载器件，做按键正常；
- 只接一个按键时，把「上一页」设为 `-1`。

**恢复完整功能**：关闭「调试模式：按键翻页…」，重新 `idf.py build`。

---

## 11. 依赖版本

| 组件 | 版本 | 来源 |
|---|---|---|
| ESP-IDF | v5.5.6 | `/home/ming/source/esp-idf` |
| lvgl/lvgl | 8.3.11 | 组件管理器 |
| espressif/esp_lvgl_port | 1.4.0 | 组件管理器 |
| espressif/mdns | 1.14.0 | 组件管理器 |
| esp_lcd (ST7789) | IDF 内置 | 官方 |

> 组件在首次 `idf.py build` 时自动下载到 `firmware/managed_components/`，需要联网。
