# Music Search

Ứng dụng web để nhận diện bài nhạc đang phát trên máy hoặc từ file audio upload.

Dự án dùng `ffmpeg` để thu âm thanh hệ thống hoặc đọc file audio, dùng `vibra` để nhận diện bài hát, rồi hiển thị kết quả trên giao diện web.

![Giao diện Music Search](scripts/image.png)

## Tính năng

- Nhận diện bài hát đang phát trên máy.
- Chọn nguồn audio thủ công hoặc để Auto tự chọn nguồn đang phát.
- Nhận diện bài hát từ file audio upload.
- Có link mở kết quả trên Shazam.
- Lưu lịch sử 10 bài gần nhất.

## Build prerequisites

Dự án dùng cho Linux có PulseAudio/PipeWire Pulse.

Môi trường build cần có:

- Python 3
- `ffmpeg`
- `pactl`
- `vibra`
- `appimagetool`

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

Source runtime nằm trong `src/`. Thư mục `build_linux/` chứa cấu hình build AppImage.

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
build_linux/dist/MusicSearch-0.2.0-x86_64.AppImage
```

Chạy AppImage:

```bash
./build_linux/dist/MusicSearch-0.2.0-x86_64.AppImage
```

Khi chạy, ứng dụng tự mở giao diện trong trình duyệt. AppImage đã bundle code Python, giao diện web, `ffmpeg`, `vibra`, `pactl`, desktop metadata và icon. Build artifact trên môi trường Linux tương thích với nền tảng phân phối.

Runtime data như lịch sử nhận diện được lưu theo XDG state, mặc định tại:

```text
~/.local/state/music-search/history.jsonl
```
