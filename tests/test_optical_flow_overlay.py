"""Unit tests for optical-flow overlay visualization helpers."""

from __future__ import annotations

import unittest

import numpy as np

from actintrack_app.optical_flow_motion_index import OpticalFlowResult, OpticalFlowSettings
from actintrack_app.optical_flow_overlay import (
    OpticalFlowVisualizationSettings,
    build_flow_cache,
    format_optical_flow_qc,
    get_flow_arrows_for_frame,
    render_optical_flow_overlay,
    resolve_frame_pair_index,
    resolve_qc_status,
    sample_flow_vectors,
)


def _shifted_frames(count: int = 5, dy: int = 2) -> list[np.ndarray]:
    frames: list[np.ndarray] = []
    for i in range(count):
        frame = np.zeros((48, 48), dtype=np.uint8)
        y0 = 8 + i * dy
        frame[y0 : y0 + 10, 12:36] = 220
        frames.append(frame)
    return frames


class OpticalFlowOverlayTests(unittest.TestCase):
    def test_resolve_frame_pair_index(self) -> None:
        self.assertIsNone(resolve_frame_pair_index(0, 1))
        self.assertEqual(resolve_frame_pair_index(0, 5), 0)
        self.assertEqual(resolve_frame_pair_index(3, 5), 3)
        self.assertEqual(resolve_frame_pair_index(4, 5), 3)

    def test_sample_flow_vectors_respects_mask(self) -> None:
        flow = np.zeros((24, 24, 2), dtype=np.float32)
        flow[12, 12, 1] = 2.0
        mask = np.zeros((24, 24), dtype=bool)
        mask[12, 12] = True
        viz = OpticalFlowVisualizationSettings(arrow_spacing_px=8, arrow_scale=2.0)
        arrows = sample_flow_vectors(flow, mask, viz)
        self.assertEqual(len(arrows), 1)
        self.assertGreater(arrows[0].dy, 0.0)

    def test_build_flow_cache_reuse(self) -> None:
        settings = OpticalFlowSettings(mask_percentile=50)
        frames = _shifted_frames()
        cache1 = build_flow_cache(frames, settings, sample_id="S1", fingerprint="fp1")
        cache2 = build_flow_cache(frames, settings, sample_id="S1", fingerprint="fp1")
        self.assertEqual(cache1.pair_count(), len(frames) - 1)
        self.assertEqual(cache2.pair_count(), cache1.pair_count())

    def test_get_flow_arrows_for_frame(self) -> None:
        settings = OpticalFlowSettings(mask_percentile=40, gaussian_blur_kernel=0)
        frames = _shifted_frames()
        cache = build_flow_cache(frames, settings, sample_id="S1", fingerprint="fp1")
        arrows = get_flow_arrows_for_frame(
            cache,
            1,
            len(frames),
            OpticalFlowVisualizationSettings(arrow_spacing_px=8),
        )
        self.assertGreaterEqual(len(arrows), 0)
        self.assertGreater(cache.pair_count(), 0)

    def test_render_optical_flow_overlay(self) -> None:
        frame = np.zeros((32, 32), dtype=np.uint8)
        frame[10:20, 10:20] = 200
        from actintrack_app.optical_flow_overlay import FlowArrow

        out = render_optical_flow_overlay(
            frame, [FlowArrow(x=15, y=15, dx=0.0, dy=4.0)]
        )
        self.assertEqual(out.shape[:2], frame.shape[:2])

    def test_format_optical_flow_qc_missing(self) -> None:
        qc = format_optical_flow_qc(None)
        self.assertEqual(qc["general_movement"], "—")

    def test_resolve_qc_status_paths(self) -> None:
        self.assertEqual(
            resolve_qc_status(result=None, is_computing=True, is_stale_flag=False),
            "Computing…",
        )
        self.assertEqual(
            resolve_qc_status(result=None, is_computing=False, is_stale_flag=False),
            "Not computed",
        )
        bad = OpticalFlowResult(has_valid_result=False, failure_reason="fail")
        self.assertEqual(
            resolve_qc_status(result=bad, is_computing=False, is_stale_flag=False),
            "Error",
        )
        good = OpticalFlowResult(
            has_valid_result=True,
            fingerprint="abc",
            optical_flow_general_movement_um_s=1.0,
        )
        self.assertEqual(
            resolve_qc_status(
                result=good,
                is_computing=False,
                is_stale_flag=False,
                current_fingerprint="abc",
            ),
            "Fresh",
        )
        self.assertEqual(
            resolve_qc_status(
                result=good,
                is_computing=False,
                is_stale_flag=True,
                current_fingerprint="abc",
            ),
            "Stale",
        )


if __name__ == "__main__":
    unittest.main()
