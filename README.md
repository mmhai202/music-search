# Music Search

Ứng dụng web để nhận diện bài nhạc đang phát trên máy, từ microphone hoặc từ file audio upload.

Dự án dùng `ffmpeg` để thu âm thanh hệ thống, thu microphone hoặc đọc file audio, dùng `vibra` để nhận diện bài hát, rồi hiển thị kết quả trên giao diện web.

![Giao diện Music Search](scripts/image.png)

## Tính năng

- Nhận diện bài hát đang phát trên máy.
- Chọn nguồn audio thủ công hoặc để Auto tự chọn nguồn đang phát.
- Ghi âm từ microphone để nhận diện, có chọn microphone thủ công hoặc Auto.
- Nhận diện bài hát từ file audio upload.
- Có link mở kết quả trên Shazam.
- Lưu lịch sử 10 bài gần nhất.

## Build prerequisites

Dự án hỗ trợ build artifact cho Linux và Windows. Linux dùng PulseAudio/PipeWire Pulse. Windows dùng WASAPI loopback qua `SoundCard`.

Môi trường build Linux cần có:

- Python 3
- `ffmpeg`
- `pactl`
- `vibra`
- `appimagetool`

Môi trường build Windows cần có:

- Python 3
- `ffmpeg.exe`
- `vibra.exe`

## Chuẩn bị

Clone repo:

```bash
git clone <repo-url>
cd music-search
```

Cài dependency:

```bash
bash scripts/install_deps.sh
```

Script này sẽ cài các gói hệ thống cần thiết, cài `appimagetool` nếu máy build chưa có, và build `vibra`.

Source runtime nằm trong `src/`. Version release nằm tại `VERSION`. Thư mục `build_linux/` chứa cấu hình build AppImage. Thư mục `build_windows/` chứa cấu hình build portable ZIP.

## Build Linux

Tạo release artifact cho Linux:

```bash
bash build_linux/build_linux.sh --clean
```

Dọn artefact build/cache trong workspace:

```bash
bash scripts/clean_ws.sh
```

Artifact:

```text
build_linux/dist/MusicSearch-0.3.1-x86_64.AppImage
```

Chạy AppImage:

```bash
./build_linux/dist/MusicSearch-0.3.1-x86_64.AppImage
```

Khi chạy, ứng dụng tự mở giao diện trong trình duyệt. AppImage đã bundle code Python, giao diện web, `ffmpeg`, `vibra`, `pactl`, desktop metadata và icon. Build artifact trên môi trường Linux tương thích với nền tảng phân phối.

Runtime data như lịch sử nhận diện được lưu theo XDG state, mặc định tại:

```text
~/.local/state/music-search/history.jsonl
```

## Build Windows

Tạo release artifact portable ZIP trên Windows:

```powershell
powershell -ExecutionPolicy Bypass -File build_windows/build_windows.ps1 -Clean
```

Artifact:

```text
build_windows/dist/MusicSearch-0.3.1-windows-x86_64.zip
```

Giải nén ZIP và chạy `MusicSearch.exe`. Runtime data mặc định lưu tại:

```text
%LOCALAPPDATA%\MusicSearch\history.jsonl
```

## Build CI

Luồng build chính thức nằm trong GitHub Actions:

- `ubuntu-22.04`: build Linux AppImage.
- `windows-2022`: build Windows portable ZIP.

Mỗi job chạy smoke test `/api/health`, `/`, `/app.js`, `/styles.css` và `/api/history` trước khi upload artifact.
