import socket
from unittest.mock import MagicMock, patch

from installer.detect import (
    GpuInfo,
    detect_amd_gpus,
    detect_host_ip,
    detect_intel_gpus,
    detect_nvidia_gpus,
    detect_os_is_atomic,
    detect_primary_gpu,
    port_in_use,
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


def test_port_in_use_true_for_a_real_bound_port():

    # Real functional check, no mocking - bind an actual listening
    # socket on an OS-assigned ephemeral port and confirm it's
    # detected, the same way a real native service would be.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)

    try:
        port = listener.getsockname()[1]
        assert port_in_use(port) is True
    finally:
        listener.close()


def test_port_in_use_false_for_a_closed_port():

    # Bind-then-immediately-close to get a real ephemeral port number
    # that's genuinely free right now, rather than guessing a literal.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()

    assert port_in_use(port) is False


def test_detect_os_is_atomic_true_when_ostree_marker_present():
    """
    /run/ostree-booted is the real, confirmed marker - checked
    against an actual Bazzite host (a real GPU machine reached over
    Tailscale) while building this: present there, and this project's
    own dev machine (a normal mutable Fedora) has no such file.
    """

    with patch("installer.detect.Path") as mock_path:

        mock_path.return_value.exists.return_value = True

        assert detect_os_is_atomic() is True


def test_detect_os_is_atomic_false_on_a_normal_mutable_distro():

    with patch("installer.detect.Path") as mock_path, patch(
        "installer.detect.shutil.which", return_value=None
    ):

        mock_path.return_value.exists.return_value = False

        assert detect_os_is_atomic() is False


def test_detect_os_is_atomic_falls_back_to_rpm_ostree_on_path():
    """
    A narrower fallback signal, not the primary one - the marker file
    not existing but rpm-ostree still being on PATH (an edge case not
    observed against real hardware, unlike the marker-file path above).
    """

    with patch("installer.detect.Path") as mock_path, patch(
        "installer.detect.shutil.which", return_value="/usr/bin/rpm-ostree"
    ):

        mock_path.return_value.exists.return_value = False

        assert detect_os_is_atomic() is True


def test_detect_host_ip_returns_a_real_address():
    """
    Genuinely unmocked, mirroring Vulcan's own identical test for the
    identical function - this machine has a real route out, so this
    exercises the real socket call rather than assuming the technique
    works.
    """

    result = detect_host_ip()

    assert result is not None
    assert result.count(".") == 3
