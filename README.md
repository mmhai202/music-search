# Music Search

Ứng dụng web để nhận diện bài nhạc đang phát trên máy.

Dự án dùng `ffmpeg` để thu âm thanh hệ thống, dùng `vibra` để nhận diện bài hát, rồi hiển thị kết quả trên giao diện web.

![Giao diện Music Search](scripts/image.png)

## Tính năng

- Nhận diện bài hát đang phát trên máy.
- Có link mở kết quả trên Shazam.
- Lưu lịch sử 10 bài gần nhất.

## Yêu cầu

Dự án phù hợp nhất với Linux có PulseAudio/PipeWire Pulse.

Cần có:

- Python 3
- `ffmpeg`
- `pactl`
- `vibra`

## Cài đặt

Clone repo:

```bash
git clone <repo-url>
cd music-search
```

Cài dependency:

```bash
bash scripts/install_deps.sh
```

Script này sẽ cài các gói cần thiết và build `vibra`.

## Chạy ứng dụng

```bash
python3 app.py
```

Sau đó mở trình duyệt:

```text
http://127.0.0.1:8765
```

bấm nút **Tìm bài đang phát**, chờ vài giây để ứng dụng nhận diện.
