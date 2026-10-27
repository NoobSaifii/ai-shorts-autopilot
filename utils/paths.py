import re
import time
from pathlib import Path


def safe_title(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_ ]", "", title).strip()
    underscored = re.sub(r"\s+", "_", cleaned)
    collapsed = re.sub(r"_+", "_", underscored).strip("_")
    return collapsed or "Untitled_Project"


class ProjectPaths:
    def __init__(self, output_root: str, title: str):
        self.title = safe_title(title)
        self.root = Path(output_root) / self.title
        self.images = self.root / "images"
        self.audio = self.root / "audio"
        self.silent_video = self.root / "silent_video"
        self.scene_video = self.root / "scene_video"
        self.final = self.root / "final"

    def create_all(self):
        for d in [self.images, self.audio, self.silent_video, self.scene_video, self.final]:
            d.mkdir(parents=True, exist_ok=True)

    def _stamp(self) -> int:
        return int(time.time() * 1000)

    def image_path(self, scene_no: int, ext: str = "jpg") -> Path:
        return self.images / f"{self.title}_scene_{str(scene_no).zfill(2)}_{self._stamp()}.{ext}"

    def raw_audio_path(self, scene_no: int) -> Path:
        return self.audio / f"{self.title}_scene_{str(scene_no).zfill(2)}_{self._stamp()}_raw.wav"

    def subtitle_path(self, scene_no: int) -> Path:
        return self.audio / f"{self.title}_scene_{str(scene_no).zfill(2)}_{self._stamp()}.ass"

    def silent_video_path(self, scene_no: int) -> Path:
        return self.silent_video / f"{self.title}_scene_{str(scene_no).zfill(2)}_{self._stamp()}_silent.mp4"

    def scene_video_path(self, scene_no: int) -> Path:
        return self.scene_video / f"{self.title}_scene_{str(scene_no).zfill(2)}_{self._stamp()}.mp4"

    def final_video_path(self) -> Path:
        return self.final / f"{self.title}_final_{self._stamp()}.mp4"

    def final_bgm_path(self) -> Path:
        return self.final / f"{self.title}_with_bgm_{self._stamp()}.mp4"
