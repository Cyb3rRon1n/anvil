from unittest.mock import MagicMock, patch

from installer.detect import (
    GpuInfo,
    detect_amd_gpus,
    detect_intel_gpus,
    detect_nvidia_gpus,
    detect_primary_gpu,
)


def test_detect_nvidia_gpus_parses_real_csv_shape():

    # Real shape confirmed via NVIDIA's own docs: one CSV line per GPU.
    proc = MagicMock(returncode=0, stdout="RTX 3060, 12288\nRTX 4090, 24564\n")

    with patch("installer.detect.shutil.which", return_value="/usr/bin/nvidia-smi"), patch(
        "installer.detect.subprocess.run", return_value=proc
    ):

        gpus = detect_nvidia_gpus()

    assert gpus == [
        GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288),
        GpuInfo(vendor="nvidia", name="RTX 4090", vram_total_mb=24564),
    ]


def test_detect_nvidia_gpus_absent_binary_returns_empty():

    with patch("installer.detect.shutil.which", return_value=None):
        assert detect_nvidia_gpus() == []


def test_detect_nvidia_gpus_binary_present_but_query_fails_returns_empty():
    """
    The exact class of false positive this module exists to avoid -
    a present-but-non-functional tool must not be reported as a GPU.
    """

    proc = MagicMock(returncode=1, stdout="")

    with patch("installer.detect.shutil.which", return_value="/usr/bin/nvidia-smi"), patch(
        "installer.detect.subprocess.run", return_value=proc
    ):

        assert detect_nvidia_gpus() == []


def test_detect_amd_gpus_reads_real_sysfs_shape(tmp_path):

    card_dir = tmp_path / "card0" / "device"
    card_dir.mkdir(parents=True)
    (card_dir / "vendor").write_text("0x1002\n")
    (card_dir / "mem_info_vram_total").write_text(str(16 * 1024 * 1024 * 1024) + "\n")

    with patch("installer.detect.Path") as mock_path:

        mock_path.return_value = tmp_path
        mock_path.side_effect = lambda p: tmp_path if p == "/sys/class/drm" else __import__("pathlib").Path(p)

        gpus = detect_amd_gpus()

    assert gpus == [GpuInfo(vendor="amd", name=None, vram_total_mb=16384)]


def test_detect_amd_gpus_skips_non_amd_vendor_id(tmp_path):
    """
    Real finding: this exact shape (a card directory with a vendor
    file but no mem_info_* files) is what a real Intel iGPU looks
    like - confirmed against this project's own dev machine.
    """

    card_dir = tmp_path / "card1" / "device"
    card_dir.mkdir(parents=True)
    (card_dir / "vendor").write_text("0x8086\n")

    with patch("installer.detect.Path") as mock_path:

        mock_path.side_effect = lambda p: tmp_path if p == "/sys/class/drm" else __import__("pathlib").Path(p)

        gpus = detect_amd_gpus()

    assert gpus == []


def test_detect_intel_gpus_parses_real_field_name():

    proc = MagicMock(returncode=0, stdout='{"Memory Physical Size": "16384.00 MiB", "Device Name": "Arc A770"}')
    fail_proc = MagicMock(returncode=1, stdout="")

    with patch("installer.detect.shutil.which", return_value="/usr/bin/xpu-smi"), patch(
        "installer.detect.subprocess.run", side_effect=[proc, fail_proc]
    ):

        gpus = detect_intel_gpus()

    assert gpus == [GpuInfo(vendor="intel", name="Arc A770", vram_total_mb=16384)]


def test_detect_intel_gpus_absent_binary_returns_empty():

    with patch("installer.detect.shutil.which", return_value=None):
        assert detect_intel_gpus() == []


def test_detect_primary_gpu_picks_largest_card_not_sum():

    gpus = [
        GpuInfo(vendor="nvidia", name="RTX 3060", vram_total_mb=12288),
        GpuInfo(vendor="nvidia", name="RTX 4090", vram_total_mb=24564),
    ]

    assert detect_primary_gpu(gpus) == gpus[1]


def test_detect_primary_gpu_none_when_no_gpus():
    assert detect_primary_gpu([]) is None
