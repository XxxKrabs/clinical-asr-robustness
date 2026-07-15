from __future__ import annotations

import numpy as np
import pytest

from scripts.preprocess_asr_audio import slice_resampled_audio, window_ranges


def test_slice_resampled_audio_uses_absolute_window_offsets() -> None:
    audio = np.arange(80, dtype=np.float32)

    sliced = slice_resampled_audio(
        audio,
        decoded_start_sec=10.0,
        window_start_sec=12.0,
        window_end_sec=15.0,
        sample_rate=10,
    )

    assert sliced.tolist() == list(range(20, 50))


def test_slice_resampled_audio_rejects_empty_window() -> None:
    with pytest.raises(ValueError, match="音频窗口为空"):
        slice_resampled_audio(
            np.arange(10, dtype=np.float32),
            decoded_start_sec=0.0,
            window_start_sec=2.0,
            window_end_sec=3.0,
            sample_rate=10,
        )


def test_window_ranges_keep_contiguous_tail() -> None:
    assert window_ranges(
        source_duration_sec=65.0,
        clip_start_sec=0.0,
        clip_duration_sec=None,
        window_sec=30.0,
        max_windows=None,
    ) == [(0.0, 30.0), (30.0, 60.0), (60.0, 65.0)]
